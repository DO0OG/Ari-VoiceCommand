import json
import threading
import unittest
from unittest.mock import patch

from services.messaging_bridge_base import ChatAuthorizer, IncomingMessage, StreamingTextBuffer
from services.telegram_bridge import TelegramApiClient, TelegramBridge


class FakeTelegramClient:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.photos = []

    def send_message(self, chat_id, text, reply_to_message_id=None):
        self.sent.append((chat_id, text, reply_to_message_id))
        return len(self.sent)

    def edit_message(self, chat_id, message_id, text):
        self.edited.append((chat_id, message_id, text[:4096]))

    def send_photo(self, chat_id, image_path, caption=""):
        self.photos.append((chat_id, image_path, caption))
        return 99


class ImmediateQueue:
    def __init__(self):
        self.submitted = []

    def submit(self, goal, runner, *, priority=50, task_id=None):
        self.submitted.append((goal, priority))
        runner(threading.Event())
        return task_id or "task-1"

    def shutdown(self, cancel_pending=True):
        pass


class TelegramBridgeTests(unittest.TestCase):
    def test_authorizer_rejects_unknown_chat(self):
        client = FakeTelegramClient()
        bridge = TelegramBridge(
            client,
            lambda text, stream_callback=None: "unused",
            allowed_chat_ids=["123"],
            queue=ImmediateQueue(),
        )

        self.assertIsNone(bridge.handle_message(IncomingMessage(chat_id="999", text="hello")))
        self.assertEqual(client.sent, [])

    def test_authorized_message_runs_command_and_edits_status(self):
        client = FakeTelegramClient()

        def runner(text, stream_callback=None):
            self.assertEqual(text, "status")
            stream_callback("working")
            return "done"

        bridge = TelegramBridge(
            client,
            runner,
            allowed_chat_ids=["123"],
            queue=ImmediateQueue(),
        )

        task_id = bridge.handle_message(IncomingMessage(chat_id="123", text="status", message_id=7))

        self.assertEqual(task_id, "task-1")
        self.assertEqual(client.sent[0], ("123", "Processing...", 7))
        self.assertIn(("123", 1, "done"), client.edited)

    def test_streaming_buffer_throttles_and_flushes(self):
        emitted = []
        buffer = StreamingTextBuffer(emitted.append, min_chars=5)

        buffer.append("he")
        self.assertEqual(emitted, [])
        buffer.append("llo")
        self.assertEqual(emitted, ["hello"])
        buffer.append("!")
        self.assertEqual(emitted[-1], "hello!")

    def test_chat_authorizer_accepts_stringified_ids(self):
        authorizer = ChatAuthorizer([123, "456"])

        self.assertTrue(authorizer.is_allowed("123"))
        self.assertTrue(authorizer.is_allowed(456))
        self.assertFalse(authorizer.is_allowed("789"))

    def test_does_not_send_photo_for_path_only_mentioned_in_response(self):
        client = FakeTelegramClient()
        bridge = TelegramBridge(
            client,
            lambda text, stream_callback=None: r"C:\tmp\shot.png",
            allowed_chat_ids=["123"],
            queue=ImmediateQueue(),
        )

        with patch("services.telegram_bridge.os.path.isfile", return_value=True):
            bridge.handle_message(IncomingMessage(chat_id="123", text="screenshot"))

        self.assertEqual(client.photos, [])

    def test_sends_photo_reported_by_screenshot_tool(self):
        client = FakeTelegramClient()

        def runner(text, stream_callback=None, *, tool_result_callback=None):
            tool_result_callback("take_screenshot", r"C:\tmp\shot.png")
            return "찍었습니다."

        bridge = TelegramBridge(
            client,
            runner,
            allowed_chat_ids=["123"],
            queue=ImmediateQueue(),
        )

        with patch("services.telegram_bridge.os.path.isfile", return_value=True):
            bridge.handle_message(IncomingMessage(chat_id="123", text="screenshot"))

        self.assertEqual(client.photos, [("123", r"C:\tmp\shot.png", "screenshot")])

    def test_sends_photo_reported_by_image_generator(self):
        client = FakeTelegramClient()
        payload = json.dumps({"enabled": True, "path": r"C:\tmp\art.png", "size": "1024x1024"})

        def runner(text, stream_callback=None, *, tool_result_callback=None):
            tool_result_callback("generate_image", payload)
            tool_result_callback("get_clipboard", r"C:\tmp\other.png")
            return "그렸습니다."

        bridge = TelegramBridge(
            client,
            runner,
            allowed_chat_ids=["123"],
            queue=ImmediateQueue(),
        )

        with patch("services.telegram_bridge.os.path.isfile", return_value=True):
            bridge.handle_message(IncomingMessage(chat_id="123", text="draw"))

        self.assertEqual(client.photos, [("123", r"C:\tmp\art.png", "screenshot")])

    def test_api_client_splits_long_message_into_chunks(self):
        long_text = "\uAC00" * 9000
        posts = []

        class _FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"ok": True, "result": {"message_id": 5}}

        class _FakeSession:
            def post(self, url, json=None, timeout=None):
                posts.append(json["text"])
                return _FakeResponse()

        client = TelegramApiClient("token", session=_FakeSession())

        client.send_message("123", long_text)

        self.assertEqual("".join(posts), long_text)
        self.assertTrue(all(len(body) <= 4096 for body in posts))

    def test_long_final_response_is_delivered_in_full(self):
        client = FakeTelegramClient()
        long_text = "가" * 9000
        bridge = TelegramBridge(
            client,
            lambda text, stream_callback=None: long_text,
            allowed_chat_ids=["123"],
            queue=ImmediateQueue(),
        )

        bridge.handle_message(IncomingMessage(chat_id="123", text="long"))

        delivered = client.edited[-1][2] + "".join(body for _chat, body, _reply in client.sent[1:])
        self.assertEqual(delivered, long_text)
        self.assertTrue(all(len(body) <= 4096 for _chat, body, _reply in client.sent))

    def test_command_error_notifies_chat(self):
        client = FakeTelegramClient()

        def runner(text, stream_callback=None):
            raise RuntimeError("boom")

        bridge = TelegramBridge(
            client,
            runner,
            allowed_chat_ids=["123"],
            queue=ImmediateQueue(),
        )

        with self.assertRaises(RuntimeError):
            bridge._run_message(IncomingMessage(chat_id="123", text="fail", message_id=3), threading.Event())

        self.assertEqual(client.sent[0], ("123", "Processing...", 3))
        self.assertIn(("123", 1, "Error: boom"), client.edited)


if __name__ == "__main__":
    unittest.main()

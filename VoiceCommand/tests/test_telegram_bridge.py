import threading
import unittest
from unittest.mock import patch

from services.messaging_bridge_base import ChatAuthorizer, IncomingMessage, StreamingTextBuffer
from services.telegram_bridge import TelegramBridge


class FakeTelegramClient:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.photos = []

    def send_message(self, chat_id, text, reply_to_message_id=None):
        self.sent.append((chat_id, text, reply_to_message_id))
        return len(self.sent)

    def edit_message(self, chat_id, message_id, text):
        self.edited.append((chat_id, message_id, text))

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

    def test_sends_photo_when_result_is_image_path(self):
        client = FakeTelegramClient()
        bridge = TelegramBridge(
            client,
            lambda text, stream_callback=None: r"C:\tmp\shot.png",
            allowed_chat_ids=["123"],
            queue=ImmediateQueue(),
        )

        with patch("services.telegram_bridge.os.path.isfile", return_value=True):
            bridge.handle_message(IncomingMessage(chat_id="123", text="screenshot"))

        self.assertEqual(client.photos, [("123", r"C:\tmp\shot.png", "screenshot")])

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

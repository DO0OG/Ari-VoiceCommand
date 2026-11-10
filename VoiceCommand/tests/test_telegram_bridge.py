import json
import threading
import traceback
import unittest
from unittest.mock import patch

from agent.confirmation_manager import ConfirmationManager
from agent.safety_checker import DangerLevel, SafetyReport
from agent.task_queue import AgentTaskQueue

from services.messaging_bridge_base import ChatAuthorizer, IncomingMessage, StreamingTextBuffer
from services.telegram_bridge import TelegramApiClient, TelegramBridge


class FakeTelegramClient:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.photos = []
        self.markups = []
        self.answered = []
        self.approval_sent = threading.Event()

    def send_message(self, chat_id, text, reply_to_message_id=None, reply_markup=None):
        self.sent.append((chat_id, text, reply_to_message_id))
        if reply_markup is not None:
            self.markups.append(reply_markup)
            self.approval_sent.set()
        return len(self.sent)

    def edit_message(self, chat_id, message_id, text, reply_markup=None):
        self.edited.append((chat_id, message_id, text[:4096]))

    def answer_callback_query(self, callback_query_id):
        self.answered.append(callback_query_id)

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
    def _start_approval(self, client=None, **options):
        client = client or FakeTelegramClient()
        manager = object.__new__(ConfirmationManager)
        results = []

        def runner(text, stream_callback=None):
            results.append(manager.request_confirmation("delete example.txt", SafetyReport(
                level=DangerLevel.DANGEROUS, summary="file deletion")))
            return "done"

        bridge = TelegramBridge(client, runner, allowed_chat_ids=["123", "456"],
                                queue=ImmediateQueue(), **options)
        worker = threading.Thread(target=bridge._run_message, args=(
            IncomingMessage(chat_id="123", text="delete", message_id=7), threading.Event()))
        worker.start()
        self.addCleanup(worker.join, 2)
        self.addCleanup(bridge.stop)
        return bridge, client, worker, results

    def _callback(self, client, choice=0, chat_id="123", data=None):
        return {"id": "callback-1", "message": {"chat": {"id": chat_id}, "message_id": 2},
                "data": data or client.markups[-1]["inline_keyboard"][0][choice]["callback_data"]}

    def test_remote_approval_buttons_return_decision(self):
        for choice, expected, status in ((0, True, "승인됨"), (1, False, "거부됨")):
            with self.subTest(choice=choice):
                bridge, client, worker, results = self._start_approval(remote_approval_enabled=True)
                self.assertTrue(client.approval_sent.wait(2))
                bridge._handle_callback_query(self._callback(client, choice))
                worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(results, [expected])
                self.assertEqual(client.answered, ["callback-1"])
                self.assertIn(status, client.edited[0][2])
                self.assertIn("delete example.txt", client.sent[1][1])
                self.assertIn("file deletion", client.sent[1][1])

    def test_stop_during_result_update_denies_approval(self):
        bridge, client, worker, results = self._start_approval(remote_approval_enabled=True)
        client.edit_message = lambda *args, **kwargs: bridge._stop_event.set()
        self.assertTrue(client.approval_sent.wait(2))
        bridge._handle_callback_query(self._callback(client, 0))
        worker.join(2)
        self.assertEqual(results, [False])

    def test_remote_approval_ignores_other_chats_and_wrong_nonce(self):
        bridge, client, worker, results = self._start_approval(remote_approval_enabled=True)
        self.assertTrue(client.approval_sent.wait(2))
        for chat_id, data in (("456", None), ("999", None), ("123", "wrong:approve")):
            bridge._handle_callback_query(self._callback(client, chat_id=chat_id, data=data))
            self.assertEqual(results, [])
            self.assertEqual(client.answered, [])
        bridge._handle_callback_query(self._callback(client))
        worker.join(2)
        self.assertEqual(results, [True])
        bridge._handle_callback_query(self._callback(client))
        self.assertEqual(client.answered, ["callback-1"])

    def test_remote_approval_timeout_denies_and_expires_nonce(self):
        with patch("services.telegram_bridge.REMOTE_APPROVAL_TIMEOUT_SECONDS", 0.02):
            bridge, client, worker, results = self._start_approval(remote_approval_enabled=True)
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [False])
        self.assertIn("시간 초과", client.edited[0][2])
        bridge._handle_callback_query(self._callback(client))
        self.assertEqual(client.answered, [])

    def test_remote_approval_errors_deny(self):
        for method in ("send_message", "answer_callback_query", "edit_message"):
            with self.subTest(method=method):
                client = FakeTelegramClient()
                original_send = client.send_message

                def send(*args, **kwargs):
                    if kwargs.get("reply_markup") is not None:
                        raise RuntimeError("send failed")
                    return original_send(*args, **kwargs)

                failure = send if method == "send_message" else RuntimeError("request failed")
                patch_args = {"side_effect": failure}
                with patch.object(client, method, **patch_args):
                    bridge, client, worker, results = self._start_approval(
                        client, remote_approval_enabled=True)
                    if method != "send_message":
                        self.assertTrue(client.approval_sent.wait(2))
                        bridge._handle_callback_query(self._callback(client))
                    worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(results, [False])

    def test_disabled_remote_approval_uses_local_confirmation(self):
        results = []
        client = FakeTelegramClient()
        manager = ConfirmationManager()

        def show(action, report, holder):
            holder["result"] = True
            holder["event"].set()

        def runner(text, stream_callback=None):
            results.append(manager.request_confirmation("delete", SafetyReport(DangerLevel.CAUTION)))
            return "done"

        bridge = TelegramBridge(client, runner, allowed_chat_ids=["123"], queue=ImmediateQueue())
        with patch.object(manager._bridge, "request_dialog") as signal:
            signal.emit.side_effect = show
            bridge.handle_message(IncomingMessage(chat_id="123", text="delete"))
        self.assertEqual(results, [True])
        self.assertEqual(client.markups, [])
        bridge._handle_callback_query({"id": "ignored", "data": "anything"})
        self.assertEqual(client.answered, [])

    def test_from_settings_enables_remote_approval_explicitly(self):
        settings = {"telegram_enabled": True, "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"], "telegram_remote_approval_enabled": True}
        with patch("services.telegram_bridge.ConfigManager.get", side_effect=lambda key, default=None: settings.get(key, default)), \
                patch("services.telegram_bridge.TelegramApiClient", return_value=FakeTelegramClient()):
            bridge = TelegramBridge.from_settings(lambda text, stream=None: "done")
        self.addCleanup(bridge.stop)
        self.assertTrue(bridge.remote_approval_enabled)

    def test_polling_receives_messages_while_approval_waits(self):
        client = FakeTelegramClient()
        manager = object.__new__(ConfirmationManager)
        results = []
        executed = []
        next_done = threading.Event()

        def runner(text, stream_callback=None):
            executed.append(text)
            if text == "delete":
                results.append(manager.request_confirmation("delete", SafetyReport(DangerLevel.CAUTION)))
            else:
                next_done.set()
            return "done"

        bridge = TelegramBridge(client, runner, allowed_chat_ids=["123"],
                                queue=AgentTaskQueue(max_workers=1), remote_approval_enabled=True)
        self.addCleanup(bridge.stop)
        polls = []

        def poll(**kwargs):
            polls.append(kwargs)
            if len(polls) == 1:
                return [{"update_id": 1, "message": {"chat": {"id": "123"}, "text": "delete"}}]
            if len(polls) == 2:
                self.assertTrue(client.approval_sent.wait(2))
                return [
                    {"update_id": 2, "message": {"chat": {"id": "123"}, "text": "next"}},
                    {"update_id": 3, "callback_query": self._callback(client)},
                ]
            finished = next_done.wait(2)
            bridge._stop_event.set()
            self.assertTrue(finished)
            return []

        with patch.object(client, "get_updates", side_effect=poll, create=True):
            bridge.run_forever()
        self.assertEqual(results, [True])
        self.assertEqual(executed, ["delete", "next"])
        self.assertEqual(polls[-1]["offset"], 4)

    def test_polling_failure_denies_waiting_approval(self):
        bridge, client, worker, results = self._start_approval(remote_approval_enabled=True)
        self.assertTrue(client.approval_sent.wait(2))
        with patch.object(client, "get_updates", side_effect=RuntimeError("offline"), create=True), \
                patch("services.telegram_bridge.time.sleep", side_effect=lambda seconds: bridge._stop_event.set()):
            bridge.run_forever()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [False])

    def test_stop_denies_waiting_approval(self):
        bridge, client, worker, results = self._start_approval(remote_approval_enabled=True)
        self.assertTrue(client.approval_sent.wait(2))
        bridge.stop()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [False])

    def test_new_confirmation_uses_fresh_nonce(self):
        bridge, client, worker, results = self._start_approval(remote_approval_enabled=True)
        self.assertTrue(client.approval_sent.wait(2))
        previous = self._callback(client)
        bridge._handle_callback_query(previous)
        worker.join(2)
        client.approval_sent.clear()
        worker = threading.Thread(target=bridge._run_message, args=(
            IncomingMessage(chat_id="123", text="delete again"), threading.Event()))
        worker.start()
        self.addCleanup(worker.join, 2)
        self.assertTrue(client.approval_sent.wait(2))
        current = self._callback(client)
        self.assertNotEqual(previous["data"], current["data"])
        self.assertLessEqual(len(current["data"].encode("utf-8")), 64)
        bridge._handle_callback_query(previous)
        self.assertEqual(results, [True])
        bridge._handle_callback_query(current)
        worker.join(2)
        self.assertEqual(results, [True, True])

    def test_api_client_sends_approval_and_callback_payloads(self):
        posts = []
        gets = []

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"ok": True, "result": {"message_id": 8}}

        class Session:
            def post(self, url, json=None, timeout=None):
                posts.append((url.rsplit("/", 1)[-1], json))
                return Response()

            def get(self, url, params=None, timeout=None):
                gets.append(params)
                response = Response()
                response.json = lambda: {"ok": True, "result": []}
                return response

        client = TelegramApiClient("token", session=Session())
        markup = {"inline_keyboard": [[{"text": "approve", "callback_data": "nonce:approve"}]]}
        self.assertEqual(client.send_message("123", "confirm", reply_markup=markup), 8)
        client.answer_callback_query("callback-1")
        client.edit_message("123", 8, "approved", reply_markup={"inline_keyboard": []})
        client.get_updates()
        self.assertEqual(posts, [
            ("sendMessage", {"chat_id": "123", "text": "confirm", "reply_markup": markup}),
            ("answerCallbackQuery", {"callback_query_id": "callback-1"}),
            ("editMessageText", {"chat_id": "123", "message_id": 8, "text": "approved",
                                 "reply_markup": {"inline_keyboard": []}}),
        ])
        self.assertEqual(json.loads(gets[0]["allowed_updates"]), ["message", "callback_query"])

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

    def test_polling_error_log_does_not_contain_bot_token(self):
        class _FailingSession:
            def get(self, url, params=None, timeout=None):
                raise RuntimeError(f"Max retries exceeded with url: {url}")

        client = TelegramApiClient("123456:SECRET-TOKEN", session=_FailingSession())
        bridge = TelegramBridge(
            client,
            lambda text, stream_callback=None: "unused",
            allowed_chat_ids=["123"],
            queue=ImmediateQueue(),
        )

        with patch("services.telegram_bridge.time.sleep", side_effect=lambda _seconds: bridge._stop_event.set()):
            with self.assertLogs("services.telegram_bridge", level="WARNING") as logs:
                bridge.run_forever()

        self.assertTrue(any("polling failed" in line for line in logs.output))
        self.assertFalse(any("SECRET-TOKEN" in line for line in logs.output))

    def test_queued_task_error_does_not_carry_bot_token(self):
        class _FailingSession:
            def post(self, url, **kwargs):
                raise RuntimeError(f"Max retries exceeded with url: {url}")

        client = TelegramApiClient("123456:SECRET-TOKEN", session=_FailingSession())
        bridge = TelegramBridge(
            client,
            lambda text, stream_callback=None: "unused",
            allowed_chat_ids=["123"],
            queue=ImmediateQueue(),
        )

        with self.assertRaises(RuntimeError) as raised:
            bridge.handle_message(IncomingMessage(chat_id="123", text="hi", message_id=3))

        self.assertNotIn("SECRET-TOKEN", "".join(traceback.format_exception(raised.exception)))


if __name__ == "__main__":
    unittest.main()

import json
import os
import threading
import traceback
import unittest
from unittest.mock import patch

from agent.confirmation_manager import ConfirmationManager
from agent.safety_checker import DangerLevel, SafetyReport
from agent.task_queue import AgentTaskQueue

from audio.mp3_decoder import AudioTooLongError
from services.messaging_bridge_base import ChatAuthorizer, IncomingMessage, StreamingTextBuffer
from services.telegram_bridge import TelegramApiClient, TelegramBridge, TelegramFileTooLarge


class FakeTelegramClient:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.photos = []
        self.markups = []
        self.answered = []
        self.approval_sent = threading.Event()
        self.downloads = []
        self.download_data = b"media-bytes"

    def download_file(self, file_id, max_bytes=0):
        self.downloads.append(file_id)
        return self.download_data

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
        bot_credential = "123:abc"
        settings = {"telegram_enabled": True, "telegram_bot_token": bot_credential,
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

    def _media_bridge(self, runner=None, **options):
        client = FakeTelegramClient()
        options = {"voice_enabled": True, "photo_enabled": True, **options}
        bridge = TelegramBridge(client, runner or (lambda text, stream_callback=None: "done"),
                                allowed_chat_ids=["123"], queue=ImmediateQueue(), **options)
        return bridge, client

    def _voice(self, chat_id="123", **media):
        media = {"kind": "voice", "file_id": "voice-1", "file_size": 1000, "duration": 3, **media}
        return IncomingMessage(chat_id=chat_id, text="", message_id=5, media=media)

    def _photo(self, chat_id="123", text="", **media):
        media = {"kind": "photo", "file_id": "photo-1", "file_size": 1000, **media}
        return IncomingMessage(chat_id=chat_id, text=text, message_id=6, media=media)

    def _settings(self, **values):
        return patch("services.telegram_bridge.ConfigManager.get",
                     side_effect=lambda key, default=None: values.get(key, default))

    def test_voice_and_photo_are_ignored_when_settings_are_off(self):
        client = FakeTelegramClient()
        bridge = TelegramBridge(client, lambda text, stream_callback=None: "unused",
                                allowed_chat_ids=["123"], queue=ImmediateQueue())
        chat = {"id": "123"}
        voice = {"update_id": 1, "message": {"chat": chat, "voice": {"file_id": "v", "duration": 2}}}
        photo = {"update_id": 2, "message": {"chat": chat, "photo": [{"file_id": "p", "width": 1, "height": 1}]}}

        self.assertIsNone(bridge._parse_update(voice))
        self.assertIsNone(bridge._parse_update(photo))
        self.assertEqual(client.downloads, [])
        self.assertEqual(client.sent, [])

    def test_parse_update_picks_largest_photo_and_caption(self):
        bridge, _client = self._media_bridge()
        photos = [{"file_id": "small", "width": 90, "height": 90}, {"file_id": "big", "width": 800, "height": 600}]

        incoming = bridge._parse_update({"message": {"chat": {"id": "123"}, "photo": photos, "caption": "무엇인가요?"}})

        self.assertEqual(incoming.media["file_id"], "big")
        self.assertEqual(incoming.text, "무엇인가요?")

    def test_media_from_unauthorized_chat_is_not_downloaded(self):
        bridge, client = self._media_bridge()

        self.assertIsNone(bridge.handle_message(self._voice(chat_id="999")))
        self.assertIsNone(bridge.handle_message(self._photo(chat_id="999")))
        self.assertEqual(client.downloads, [])
        self.assertEqual(client.sent, [])

    def test_voice_requires_local_whisper(self):
        bridge, client = self._media_bridge()

        with self._settings(stt_provider="google"):
            bridge.handle_message(self._voice())

        self.assertEqual(client.downloads, [])
        self.assertIn("로컬 Whisper", client.sent[0][1])

    def test_voice_over_limit_is_not_downloaded(self):
        for media in ({"duration": 121}, {"file_size": 10 * 1024 * 1024 + 1}):
            with self.subTest(media=media):
                bridge, client = self._media_bridge()
                with self._settings(stt_provider="whisper"):
                    bridge.handle_message(self._voice(**media))
                self.assertEqual(client.downloads, [])
                self.assertEqual(len(client.sent), 1)

    def test_voice_text_goes_through_the_normal_command_path(self):
        ran = []
        heard = []

        class FakeStt:
            def transcribe(self, audio, mode=None):
                heard.append((audio.get_wav_data()[:4], mode))
                return " 볼륨 올려줘 "

        bridge, client = self._media_bridge(lambda text, stream_callback=None: ran.append(text) or "done",
                                            stt_factory=FakeStt)
        with self._settings(stt_provider="whisper"), \
                patch("audio.mp3_decoder.decode_ogg_to_pcm", return_value=b"\x00\x01" * 800) as decode:
            bridge.handle_message(self._voice())

        decode.assert_called_once_with(client.download_data, 16000, 120 * 16000)
        self.assertEqual(heard, [(b"RIFF", "command")])
        self.assertEqual(ran, ["볼륨 올려줘"])
        self.assertEqual(client.downloads, ["voice-1"])
        self.assertEqual(client.sent[0][1], "들은 내용: 볼륨 올려줘")
        self.assertEqual(client.sent[1][1], "Processing...")

    def test_voice_with_empty_recognition_does_not_run_a_command(self):
        ran = []

        class FakeStt:
            def transcribe(self, audio, mode=None):
                return None

        bridge, client = self._media_bridge(lambda text, stream_callback=None: ran.append(text) or "done",
                                            stt_factory=FakeStt)
        with self._settings(stt_provider="whisper"), \
                patch("audio.mp3_decoder.decode_ogg_to_pcm", return_value=b"\x00\x01" * 800):
            bridge.handle_message(self._voice())

        self.assertEqual(ran, [])
        self.assertEqual(client.sent[-1][1], "음성을 알아듣지 못했어요.")

    def test_voice_decoded_longer_than_limit_is_dropped(self):
        ran = []
        bridge, client = self._media_bridge(lambda text, stream_callback=None: ran.append(text) or "done",
                                            stt_factory=lambda: self.fail("stt must not run"))
        with self._settings(stt_provider="whisper"), \
                patch("audio.mp3_decoder.decode_ogg_to_pcm", side_effect=AudioTooLongError("long")) as decode:
            bridge.handle_message(self._voice(duration=None))

        self.assertEqual(decode.call_args.args, (client.download_data, 16000, 120 * 16000))
        self.assertEqual(ran, [])
        self.assertEqual(len(client.sent), 1)

    def test_photo_cancelled_skips_analysis_and_reply(self):
        for cancel_at in ("before_analysis", "after_analysis"):
            with self.subTest(cancel_at=cancel_at):
                cancel = threading.Event()
                calls = []

                def analyze(path, question):
                    calls.append(path)
                    if cancel_at == "after_analysis":
                        cancel.set()
                    return "result"

                bridge, client = self._media_bridge(image_analyzer=analyze)
                if cancel_at == "before_analysis":
                    client.download_file = lambda file_id, max_bytes=0: cancel.set() or b"data"

                self.assertEqual(bridge._run_media(self._photo(), cancel), "cancelled")
                self.assertEqual(len(calls), 0 if cancel_at == "before_analysis" else 1)
                self.assertEqual(client.sent, [])
                self.assertFalse(os.path.exists(os.path.dirname(calls[0])) if calls else False)

    def test_stop_releases_stt_provider(self):
        released = []

        class FakeStt:
            def __del__(self):
                released.append(True)

        bridge, _client = self._media_bridge()
        bridge._stt = FakeStt()
        bridge.stop()

        self.assertEqual(released, [True])
        self.assertIsNone(bridge._stt)

    def test_long_photo_analysis_is_split_into_telegram_sized_messages(self):
        long_text = "나" * 9000
        bridge, client = self._media_bridge(image_analyzer=lambda path, question: long_text)

        bridge.handle_message(self._photo())

        self.assertEqual("".join(body for _chat, body, _reply in client.sent), long_text)
        self.assertTrue(all(len(body) <= 4096 for _chat, body, _reply in client.sent))
        self.assertEqual([reply for _chat, _body, reply in client.sent], [6, None, None])

    def test_photo_is_analyzed_and_temp_file_removed(self):
        calls = []

        def analyze(path, question):
            with open(path, "rb") as image_file:
                calls.append((path, question, image_file.read()))
            return "고양이 사진입니다."

        bridge, client = self._media_bridge(image_analyzer=analyze)
        bridge.handle_message(self._photo(text="이게 뭐야?"))

        path, question, data = calls[0]
        self.assertEqual((question, data), ("이게 뭐야?", client.download_data))
        self.assertFalse(os.path.exists(path))
        self.assertFalse(os.path.exists(os.path.dirname(path)))
        self.assertEqual(client.sent[-1][1], "고양이 사진입니다.")

    def test_photo_temp_file_removed_when_analysis_fails(self):
        paths = []

        def analyze(path, question):
            paths.append(path)
            raise RuntimeError("analysis failed")

        bridge, client = self._media_bridge(image_analyzer=analyze)
        with self.assertRaises(RuntimeError):
            bridge.handle_message(self._photo())

        self.assertFalse(os.path.exists(os.path.dirname(paths[0])))
        self.assertIn("analysis failed", client.sent[-1][1])

    def test_photo_empty_result_and_oversize_are_reported_without_download(self):
        bridge, client = self._media_bridge(image_analyzer=lambda path, question: "  ")
        bridge.handle_message(self._photo())
        self.assertEqual(client.sent[-1][1], "사진을 분석하지 못했어요.")

        bridge, client = self._media_bridge(image_analyzer=lambda path, question: self.fail("too large"))
        bridge.handle_message(self._photo(file_size=10 * 1024 * 1024 + 1))
        self.assertEqual(client.downloads, [])

    def test_download_file_uses_fixed_host_without_redirects_and_limits_size(self):
        requests_made = []

        class Response:
            status_code = 200

            def __init__(self, payload=None, chunks=()):
                self.payload, self.chunks, self.closed = payload, chunks, False

            def raise_for_status(self):
                pass

            def json(self):
                return self.payload

            def iter_content(self, chunk_size=0):
                return iter(self.chunks)

            def close(self):
                self.closed = True

        file_response = Response(chunks=[b"ab", b"cd"])

        class Session:
            file_path = "voice/file_1.oga"

            def get(self, url, params=None, timeout=None, **kwargs):
                requests_made.append((url, kwargs))
                if url.endswith("/getFile"):
                    return Response({"ok": True, "result": {"file_path": self.file_path}})
                return file_response

        session = Session()
        client = TelegramApiClient("123456:SECRET-TOKEN", session=session)

        self.assertEqual(client.download_file("f1", max_bytes=10), b"abcd")
        self.assertEqual(requests_made[1][0], "https://api.telegram.org/file/bot123456:SECRET-TOKEN/voice/file_1.oga")
        self.assertIs(requests_made[1][1]["allow_redirects"], False)
        self.assertTrue(file_response.closed)
        with self.assertRaises(TelegramFileTooLarge):
            client.download_file("f1", max_bytes=3)
        for bad_path in ("../etc/passwd", "https://evil.example/x", "/abs/path", ""):
            session.file_path = bad_path
            with self.assertRaises(RuntimeError):
                client.download_file("f1")

    def test_download_error_does_not_leak_bot_token(self):
        class _FailingSession:
            def get(self, url, **kwargs):
                if url.endswith("/getFile"):
                    class Info:
                        def raise_for_status(self):
                            pass

                        def json(self):
                            return {"ok": True, "result": {"file_path": "photos/file_1.jpg"}}
                    return Info()
                raise RuntimeError(f"Max retries exceeded with url: {url}")

        client = TelegramApiClient("123456:SECRET-TOKEN", session=_FailingSession())
        bridge = TelegramBridge(client, lambda text, stream_callback=None: "unused", allowed_chat_ids=["123"],
                                queue=ImmediateQueue(), photo_enabled=True, image_analyzer=lambda path, question: "x")
        sent = []
        client.send_message = lambda chat_id, text, **kwargs: sent.append(text)

        with self.assertLogs("services.telegram_bridge", level="ERROR") as logs, \
                self.assertRaises(RuntimeError) as raised:
            bridge.handle_message(self._photo())

        everything = "".join(sent) + "".join(logs.output) + "".join(traceback.format_exception(raised.exception))
        self.assertNotIn("SECRET-TOKEN", everything)
        self.assertIn("/file/bot***/photos/file_1.jpg", everything)

    def test_from_settings_reads_voice_and_photo_flags(self):
        for flags, expected in (({}, (False, False)),
                                ({"telegram_voice_enabled": True, "telegram_photo_enabled": "yes"}, (True, False))):
            with self.subTest(flags=flags):
                bot_credential = "123:abc"
                values = {"telegram_enabled": True, "telegram_bot_token": bot_credential,
                          "telegram_allowed_chat_ids": ["123"], **flags}
                with self._settings(**values), \
                        patch("services.telegram_bridge.TelegramApiClient", return_value=FakeTelegramClient()):
                    bridge = TelegramBridge.from_settings(lambda text, stream=None: "done")
                self.addCleanup(bridge.stop)
                self.assertEqual((bridge.voice_enabled, bridge.photo_enabled), expected)


if __name__ == "__main__":
    unittest.main()

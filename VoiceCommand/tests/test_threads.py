import unittest
import threading
import sys
from contextlib import nullcontext
from queue import Empty
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from core.threads import (
    CommandExecutionThread,
    TTSThread,
    VoiceRecognitionThread,
    _wait_for_tts_playback_completion,
)
from core.core_manager import start_file_watcher


class TTSThreadTests(unittest.TestCase):
    def test_collect_batch_merges_immediately_queued_messages(self):
        thread = TTSThread()
        thread.queue.put("둘째 문장입니다.")
        thread.queue.put("셋째 문장입니다.")

        combined, task_count, stop_requested = thread._collect_batch("첫째 문장입니다.")

        self.assertEqual(
            combined,
            "첫째 문장입니다. 둘째 문장입니다. 셋째 문장입니다.",
        )
        self.assertEqual(task_count, 3)
        self.assertFalse(stop_requested)

    def test_collect_batch_preserves_stop_signal(self):
        thread = TTSThread()
        thread.queue.put(None)

        combined, task_count, stop_requested = thread._collect_batch("안내 멘트입니다.")

        self.assertEqual(combined, "안내 멘트입니다.")
        self.assertEqual(task_count, 2)
        self.assertTrue(stop_requested)

    def test_stop_interrupts_provider_discards_pending_text_and_rejects_new_text(self):
        provider = MagicMock()
        thread = TTSThread()
        thread.queue.put_nowait("pending speech")
        voice_command_module = ModuleType("VoiceCommand")
        voice_command_module._state = SimpleNamespace(fish_tts=provider)

        with patch.dict(
            sys.modules, {"VoiceCommand": voice_command_module}
        ):
            thread.stop()

            provider.stop.assert_called_once_with()
            self.assertIsNone(thread.queue.get_nowait())
            thread.queue.task_done()
            with self.assertRaises(Empty):
                thread.queue.get_nowait()
            self.assertFalse(thread.speak("late speech"))

    def test_wait_for_tts_playback_completion_uses_backoff(self):
        checks = iter([True, True, True, False])
        slept = []
        now_values = iter([0.0, 0.01, 0.08, 0.2])

        completed = _wait_for_tts_playback_completion(
            is_tts_playing=lambda: next(checks),
            sleep_fn=lambda seconds: slept.append(round(seconds, 3)),
            now_fn=lambda: next(now_values),
        )

        self.assertTrue(completed)
        self.assertEqual(slept, [0.05, 0.075, 0.113])

    def test_wait_for_tts_playback_completion_times_out(self):
        with patch("core.threads.logging.warning") as mocked_warning:
            completed = _wait_for_tts_playback_completion(
                is_tts_playing=lambda: True,
                timeout=0.1,
                sleep_fn=lambda _seconds: None,
                now_fn=iter([0.0, 0.05, 0.11]).__next__,
            )

        self.assertFalse(completed)
        mocked_warning.assert_called_once()

    def test_command_execution_thread_marks_failed_command_done(self):
        thread = CommandExecutionThread()
        thread.queue = MagicMock()
        thread.queue.get.side_effect = ["boom", None]

        with patch("VoiceCommand.execute_command", side_effect=RuntimeError("fail")):
            thread.run()

        self.assertEqual(thread.queue.task_done.call_count, 2)


class VoiceRecognitionThreadTests(unittest.TestCase):
    def test_duplicate_notice_is_shown_after_listening_cleanup(self):
        with patch("VoiceCommand.SharedMicrophone", return_value=MagicMock()):
            thread = VoiceRecognitionThread()
        thread._microphone_source = lambda: nullcontext(object())
        thread.speech_recognizer = object()
        thread._stt = object()
        events = []

        with (
            patch("VoiceCommand.tts_wrapper"),
            patch("VoiceCommand.recognize_speech_helper", return_value="repeat notice"),
            patch("VoiceCommand.wake_detector_recalibrate_helper"),
            patch("VoiceCommand.set_listening_indicator", side_effect=lambda active: (
                events.append(("listening", active))
            )),
            patch("VoiceCommand._show_tts_bubble", side_effect=lambda text, duration=0: (
                events.append(("bubble", text, duration))
            )),
            patch("core.threads._wait_for_tts_playback_completion"),
            patch("core.threads.time.sleep"),
        ):
            thread.handle_wake_word()

        self.assertEqual(
            events,
            [
                ("listening", True),
                ("listening", False),
                ("bubble", "repeat notice", 2000),
            ],
        )

    def test_missing_microphone_waits_without_polling_and_stops(self):
        waiting = threading.Event()
        original_wait = threading.Event.wait

        def wait_for_microphone(event, timeout=None):
            waiting.set()
            return original_wait(event, timeout)

        with (
            patch("VoiceCommand.SharedMicrophone", side_effect=OSError("no input device")),
            patch("core.threads.time.sleep", side_effect=AssertionError("unexpected polling")),
            patch("core.threads.create_stt_provider") as create_provider,
        ):
            thread = VoiceRecognitionThread()
            self.addCleanup(thread.stop)
            thread._microphone_wakeup.wait = lambda timeout=None: wait_for_microphone(
                thread._microphone_wakeup, timeout
            )
            thread.start()

            self.assertTrue(waiting.wait(1))
            self.assertIs(thread.microphone_available, False)
            self.assertTrue(thread.isRunning())
            self.assertTrue(thread.claim_microphone_unavailable_notification())
            self.assertFalse(thread.claim_microphone_unavailable_notification())
            create_provider.assert_not_called()

            thread.stop()
            self.assertTrue(thread.wait(1000))

    def test_setting_microphone_recovers_on_voice_thread(self):
        microphone_ready = threading.Event()
        creation_threads = []

        class FakeMicrophone:
            def __init__(self):
                self.stream = None

            def __enter__(self):
                self.stream = object()
                return self

            def __exit__(self, *_args):
                self.stream = None

        def create_microphone(device_index=None):
            creation_threads.append(threading.current_thread().name)
            if len(creation_threads) == 1:
                raise OSError("no default input device")
            return FakeMicrophone()

        detector = MagicMock()
        detector.should_stop = False
        detector.listen_for_wake_word.side_effect = lambda *_args, **_kwargs: (
            microphone_ready.set() or False
        )

        with (
            patch("VoiceCommand.SharedMicrophone", side_effect=create_microphone),
            patch("VoiceCommand.get_microphone_index_helper", return_value=4),
            patch("VoiceCommand.should_pause_wake_detection", return_value=False),
        ):
            thread = VoiceRecognitionThread()
            self.addCleanup(thread.stop)
            thread._initialize_voice_recognition = lambda: (
                setattr(thread, "wake_detector", detector) or True
            )
            thread._apply_recognizer_settings = lambda: None
            thread._refresh_stt_provider = lambda: None
            thread.start()

            thread.set_microphone("USB Microphone")
            self.assertTrue(microphone_ready.wait(2))
            self.assertIs(thread.microphone_available, True)
            self.assertEqual(thread.selected_microphone, "USB Microphone")
            self.assertEqual(thread.microphone_index, 4)
            self.assertNotEqual(creation_threads[1], threading.current_thread().name)

            thread.stop()
            self.assertTrue(thread.wait(1000))

    def test_same_microphone_can_retry_failed_voice_setup(self):
        with patch("VoiceCommand.SharedMicrophone", return_value=MagicMock()):
            thread = VoiceRecognitionThread()

        thread.selected_microphone = "USB Microphone"
        thread._microphone_active = True
        thread._voice_setup_failed = True

        thread.set_microphone("USB Microphone")

        self.assertTrue(thread._microphone_request_pending)
        self.assertTrue(thread._microphone_wakeup.is_set())


class FileWatcherTests(unittest.TestCase):
    def test_observer_failure_does_not_escape_startup(self):
        observer = MagicMock()
        observer.is_alive.return_value = False
        observer.schedule.side_effect = OSError("watch access denied")
        with (
            patch("core.core_manager.is_bundled", return_value=False),
            patch("core.core_manager.Observer", return_value=observer),
        ):
            self.assertIsNone(start_file_watcher())

        observer.stop.assert_called_once()
        observer.join.assert_not_called()


if __name__ == "__main__":
    unittest.main()

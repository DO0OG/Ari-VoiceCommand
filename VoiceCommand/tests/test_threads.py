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
    def _run_tts_results(self, results, queue_empty_results=None):
        thread = TTSThread()
        for index in range(len(results)):
            thread.queue.put(f"speech {index}")
        thread.queue.put(None)
        thread._collect_batch = MagicMock(
            side_effect=lambda text, _stop_event: (text, 1, False)
        )
        thread.queue.empty = MagicMock(
            side_effect=queue_empty_results or [True] * len(results)
        )
        voice_command = ModuleType("VoiceCommand")
        voice_command.text_to_speech = MagicMock(side_effect=results)
        voice_command._handle_tts_playback_finished = MagicMock()
        voice_command._show_tts_bubble = MagicMock()

        with (
            patch.dict(sys.modules, {"VoiceCommand": voice_command}),
            patch("core.threads._", return_value="TTS failed"),
        ):
            thread.run()

        return voice_command

    def test_cancelled_tts_does_not_show_failure_notice(self):
        def cancel_speech(_text, stop_event=None):
            stop_event.set()
            return False

        voice_command = self._run_tts_results(
            [False, cancel_speech], queue_empty_results=[False, True]
        )

        voice_command._show_tts_bubble.assert_not_called()

    def test_consecutive_tts_failures_show_failure_notice_once(self):
        voice_command = self._run_tts_results([False, False])

        voice_command._show_tts_bubble.assert_called_once_with(
            "TTS failed", duration=3000
        )

    def test_tts_success_resets_failure_notice_for_next_failure(self):
        voice_command = self._run_tts_results([False, False, True, False])

        self.assertEqual(voice_command._show_tts_bubble.call_count, 2)
        voice_command._show_tts_bubble.assert_called_with(
            "TTS failed", duration=3000
        )

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

    def test_clear_discards_queued_speech_and_cancels_active_batch(self):
        thread = TTSThread()
        thread.queue.put_nowait("첫 문장")
        thread.queue.put_nowait("둘째 문장")
        stop_event = threading.Event()
        thread._active_stop_event = stop_event

        self.assertEqual(thread.clear(), 2)

        self.assertTrue(stop_event.is_set())
        self.assertTrue(thread.queue.empty())
        self.assertEqual(thread.queue.unfinished_tasks, 0)

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

    def test_wait_for_tts_playback_completion_uses_event(self):
        event = threading.Event()
        event.set()
        checks = iter([True, False])

        completed = _wait_for_tts_playback_completion(
            is_tts_playing=lambda: next(checks),
            playback_finished=event,
        )

        self.assertTrue(completed)
        self.assertFalse(event.is_set())

    def test_wait_for_tts_playback_completion_times_out(self):
        event = SimpleNamespace(wait=MagicMock(return_value=False), clear=MagicMock())
        with patch("core.threads.logging.warning") as mocked_warning:
            completed = _wait_for_tts_playback_completion(
                is_tts_playing=lambda: True,
                playback_finished=event,
                timeout=0.1,
                now_fn=iter([0.0, 0.0, 0.11]).__next__,
            )

        self.assertFalse(completed)
        mocked_warning.assert_called_once()
        event.wait.assert_called_once_with(0.1)

    def test_command_execution_thread_marks_failed_command_done(self):
        thread = CommandExecutionThread()
        thread.queue = MagicMock()
        thread.queue.get.side_effect = ["boom", None]

        with patch("VoiceCommand.execute_command", side_effect=RuntimeError("fail")):
            thread.run()

        self.assertEqual(thread.queue.task_done.call_count, 2)


class VoiceRecognitionThreadTests(unittest.TestCase):
    def test_manual_activation_schedules_llm_prewarm(self):
        with patch("VoiceCommand.SharedMicrophone", return_value=MagicMock()):
            thread = VoiceRecognitionThread()
        thread.running = True
        thread.microphone = MagicMock()
        thread._microphone_active = True

        with patch.object(thread, "_prewarm_llm_connection") as prewarm:
            self.assertTrue(thread.request_listening())

        prewarm.assert_called_once_with()

    def test_recognizer_pause_threshold_caps_trailing_silence(self):
        with patch("VoiceCommand.SharedMicrophone", return_value=MagicMock()):
            thread = VoiceRecognitionThread()
        recognizer = SimpleNamespace(
            energy_threshold=0,
            dynamic_energy_threshold=False,
            pause_threshold=0.8,
            non_speaking_duration=0.5,
        )
        thread.speech_recognizer = recognizer
        settings = {
            "stt_energy_threshold": 300,
            "stt_dynamic_energy": True,
            "stt_pause_threshold": 0.3,
        }

        with patch(
            "core.threads.ConfigManager.get",
            side_effect=lambda key, default=None: settings.get(key, default),
        ):
            thread._apply_recognizer_settings()

        self.assertEqual(recognizer.pause_threshold, 0.3)
        self.assertEqual(recognizer.non_speaking_duration, 0.3)

    def test_activation_is_thread_safe_and_releases_push_to_talk(self):
        with patch("VoiceCommand.SharedMicrophone", return_value=MagicMock()):
            thread = VoiceRecognitionThread()

        self.assertTrue(thread.request_listening(push_to_talk=True))
        self.assertFalse(thread.request_listening())
        request = thread._take_voice_activation()
        self.assertIsNotNone(request)
        self.assertFalse(request["released"].is_set())

        self.assertFalse(thread.request_listening())
        thread.release_listening()
        self.assertTrue(request["released"].is_set())
        thread._finish_voice_activation()

    def test_wake_disabled_idle_loop_does_not_open_microphone_or_call_stt(self):
        settings = {"wake_word_enabled": False}
        with (
            patch("VoiceCommand.SharedMicrophone", return_value=MagicMock()),
            patch("core.threads.ConfigManager.load_settings", return_value=settings),
            patch("core.threads.create_stt_provider") as create_provider,
        ):
            thread = VoiceRecognitionThread()
            microphone_source = MagicMock()
            thread._microphone_source = microphone_source
            self.addCleanup(thread.stop)
            thread.start()

            self.assertTrue(thread.isRunning())
            threading.Event().wait(0.05)
            thread.stop()

        microphone_source.assert_not_called()
        create_provider.assert_not_called()

    def test_microphone_change_does_not_probe_while_wake_word_is_disabled(self):
        with (
            patch("VoiceCommand.SharedMicrophone", return_value=MagicMock()),
            patch("VoiceCommand.get_microphone_index_helper", return_value=2),
            patch("core.threads.ConfigManager.get", return_value=False),
        ):
            thread = VoiceRecognitionThread()
            thread._probe_microphone = MagicMock()
            thread.set_microphone("USB Microphone")
            thread._apply_pending_microphone()

        thread._probe_microphone.assert_not_called()
        self.assertFalse(thread._microphone_probed)

    def test_manual_activation_skips_wake_response_and_passes_ptt_release(self):
        with patch("VoiceCommand.SharedMicrophone", return_value=MagicMock()):
            thread = VoiceRecognitionThread()
        thread._initialize_voice_recognition = MagicMock(return_value=True)
        thread._apply_recognizer_settings = MagicMock()
        thread._refresh_stt_provider = MagicMock()
        thread._listen_for_command = MagicMock()

        with (
            patch("core.threads.ConfigManager.get", return_value=False),
            patch("VoiceCommand.is_tts_playing", return_value=False),
        ):
            self.assertTrue(thread.request_listening(push_to_talk=True))
            request = thread._take_voice_activation()
            thread._listen_for_manual_activation(request)

        thread._initialize_voice_recognition.assert_called_once_with(False)
        thread._listen_for_command.assert_called_once_with(request["released"])
        self.assertFalse(thread._command_listening)

    def test_manual_activation_applies_pending_microphone_before_capture(self):
        previous_microphone = MagicMock()
        selected_microphone = MagicMock()
        with patch(
            "VoiceCommand.SharedMicrophone",
            side_effect=[previous_microphone, selected_microphone],
        ):
            thread = VoiceRecognitionThread()
        thread.set_microphone("USB Microphone")
        thread._initialize_voice_recognition = MagicMock(return_value=True)
        thread._apply_recognizer_settings = MagicMock()
        thread._refresh_stt_provider = MagicMock()
        thread._listen_for_command = MagicMock(
            side_effect=lambda _released: self.assertIs(thread.microphone, selected_microphone)
        )

        with (
            patch("VoiceCommand.SharedMicrophone", return_value=selected_microphone),
            patch("VoiceCommand.get_microphone_index_helper", return_value=4),
            patch(
                "core.threads.ConfigManager.get",
                side_effect=lambda key, default=None: False if key == "wake_word_enabled" else default,
            ),
            patch("VoiceCommand.is_session_lock_blocked", return_value=False),
            patch("VoiceCommand.is_tts_playing", return_value=False),
        ):
            thread._listen_for_manual_activation({"released": None})

        thread._listen_for_command.assert_called_once_with(None)

    def test_voice_settings_change_retries_failed_initialization(self):
        initialization_failed = threading.Event()
        recovered_listening = threading.Event()
        detector = MagicMock()

        with (
            patch("VoiceCommand.SharedMicrophone", return_value=MagicMock()),
            patch("VoiceCommand.should_pause_wake_detection", return_value=False),
            patch("VoiceCommand.is_session_lock_blocked", return_value=False),
            patch("core.threads.ConfigManager.get", return_value=True),
        ):
            thread = VoiceRecognitionThread()
            self.addCleanup(thread.stop)
            thread._probe_microphone = MagicMock()
            thread._microphone_source = lambda: nullcontext(object())
            thread._apply_recognizer_settings = MagicMock()
            thread._refresh_stt_provider = MagicMock()
            attempts = []

            def initialize_voice_recognition(_initialize_wake_detector=True):
                attempts.append(True)
                if len(attempts) == 1:
                    thread._voice_setup_failed = True
                    initialization_failed.set()
                    return False
                thread._voice_setup_failed = False
                thread.wake_detector = detector
                return True

            def listen_for_wake_word(*_args, **_kwargs):
                recovered_listening.set()
                return False

            detector.listen_for_wake_word.side_effect = listen_for_wake_word
            thread._initialize_voice_recognition = initialize_voice_recognition
            thread.start()

            self.assertTrue(initialization_failed.wait(1))
            thread.refresh_voice_settings()
            self.assertTrue(recovered_listening.wait(1))
            thread.stop()
            self.assertTrue(thread.wait(1000))

        self.assertGreaterEqual(len(attempts), 2)

    def test_manual_activation_is_ignored_during_tts_playback(self):
        with patch("VoiceCommand.SharedMicrophone", return_value=MagicMock()):
            thread = VoiceRecognitionThread()
        thread._initialize_voice_recognition = MagicMock()
        thread._listen_for_command = MagicMock()

        with patch("VoiceCommand.is_tts_playing", return_value=True):
            self.assertTrue(thread.request_listening())
            request = thread._take_voice_activation()
            thread._listen_for_manual_activation(request)

        thread._initialize_voice_recognition.assert_not_called()
        thread._listen_for_command.assert_not_called()
        self.assertFalse(thread._command_listening)

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
            patch("core.threads.time.sleep") as sleep,
            patch("core.threads.ConfigManager.get", return_value=100),
        ):
            thread.handle_wake_word()

        sleep.assert_called_once_with(0.1)
        self.assertEqual(
            events,
            [
                ("listening", True),
                ("listening", False),
                ("bubble", "repeat notice", 2000),
            ],
        )

    def test_one_shot_wake_command_skips_response_and_second_listen(self):
        with patch("VoiceCommand.SharedMicrophone", return_value=MagicMock()):
            thread = VoiceRecognitionThread()
        thread._microphone_source = lambda: nullcontext(object())
        thread.wake_detector = MagicMock()
        thread._listen_for_command = MagicMock()
        received = []
        thread.result.connect(received.append)

        with (
            patch("VoiceCommand.is_session_lock_blocked", return_value=False),
            patch("VoiceCommand.tts_wrapper") as tts_wrapper,
            patch("VoiceCommand.wake_detector_recalibrate_helper"),
        ):
            thread.handle_wake_word("불 꺼줘")

        self.assertEqual(received, ["불 꺼줘"])
        tts_wrapper.assert_not_called()
        thread._listen_for_command.assert_not_called()

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

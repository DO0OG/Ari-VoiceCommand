import unittest
from unittest.mock import patch


from core import VoiceCommand


class _DummyQueue:
    def empty(self):
        return True


class _DummyTTS:
    is_playing = False


class _FakePlaybackTTS:
    def __init__(self):
        self.is_playing = False

    def speak(self, _text, emotion=None):
        del emotion
        self.is_playing = True
        return True


class VoiceCommandWakeGuardTests(unittest.TestCase):
    def setUp(self):
        self._old_thread = VoiceCommand._state.tts_thread
        self._old_tts = VoiceCommand._state.fish_tts
        self._old_guard = VoiceCommand._state.tts_resume_guard_until
        VoiceCommand._state.tts_thread = type("DummyThread", (), {"queue": _DummyQueue(), "is_processing": False})()
        VoiceCommand._state.fish_tts = _DummyTTS()
        VoiceCommand._state.tts_resume_guard_until = 0.0

    def tearDown(self):
        VoiceCommand._state.tts_thread = self._old_thread
        VoiceCommand._state.fish_tts = self._old_tts
        VoiceCommand._state.tts_resume_guard_until = self._old_guard

    def test_should_pause_wake_detection_during_guard_window(self):
        VoiceCommand._state.tts_resume_guard_until = 10.0
        self.assertTrue(VoiceCommand.should_pause_wake_detection(now=9.5))
        self.assertFalse(VoiceCommand.should_pause_wake_detection(now=10.5))

    def test_extend_tts_resume_guard_uses_duration_plus_buffer(self):
        old_monotonic = VoiceCommand.time.monotonic
        try:
            VoiceCommand.time.monotonic = lambda: 100.0
            VoiceCommand.extend_tts_resume_guard(3.0)
        finally:
            VoiceCommand.time.monotonic = old_monotonic

        self.assertEqual(VoiceCommand._state.tts_resume_guard_until, 103.5)

    def test_playback_finish_replaces_estimate_with_buffer(self):
        previous_tts = VoiceCommand._state.fish_tts
        previous_rp_gen = VoiceCommand._state.rp_gen
        previous_widget = VoiceCommand._state.character_widget
        previous_indicator = VoiceCommand._state.listening_indicator_active
        playback_finished = VoiceCommand._state.tts_playback_finished_event
        previous_playback_finished = playback_finished.is_set()
        VoiceCommand._state.fish_tts = _FakePlaybackTTS()
        VoiceCommand._state.rp_gen = None
        VoiceCommand._state.character_widget = None
        VoiceCommand._state.listening_indicator_active = False
        playback_finished.clear()
        monotonic_values = iter([100.0, 103.0])
        try:
            with (
                patch.object(
                    VoiceCommand,
                    "_estimate_tts_duration",
                    return_value=10.0,
                ),
                patch("core.VoiceCommand.time.monotonic", side_effect=monotonic_values),
                patch.object(VoiceCommand, "emit_plugin_event"),
            ):
                self.assertTrue(VoiceCommand.text_to_speech("응답", show_bubble=False))
                self.assertEqual(VoiceCommand._state.tts_resume_guard_until, 110.5)
                VoiceCommand._state.fish_tts.is_playing = False
                VoiceCommand._handle_tts_playback_finished()

            self.assertEqual(VoiceCommand._state.tts_resume_guard_until, 103.5)
            self.assertTrue(playback_finished.is_set())
            self.assertTrue(VoiceCommand.should_pause_wake_detection(now=103.49))
            self.assertFalse(VoiceCommand.should_pause_wake_detection(now=103.5))
        finally:
            VoiceCommand._state.fish_tts = previous_tts
            VoiceCommand._state.rp_gen = previous_rp_gen
            VoiceCommand._state.character_widget = previous_widget
            VoiceCommand._state.listening_indicator_active = previous_indicator
            if previous_playback_finished:
                playback_finished.set()
            else:
                playback_finished.clear()

    def test_tts_startup_failure_does_not_escape_or_leave_waiters_blocked(self):
        old_started = VoiceCommand._state.tts_init_started
        event = VoiceCommand._state.tts_init_event
        old_event_is_set = event.is_set()
        event.clear()
        VoiceCommand._state.tts_init_started = False
        try:
            with (
                patch(
                    "core.config_manager.ConfigManager.load_settings",
                    return_value={"tts_mode": "edge"},
                ),
                patch.object(
                    VoiceCommand,
                    "initialize_tts",
                    side_effect=TypeError("unexpected provider initialization error"),
                ),
            ):
                VoiceCommand.start_tts_background()
            initialized_event = event.is_set()
        finally:
            VoiceCommand._state.tts_init_started = old_started
            if old_event_is_set:
                event.set()
            else:
                event.clear()

        self.assertTrue(initialized_event)

    def test_tts_settings_load_failure_releases_waiters(self):
        old_started = VoiceCommand._state.tts_init_started
        event = VoiceCommand._state.tts_init_event
        old_event_is_set = event.is_set()
        event.clear()
        VoiceCommand._state.tts_init_started = False
        try:
            with patch(
                "core.config_manager.ConfigManager.load_settings",
                side_effect=PermissionError("settings are read-only"),
            ):
                VoiceCommand.start_tts_background()
            initialized_event = event.is_set()
        finally:
            VoiceCommand._state.tts_init_started = old_started
            if old_event_is_set:
                event.set()
            else:
                event.clear()

        self.assertTrue(initialized_event)

    def test_character_widget_startup_survives_orchestrator_storage_failure(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        previous_character = VoiceCommand._state.character_widget
        character = SimpleNamespace(thinking_signal=SimpleNamespace(emit=Mock()))
        try:
            with patch(
                "agent.agent_orchestrator.get_orchestrator",
                side_effect=PermissionError("runtime directory is read-only"),
            ):
                VoiceCommand.set_character_widget(character)

            self.assertIs(VoiceCommand._state.character_widget, character)
        finally:
            VoiceCommand._state.character_widget = previous_character


if __name__ == "__main__":
    unittest.main()

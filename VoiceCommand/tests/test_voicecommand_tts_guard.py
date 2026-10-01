import unittest
from unittest.mock import Mock, call, patch


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

    def test_cosyvoice_warmup_failure_uses_configured_fallback(self):
        from types import SimpleNamespace

        previous_provider = VoiceCommand._state.fish_tts
        previous_signature = VoiceCommand._state.tts_signature
        previous_generator = VoiceCommand._state.rp_gen
        previous_widget = VoiceCommand._state.character_widget
        VoiceCommand._state.fish_tts = None
        VoiceCommand._state.tts_signature = None
        VoiceCommand._state.character_widget = None
        provider = Mock()
        provider.wait_until_warmup_done.return_value = False
        provider._warmup_error = "GPU warmup failed"
        fallback_provider = object()
        settings = {"tts_mode": "local", "tts_fallback_provider": "openai_tts"}
        try:
            with (
                patch("core.config_manager.ConfigManager.load_settings", return_value=settings),
                patch("tts.tts_factory.build_tts_signature", return_value=("local",)),
                patch(
                    "tts.tts_factory.create_tts_provider",
                    side_effect=[(provider, "local"), (fallback_provider, "openai_tts")],
                ) as create_provider,
                patch.object(VoiceCommand, "RPGenerator", return_value=SimpleNamespace(set_config=Mock())),
            ):
                VoiceCommand.initialize_tts()

            self.assertIs(VoiceCommand._state.fish_tts, fallback_provider)
            provider.cleanup.assert_called_once_with()
            self.assertEqual(
                create_provider.call_args_list,
                [call(), call({**settings, "tts_mode": "openai_tts"})],
            )
        finally:
            VoiceCommand._state.fish_tts = previous_provider
            VoiceCommand._state.tts_signature = previous_signature
            VoiceCommand._state.rp_gen = previous_generator
            VoiceCommand._state.character_widget = previous_widget

    def _run_initialize_tts(self, settings, providers):
        from types import SimpleNamespace

        saved = (
            VoiceCommand._state.fish_tts,
            VoiceCommand._state.tts_signature,
            VoiceCommand._state.rp_gen,
            VoiceCommand._state.character_widget,
        )
        VoiceCommand._state.fish_tts = None
        VoiceCommand._state.tts_signature = None
        VoiceCommand._state.character_widget = None
        self.addCleanup(self._restore_tts_state, saved)
        with (
            patch("core.config_manager.ConfigManager.load_settings", return_value=settings),
            patch("tts.tts_factory.build_tts_signature", return_value=("sig",)),
            patch("tts.tts_factory.create_tts_provider", side_effect=providers) as create_provider,
            patch.object(VoiceCommand, "RPGenerator", return_value=SimpleNamespace(set_config=Mock())),
        ):
            VoiceCommand.initialize_tts()
        return create_provider

    @staticmethod
    def _restore_tts_state(saved):
        (
            VoiceCommand._state.fish_tts,
            VoiceCommand._state.tts_signature,
            VoiceCommand._state.rp_gen,
            VoiceCommand._state.character_widget,
        ) = saved

    def test_local_provider_is_registered_before_warmup_finishes(self):
        provider = Mock()
        registered_during_warmup = []
        provider.wait_until_warmup_done.side_effect = lambda: (
            registered_during_warmup.append(
                VoiceCommand._state.fish_tts is provider
                and VoiceCommand._state.rp_gen is not None
            )
            or True
        )
        self.addCleanup(setattr, VoiceCommand._state, "rp_gen", VoiceCommand._state.rp_gen)
        VoiceCommand._state.rp_gen = None

        self._run_initialize_tts({"tts_mode": "local"}, [(provider, "local")])

        self.assertEqual(registered_during_warmup, [True])
        self.assertIs(VoiceCommand._state.fish_tts, provider)
        provider.cleanup.assert_not_called()

    def test_failed_warmup_keeps_provider_replaced_by_newer_initialization(self):
        provider = Mock()
        newer_provider = object()

        def replaced_during_warmup():
            VoiceCommand._state.fish_tts = newer_provider
            return False

        provider.wait_until_warmup_done.side_effect = replaced_during_warmup

        create_provider = self._run_initialize_tts(
            {"tts_mode": "local", "tts_fallback_provider": "edge"},
            [(provider, "local")],
        )

        self.assertIs(VoiceCommand._state.fish_tts, newer_provider)
        self.assertEqual(create_provider.call_count, 1)

    def test_fallback_same_as_primary_uses_edge(self):
        fallback_provider = object()
        settings = {"tts_mode": "openai_tts", "tts_fallback_provider": "openai_tts"}

        create_provider = self._run_initialize_tts(
            settings,
            [RuntimeError("no key"), (fallback_provider, "edge")],
        )

        self.assertIs(VoiceCommand._state.fish_tts, fallback_provider)
        self.assertEqual(create_provider.call_args_list[1], call({**settings, "tts_mode": "edge"}))

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

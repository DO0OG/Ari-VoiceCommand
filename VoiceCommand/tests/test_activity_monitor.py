import unittest
from unittest.mock import Mock, patch

from agent.llm_provider import LLMProvider
from core.activity_monitor import ActivityMonitor, get_activity_context
from core.settings_schema import DEFAULT_SETTINGS
from core.VoiceCommand import (
    is_session_lock_blocked,
    recognize_speech_helper,
    set_activity_quiet,
    set_session_locked,
    should_pause_wake_detection,
    text_to_speech,
    tts_wrapper,
)


class _FakeActivityApi:
    def __init__(self):
        self.idle_seconds = 0
        self.quiet_reason = "none"
        self.category = "other"
        self.window_rect = (0, 0, 1920, 1080)
        self.session_locked = False
        self.taskbar_hidden = False
        self.idle_calls = 0
        self.quiet_calls = 0

    def get_idle_seconds(self):
        self.idle_calls += 1
        return self.idle_seconds

    def get_quiet_reason(self):
        self.quiet_calls += 1
        return self.quiet_reason

    def get_foreground_app_category(self):
        return self.category

    def get_foreground_window_rect(self):
        return self.window_rect

    def get_session_locked(self):
        return self.session_locked

    def is_taskbar_hidden(self):
        return self.taskbar_hidden


class ActivityMonitorTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "activity_idle_reaction_enabled": True,
            "activity_quiet_reaction_enabled": True,
            "activity_away_threshold_minutes": 5,
            "activity_app_category_reaction_enabled": False,
        }
        self.api = _FakeActivityApi()
        self.now = [0.0]
        self.monitor = ActivityMonitor(
            api=self.api,
            settings_provider=lambda: self.settings,
            clock=lambda: self.now[0],
        )
        self.monitor.session_locked.connect(lambda: set_session_locked(True))
        self.monitor.session_unlocked.connect(lambda: set_session_locked(False))

    def tearDown(self):
        set_session_locked(False)
        set_activity_quiet(False)
        self.monitor.stop()

    def test_idle_events_fire_once_and_report_duration(self):
        away = Mock()
        returned = Mock()
        self.monitor.user_away.connect(away)
        self.monitor.user_returned.connect(returned)

        self.api.idle_seconds = 300
        self.monitor._check_idle()
        self.monitor._check_idle()
        away.assert_called_once_with(300)

        self.now[0] = 12
        self.api.idle_seconds = 0
        self.monitor._check_idle()
        returned.assert_called_once_with(312)

    def test_disabled_idle_and_quiet_reactions_do_not_poll(self):
        self.settings["activity_idle_reaction_enabled"] = False
        self.settings["activity_quiet_reaction_enabled"] = False
        away = Mock()
        quiet = Mock()
        self.monitor.user_away.connect(away)
        self.monitor.quiet_state_changed.connect(quiet)

        self.api.idle_seconds = 600
        self.api.quiet_reason = "presentation"
        self.monitor._check_idle()
        self.monitor._check_quiet()

        away.assert_not_called()
        quiet.assert_not_called()
        self.assertEqual(self.api.idle_calls, 0)
        self.assertEqual(self.api.quiet_calls, 0)

    def test_lock_events_are_edge_triggered(self):
        locked = Mock()
        unlocked = Mock()
        self.monitor.session_locked.connect(locked)
        self.monitor.session_unlocked.connect(unlocked)

        with patch("core.VoiceCommand.is_tts_playing", return_value=False):
            self.monitor.handle_session_change(0x7)
            self.monitor.handle_session_change(0x7)
            self.assertTrue(should_pause_wake_detection(now=10**9))
            self.monitor.handle_session_change(0x8)
            self.monitor.handle_session_change(0x8)
            self.assertFalse(should_pause_wake_detection(now=10**9))

        locked.assert_called_once_with()
        unlocked.assert_called_once_with()
        self.assertFalse(self.monitor.session_is_locked)

    def test_startup_lock_state_blocks_until_unlock(self):
        self.api.session_locked = True
        self.monitor._refresh_session_state()
        self.assertTrue(self.monitor.session_is_locked)
        self.assertTrue(is_session_lock_blocked())

        self.api.session_locked = False
        self.monitor.handle_session_change(0x8)
        self.assertFalse(is_session_lock_blocked())

    def test_unknown_startup_lock_state_fails_closed_until_query_succeeds(self):
        self.api.get_session_locked = Mock(return_value=None)
        self.monitor._refresh_session_state()
        self.assertTrue(is_session_lock_blocked())

        self.api.get_session_locked.return_value = False
        self.monitor._refresh_session_state()
        self.assertFalse(is_session_lock_blocked())

    def test_secure_desktop_return_to_default_unlocks_without_wts_event(self):
        self.monitor._lock_notifications_available = True
        self.api.session_locked = True
        self.monitor._refresh_session_state()
        self.assertTrue(is_session_lock_blocked())

        self.api.session_locked = False
        self.monitor._refresh_display_state()

        self.assertFalse(is_session_lock_blocked())

    def test_lock_state_is_polled_without_session_notifications(self):
        self.monitor._lock_notifications_available = False
        self.api.session_locked = True
        self.monitor._refresh_display_state()
        self.assertTrue(is_session_lock_blocked())

        self.api.session_locked = False
        self.monitor._refresh_display_state()
        self.assertFalse(is_session_lock_blocked())

    def test_lock_during_listen_discards_voice_command(self):
        recognizer = Mock()
        recognizer.listen.side_effect = lambda *_args, **_kwargs: (
            set_session_locked(True),
            object(),
        )[1]
        provider = Mock()
        signal = Mock()

        recognize_speech_helper(
            recognizer,
            object(),
            signal,
            stt_provider=provider,
            continue_check=lambda: not is_session_lock_blocked(),
        )

        provider.transcribe.assert_not_called()
        signal.emit.assert_not_called()

    def test_display_state_refresh_updates_fullscreen_and_taskbar_cache(self):
        self.api.window_rect = (0, 0, 1920, 1080)
        self.api.taskbar_hidden = True
        self.monitor._refresh_display_state()

        self.assertTrue(self.monitor.foreground_covers(1920, 1080))
        self.assertTrue(self.monitor.taskbar_hidden)

    def test_foreground_category_and_prompt_expose_only_category_and_elapsed(self):
        self.assertFalse(DEFAULT_SETTINGS["activity_app_category_reaction_enabled"])
        self.settings["activity_app_category_reaction_enabled"] = True
        self.api.category = "ide"
        changed = Mock()
        self.monitor.foreground_category_changed.connect(changed)

        self.monitor._on_foreground_event()
        self.now[0] = 42
        changed.assert_called_once_with("ide")
        self.assertEqual(
            get_activity_context(),
            "[activity] category=ide; elapsed_seconds=42",
        )
        self.assertNotIn("code.exe", get_activity_context())
        self.assertNotIn("window", get_activity_context())

        provider = LLMProvider()
        provider._get_skill_context = Mock(return_value={"prompt": ""})
        prompt = provider._build_system(include_context=True)
        activity_line = next(line for line in prompt.splitlines() if line.startswith("[activity]"))
        self.assertEqual(activity_line, "[activity] category=ide; elapsed_seconds=42")

    def test_ide_long_use_signal_requires_enabled_category_reaction(self):
        self.settings["activity_app_category_reaction_enabled"] = True
        due = Mock()
        self.monitor.ide_long_use_due.connect(due)
        self.api.category = "ide"
        self.monitor._on_foreground_event()
        self.now[0] = 3 * 60 * 60
        self.monitor._check_ide_long_use()
        due.assert_called_once_with(3 * 60 * 60)

        self.settings["activity_ide_long_use_reaction_enabled"] = False
        self.monitor._check_ide_long_use()
        due.assert_called_once()

    def test_quiet_bubble_only_mode_skips_audio_output(self):
        with (
            patch("core.config_manager.ConfigManager.get", return_value=True),
            patch("core.VoiceCommand._show_tts_bubble") as show_bubble,
            patch("core.VoiceCommand._state.character_widget", Mock()),
        ):
            set_activity_quiet(True)
            tts_wrapper("조용히 응답")
            self.assertTrue(text_to_speech("말풍선 응답"))

        self.assertEqual(show_bubble.call_count, 2)

    def test_fullscreen_geometry_uses_cached_window_rect(self):
        self.monitor._on_foreground_event()
        self.assertTrue(self.monitor.foreground_covers(1920, 1080))
        self.assertFalse(self.monitor.foreground_covers(2560, 1440))


if __name__ == "__main__":
    unittest.main()

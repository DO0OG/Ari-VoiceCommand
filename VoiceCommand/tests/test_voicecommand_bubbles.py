import unittest
from unittest.mock import patch


import core.VoiceCommand as voicecommand


class _FakeWidget:
    def __init__(self):
        self.say_calls = []
        self.hide_calls = 0

    def say(self, text, duration=5000):
        self.say_calls.append((text, duration))

    def hide_speech_bubble(self):
        self.hide_calls += 1


class _FakeSignal:
    def __init__(self):
        self.connected = []

    def connect(self, callback):
        self.connected.append(callback)

    def disconnect(self, callback):
        self.connected = [cb for cb in self.connected if cb != callback]


class _FakeFishProvider:
    def __init__(self, *args, **kwargs):
        del args, kwargs
        self.playback_finished = _FakeSignal()


class VoiceCommandBubbleTests(unittest.TestCase):
    def setUp(self):
        self.original_widget = voicecommand._state.character_widget
        self.original_provider = voicecommand._state.fish_tts
        self.original_game_mode = voicecommand._state.game_mode
        self.original_indicator = voicecommand._state.listening_indicator_active
        self.original_indicator_text = voicecommand._state.listening_indicator_text
        self.original_tts_resume_guard_until = voicecommand._state.tts_resume_guard_until
        self.original_tts_thread = voicecommand._state.tts_thread

        voicecommand._state.character_widget = _FakeWidget()
        voicecommand._state.fish_tts = None
        voicecommand._state.game_mode = False
        voicecommand._state.listening_indicator_active = False
        voicecommand._state.listening_indicator_text = "말씀해주세요"
        voicecommand._state.tts_resume_guard_until = 0.0
        voicecommand._state.tts_thread = None

    def tearDown(self):
        voicecommand._state.character_widget = self.original_widget
        voicecommand._state.fish_tts = self.original_provider
        voicecommand._state.game_mode = self.original_game_mode
        voicecommand._state.listening_indicator_active = self.original_indicator
        voicecommand._state.listening_indicator_text = self.original_indicator_text
        voicecommand._state.tts_resume_guard_until = self.original_tts_resume_guard_until
        voicecommand._state.tts_thread = self.original_tts_thread

    def test_set_listening_indicator_shows_prompt_bubble(self):
        voicecommand.set_listening_indicator(True)

        self.assertEqual(
            voicecommand._state.character_widget.say_calls[-1],
            ("말씀해주세요", 0),
        )

    def test_tts_finish_keeps_listening_bubble_visible_when_waiting_for_stt(self):
        voicecommand._state.listening_indicator_active = True

        with patch("core.VoiceCommand.is_tts_playing", return_value=False), patch(
            "core.VoiceCommand.time.monotonic", return_value=100.0
        ):
            voicecommand._handle_tts_playback_finished()

        self.assertEqual(
            voicecommand._state.character_widget.say_calls[-1],
            ("말씀해주세요", 0),
        )
        self.assertEqual(voicecommand._state.character_widget.hide_calls, 0)
        self.assertEqual(voicecommand._state.tts_resume_guard_until, 101.2)

    def test_should_pause_wake_detection_during_resume_guard(self):
        voicecommand._state.tts_resume_guard_until = 101.2

        self.assertTrue(voicecommand.should_pause_wake_detection(now=100.5))
        self.assertFalse(voicecommand.should_pause_wake_detection(now=101.2))

    def test_enable_game_mode_reconnects_playback_finished_signal(self):
        with patch("core.config_manager.ConfigManager.load_settings", return_value={}):
            with patch("tts.fish_tts_ws.FishTTSWebSocket", _FakeFishProvider):
                voicecommand.enable_game_mode()

        provider = voicecommand._state.fish_tts
        self.assertIsNotNone(provider)
        self.assertIn(voicecommand._handle_tts_playback_finished, provider.playback_finished.connected)

    def test_parse_emotion_text_supports_english_and_japanese_tags(self):
        emotion_en, pure_en = voicecommand.parse_emotion_text("[happy] hello")
        emotion_ja, pure_ja = voicecommand.parse_emotion_text("(心配) 大丈夫?")

        self.assertEqual(emotion_en, "기쁨")
        self.assertEqual(pure_en, "hello")
        self.assertEqual(emotion_ja, "걱정")
        self.assertEqual(pure_ja, "大丈夫?")


if __name__ == "__main__":
    unittest.main()

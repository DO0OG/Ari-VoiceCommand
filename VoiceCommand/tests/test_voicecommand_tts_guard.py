import unittest


from core import VoiceCommand


class _DummyQueue:
    def empty(self):
        return True


class _DummyTTS:
    is_playing = False


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


if __name__ == "__main__":
    unittest.main()

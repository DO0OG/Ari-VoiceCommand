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

    def test_extend_tts_resume_guard_uses_duration_plus_buffer(self):
        old_monotonic = VoiceCommand.time.monotonic
        try:
            VoiceCommand.time.monotonic = lambda: 100.0
            VoiceCommand.extend_tts_resume_guard(3.0)
        finally:
            VoiceCommand.time.monotonic = old_monotonic

        self.assertEqual(VoiceCommand._state.tts_resume_guard_until, 103.5)


if __name__ == "__main__":
    unittest.main()

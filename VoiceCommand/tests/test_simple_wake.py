import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from audio.simple_wake import SimpleWakeWord


class _FakeSttProvider:
    def is_healthy(self):
        return True


class SimpleWakeWordTests(unittest.TestCase):
    def _make_detector(self):
        settings = {
            "wake_words": ["아리야", "시작"],
            "stt_energy_threshold": 300,
            "stt_dynamic_energy": True,
            "stt_provider": "google",
            "whisper_model": "small",
            "whisper_device": "auto",
            "whisper_compute_type": "int8",
        }
        with patch("audio.simple_wake.ConfigManager.load_settings", return_value=settings):
            with patch("audio.simple_wake.create_stt_provider", return_value=_FakeSttProvider()):
                return SimpleWakeWord()

    def test_matches_exact_wake_word_even_with_punctuation(self):
        detector = self._make_detector()

        self.assertTrue(detector._matches_wake_word("아리야!", "아리야"))
        self.assertTrue(detector._matches_wake_word(" 시작... ", "시작"))

    def test_does_not_match_generic_word_inside_longer_sentence(self):
        detector = self._make_detector()

        self.assertFalse(
            detector._matches_wake_word("오늘도 평화롭게 시작하셨길 바랍니다", "시작")
        )


if __name__ == "__main__":
    unittest.main()

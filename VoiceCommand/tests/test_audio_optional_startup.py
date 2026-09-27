import unittest
from unittest.mock import patch

from audio import audio_manager


class OptionalAudioStartupTests(unittest.TestCase):
    def test_global_audio_initialization_failure_is_reported_without_raising(self):
        with patch.object(
            audio_manager.GlobalAudio,
            "get_instance",
            side_effect=OSError("no audio device available"),
        ):
            self.assertFalse(audio_manager.initialize_global_audio())

    def test_global_audio_initialization_reports_success(self):
        with patch.object(audio_manager.GlobalAudio, "get_instance", return_value=object()):
            self.assertTrue(audio_manager.initialize_global_audio())


if __name__ == "__main__":
    unittest.main()

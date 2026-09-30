import unittest
from unittest.mock import patch

from tts.voice_reference import get_reference_text, get_reference_wav


class VoiceReferenceTests(unittest.TestCase):
    def test_configured_reference_wav_overrides_existing_path_rules(self):
        path = r"C:\voices\reference.wav"

        self.assertEqual(get_reference_wav({"tts_reference_wav": path}), path)

    def test_empty_reference_uses_appdata_then_bundle_fallback(self):
        with (
            patch(
                "core.resource_manager.ResourceManager.get_writable_path",
                return_value=r"C:\appdata\reference.wav",
            ),
            patch(
                "core.resource_manager.ResourceManager.get_bundle_path",
                return_value=r"C:\bundle\reference.wav",
            ),
            patch("tts.voice_reference.os.path.exists", return_value=False),
        ):
            result = get_reference_wav({"tts_reference_wav": ""})

        self.assertEqual(result, r"C:\bundle\reference.wav")

    def test_reference_text_reuses_cosyvoice_setting(self):
        self.assertEqual(
            get_reference_text({"cosyvoice_reference_text": "reference transcript"}),
            "reference transcript",
        )


if __name__ == "__main__":
    unittest.main()

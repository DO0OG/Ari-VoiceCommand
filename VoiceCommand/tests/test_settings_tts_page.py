import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ui.settings_tts_page import _TTSSettingsPage


class TTSSettingsPageTests(unittest.TestCase):
    def test_clone_keeps_voice_selected_and_notifies_when_verification_is_required(self):
        page = SimpleNamespace(
            elevenlabs_key_input=Mock(),
            elevenlabs_clone_button=Mock(),
            elevenlabs_voice_combo=Mock(),
            get_values=Mock(return_value={}),
        )
        page.elevenlabs_key_input.text.return_value = "test-key"
        page.elevenlabs_voice_combo.count.return_value = 1
        page._start_elevenlabs_action = Mock(
            side_effect=lambda _button, _action, finish: finish(("voice-id", True), "")
        )

        with (
            patch("tts.voice_reference.get_reference_wav", return_value="reference.wav"),
            patch("ui.settings_tts_page.os.path.isfile", return_value=True),
            patch("ui.settings_tts_page.QMessageBox.information") as information,
        ):
            _TTSSettingsPage._create_elevenlabs_clone(page)

        page.elevenlabs_voice_combo.addItem.assert_called_once_with(
            "reference", "voice-id"
        )
        page.elevenlabs_voice_combo.setCurrentIndex.assert_called_once_with(0)
        information.assert_called_once()
        self.assertIn("추가 인증", information.call_args.args[2])


if __name__ == "__main__":
    unittest.main()

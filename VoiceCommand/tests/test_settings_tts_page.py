import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ui.settings_tts_page import _TTSSettingsPage


class TTSSettingsPageTests(unittest.TestCase):
    @staticmethod
    def _warning_page(mode, reference_wav):
        page = SimpleNamespace(
            _settings={},
            tts_mode_combo=Mock(),
            tts_reference_wav_input=Mock(),
            openai_compat_clone_combo=Mock(),
            _reference_wav_warning=Mock(),
        )
        page.tts_mode_combo.currentData.return_value = mode
        page.tts_reference_wav_input.text.return_value = reference_wav
        page.openai_compat_clone_combo.currentData.return_value = "none"
        return page

    def test_reference_warning_uses_default_path_when_setting_is_empty(self):
        page = self._warning_page("local", "")
        appdata_path = r"C:\Users\test\AppData\Ari\reference.wav"
        bundle_path = r"C:\Program Files\Ari\reference.wav"

        with (
            patch("core.resource_manager.ResourceManager.get_writable_path", return_value=appdata_path),
            patch("core.resource_manager.ResourceManager.get_bundle_path", return_value=bundle_path),
            patch("tts.voice_reference.os.path.exists", return_value=False),
            patch("ui.settings_tts_page.os.path.isfile", return_value=False) as isfile,
        ):
            _TTSSettingsPage._update_reference_wav_warning(page)

        page._reference_wav_warning.setVisible.assert_called_once_with(True)
        isfile.assert_called_once_with(bundle_path)

    def test_reference_warning_shows_for_missing_explicit_path(self):
        reference_wav = r"C:\Voices\missing.wav"
        page = self._warning_page("local", reference_wav)

        with patch("ui.settings_tts_page.os.path.isfile", return_value=False) as isfile:
            _TTSSettingsPage._update_reference_wav_warning(page)

        page._reference_wav_warning.setVisible.assert_called_once_with(True)
        isfile.assert_called_once_with(reference_wav)

    def test_reference_warning_hides_for_existing_path(self):
        reference_wav = r"C:\Voices\voice.wav"
        page = self._warning_page("local", reference_wav)

        with patch("ui.settings_tts_page.os.path.isfile", return_value=True):
            _TTSSettingsPage._update_reference_wav_warning(page)

        page._reference_wav_warning.setVisible.assert_called_once_with(False)

    def test_reference_warning_hides_for_other_engine(self):
        page = self._warning_page("openai_compat_tts", r"C:\Voices\missing.wav")

        with patch("ui.settings_tts_page.os.path.isfile") as isfile:
            _TTSSettingsPage._update_reference_wav_warning(page)

        page._reference_wav_warning.setVisible.assert_called_once_with(False)
        isfile.assert_not_called()

    def test_reference_warning_shows_for_openai_compat_reference_audio_mode(self):
        reference_wav = r"C:\Voices\missing.wav"
        page = self._warning_page("openai_compat_tts", reference_wav)
        page.openai_compat_clone_combo.currentData.return_value = "ref_audio"

        with patch("ui.settings_tts_page.os.path.isfile", return_value=False) as isfile:
            _TTSSettingsPage._update_reference_wav_warning(page)

        page._reference_wav_warning.setVisible.assert_called_once_with(True)
        isfile.assert_called_once_with(reference_wav)

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

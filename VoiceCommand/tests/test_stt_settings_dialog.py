import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QDialog

from ui.stt_settings_dialog import STTSettingsDialog


class _BareSTTSettingsDialog(STTSettingsDialog):
    """위젯 구성을 건너뛰고 저장 로직만 시험하기 위한 대화상자."""

    def __init__(self):
        QDialog.__init__(self)


class STTSettingsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self):
        dialog = _BareSTTSettingsDialog()
        dialog.voice_hotkey_edit = Mock()
        dialog.voice_hotkey_edit.keySequence.return_value.toString.return_value = "Ctrl+Alt+Space"
        dialog.wake_words_list = Mock()
        dialog.wake_words_list.count.return_value = 1
        dialog.wake_words_list.item.return_value.text.return_value = "Ari"
        for name in (
            "stt_provider_combo", "whisper_model_combo", "voice_activation_mode_combo",
            "wake_word_enabled_checkbox", "stt_energy_slider", "stt_dynamic_checkbox",
        ):
            setattr(dialog, name, Mock())
        dialog.stt_energy_slider.value.return_value = 300
        return dialog

    def test_save_failure_warns_and_keeps_dialog_open(self):
        dialog = self._dialog()
        with patch("ui.stt_settings_dialog.parse_global_hotkey"), \
                patch("ui.stt_settings_dialog.ConfigManager.load_settings", return_value={}), \
                patch("ui.stt_settings_dialog.ConfigManager.save_settings", return_value=False), \
                patch("ui.stt_settings_dialog.QMessageBox.warning") as warning, \
                patch.object(STTSettingsDialog, "accept") as accept:
            dialog._save()
            warning.assert_called_once()
            accept.assert_not_called()

    def test_successful_save_accepts_dialog(self):
        dialog = self._dialog()
        with patch("ui.stt_settings_dialog.parse_global_hotkey"), \
                patch("ui.stt_settings_dialog.ConfigManager.load_settings", return_value={}), \
                patch("ui.stt_settings_dialog.ConfigManager.save_settings", return_value=True), \
                patch("ui.stt_settings_dialog.QMessageBox.warning") as warning, \
                patch.object(STTSettingsDialog, "accept") as accept:
            dialog._save()
            warning.assert_not_called()
            accept.assert_called_once()


if __name__ == "__main__":
    unittest.main()

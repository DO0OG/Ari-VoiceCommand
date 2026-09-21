import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ui.settings_dialog import SettingsDialog


class SettingsSecretUITests(unittest.TestCase):
    def test_page_credentials_use_config_gateway_and_failed_save_stays_open(self):
        field = Mock()
        field.text.return_value = "1.0"
        field.toPlainText.return_value = "text"
        field.currentData.return_value = "ko"
        field.value.return_value = 100
        names = (
            "personality_input", "scenario_input", "system_input", "history_input",
            "verbosity_combo", "mic_combo", "speaker_combo", "char_scale_slider",
            "char_offset_slider", "theme_preset_combo", "theme_scale_input",
            "theme_font_input", "lang_combo",
        )
        dialog = SimpleNamespace(**dict.fromkeys(names, field))
        dialog.original_settings = {}
        dialog._float = lambda value, default: float(value)
        dialog._llm_page = Mock()
        dialog._llm_page.get_values.return_value = {"groq_api_key": "test-llm"}
        dialog._tts_page = Mock()
        dialog._tts_page.get_values.return_value = {"fish_api_key": "test-tts"}
        dialog._agent_page = Mock()
        dialog._agent_page.get_values.return_value = {"google_client_secret": "test-google"}
        dialog.accept = Mock()
        with patch("ui.settings_dialog.ConfigManager.save_settings", return_value=False) as save:
            with patch("ui.settings_dialog.QMessageBox.warning") as warning:
                SettingsDialog._save(dialog)
        payload = save.call_args.args[0]
        self.assertEqual(payload["groq_api_key"], "test-llm")
        self.assertEqual(payload["fish_api_key"], "test-tts")
        self.assertEqual(payload["google_client_secret"], "test-google")
        self.assertEqual(dialog.changed_keys, set())
        warning.assert_called_once()
        dialog.accept.assert_not_called()


if __name__ == "__main__":
    unittest.main()

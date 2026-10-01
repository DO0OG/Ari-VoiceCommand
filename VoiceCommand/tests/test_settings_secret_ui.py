import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QScrollArea

from ui.settings_dialog import SettingsDialog
from ui.stt_settings_dialog import STTSettingsDialog


class SettingsSecretUITests(unittest.TestCase):
    def test_device_tab_uses_scroll_area(self):
        self._app = QApplication.instance() or QApplication([])
        with patch("ui.settings_dialog.ConfigManager.load_settings", return_value={}):
            dialog = SettingsDialog()
        self.addCleanup(dialog.deleteLater)

        device_tab = dialog.tabs.widget(3)
        self.assertIsInstance(device_tab, QScrollArea)
        self.assertTrue(device_tab.widgetResizable())
        self.assertEqual(device_tab.frameShape(), QScrollArea.Shape.NoFrame)
        dialog.reject()

    def test_agent_and_plugin_tabs_use_scroll_areas(self):
        self._app = QApplication.instance() or QApplication([])
        with patch("ui.settings_dialog.ConfigManager.load_settings", return_value={}):
            dialog = SettingsDialog()
        self.addCleanup(dialog.deleteLater)

        for title, page in (("에이전트", dialog._agent_page), ("확장", dialog._plugin_page)):
            index = next(
                index for index in range(dialog.tabs.count())
                if dialog.tabs.tabText(index) == title
            )
            scroll = dialog.tabs.widget(index)
            self.assertIsInstance(scroll, QScrollArea)
            self.assertIs(scroll.widget(), page)
        dialog.reject()

    def test_agent_page_keeps_minimum_height_when_dialog_is_reduced(self):
        self._app = QApplication.instance() or QApplication([])
        with patch("ui.settings_dialog.ConfigManager.load_settings", return_value={}):
            dialog = SettingsDialog()
        self.addCleanup(dialog.deleteLater)

        dialog.resize(605, 600)
        dialog.show()
        self._app.processEvents()

        self.assertGreaterEqual(
            dialog._agent_page.height(),
            dialog._agent_page.minimumSizeHint().height(),
        )
        dialog.reject()

    def test_real_dialog_builds_every_tab(self):
        self._app = QApplication.instance() or QApplication([])
        with patch("ui.settings_dialog.ConfigManager.load_settings", return_value={}):
            dialog = SettingsDialog()
        self.addCleanup(dialog.deleteLater)
        self.assertIsNotNone(dialog.audio_diagnostic_panel)
        dialog.reject()

    def test_stt_energy_slider_preserves_low_and_large_saved_thresholds(self):
        self._app = QApplication.instance() or QApplication([])
        for threshold in (7, 5000):
            with patch(
                "ui.stt_settings_dialog.ConfigManager.load_settings",
                return_value={"stt_energy_threshold": threshold},
            ):
                dialog = STTSettingsDialog()

            self.assertEqual(dialog.stt_energy_slider.minimum(), 1)
            self.assertGreaterEqual(dialog.stt_energy_slider.maximum(), threshold)
            self.assertEqual(dialog.stt_energy_slider.value(), threshold)
            self.assertFalse(dialog.stt_dynamic_checkbox.isChecked())
            dialog.deleteLater()

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
            "theme_font_input", "lang_combo", "update_check_enabled",
            "activity_idle_checkbox", "activity_lock_checkbox", "activity_quiet_checkbox",
            "activity_away_threshold_spin", "activity_app_checkbox",
            "activity_quiet_bubble_checkbox", "activity_auto_game_mode_checkbox",
            "activity_ide_long_use_checkbox",
            "examples_en_input", "examples_ja_input",
        )
        dialog = SimpleNamespace(**dict.fromkeys(names, field))
        dialog.update_checker = None
        dialog.original_settings = {}
        dialog._float = lambda value, default: float(value)
        dialog._llm_page = Mock()
        dialog._llm_page.get_values.return_value = {"groq_api_key": "test-llm"}
        dialog._tts_page = Mock()
        dialog._tts_page.get_values.return_value = {"fish_api_key": "test-tts"}
        dialog._agent_page = Mock()
        agent_value = "test-google"
        dialog._agent_page.get_values.return_value = {"google_client_secret": agent_value}
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

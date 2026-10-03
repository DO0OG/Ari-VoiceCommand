import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QScrollArea

from ui.settings_dialog import SettingsDialog
from ui.stt_settings_dialog import STTSettingsDialog


class SettingsSecretUITests(unittest.TestCase):
    def setUp(self):
        connected = patch("services.google_auth.is_connected", return_value=False)
        connected.start()
        self.addCleanup(connected.stop)

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

    def test_plugin_lists_keep_several_rows_when_dialog_is_reduced(self):
        self._app = QApplication.instance() or QApplication([])
        with patch("ui.settings_dialog.ConfigManager.load_settings", return_value={}):
            dialog = SettingsDialog()
        self.addCleanup(dialog.deleteLater)

        dialog.resize(605, 550)
        dialog.show()
        # 선택된 탭만 배치되므로 탭을 고른 뒤 높이를 잰다.
        dialog.tabs.setCurrentIndex(next(
            index for index in range(dialog.tabs.count())
            if dialog.tabs.tabText(index) == "확장"
        ))
        self._app.processEvents()

        page = dialog._plugin_page
        for list_widget in (page.marketplace_list, page.plugin_list, page.skill_list_widget):
            self.assertGreaterEqual(list_widget.height(), 96)
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

    def test_save_reloads_llm_provider_when_llm_settings_change(self):
        field = Mock()
        field.toPlainText.return_value = ""
        field.currentData.return_value = None
        field.value.return_value = 0
        field.text.return_value = "1.0"
        field.isChecked.return_value = False
        dialog = SimpleNamespace(**dict.fromkeys((
            "personality_input", "examples_en_input", "examples_ja_input",
            "scenario_input", "system_input", "history_input", "verbosity_combo",
            "mic_combo", "speaker_combo", "char_scale_slider", "char_offset_slider",
            "theme_preset_combo", "theme_scale_input", "theme_font_input", "lang_combo",
            "update_check_enabled", "activity_idle_checkbox", "activity_lock_checkbox",
            "activity_quiet_checkbox", "activity_away_threshold_spin", "activity_app_checkbox",
            "activity_quiet_bubble_checkbox", "activity_auto_game_mode_checkbox",
            "activity_ide_long_use_checkbox",
        ), field))
        dialog.original_settings = {"llm_router_enabled": False, "llm_provider": "groq"}
        dialog.update_checker = None
        dialog._float = lambda value, default: float(value)
        dialog._llm_page = Mock()
        dialog._llm_page.get_values.return_value = {"llm_router_enabled": True}
        dialog._tts_page = Mock()
        dialog._tts_page.get_values.return_value = {}
        dialog._agent_page = Mock()
        dialog._agent_page.get_values.return_value = {}
        dialog.LLM_KEYS = SettingsDialog.LLM_KEYS
        dialog.llm_settings_changed = lambda: SettingsDialog.llm_settings_changed(dialog)
        dialog.character_settings_changed = lambda: False
        dialog.theme_settings_changed = lambda: False
        dialog.accept = Mock()

        started_threads = []

        class ImmediateThread:
            def __init__(self, target, **kwargs):
                self.target = target
                self.kwargs = kwargs
                started_threads.append(self)

            def start(self):
                self.target()

        # 창을 연 뒤 다른 경로가 설정을 바꿨다. 이 창에서 건드리지 않은 값은 그대로 저장돼야 한다.
        current = {"llm_router_enabled": False, "llm_provider": "openai"}
        with patch("ui.settings_dialog.ConfigManager.save_settings", return_value=True) as save, \
             patch("ui.settings_dialog.ConfigManager.load_settings", return_value=current), \
             patch("ui.settings_dialog.refresh_activity_monitor"), \
             patch("ui.settings_dialog.get_language", return_value=None), \
             patch("agent.llm_provider.reload_llm_provider") as reload_provider, \
             patch("threading.Thread", ImmediateThread):
            SettingsDialog._save(dialog)
            reload_provider.assert_called_once_with()
            self.assertEqual(started_threads[0].kwargs["name"], "LLM-Reload")
            saved = save.call_args.args[0]
            self.assertEqual(saved["llm_provider"], "openai")
            self.assertTrue(saved["llm_router_enabled"])

        self.assertIn("llm_router_enabled", dialog.changed_keys)


if __name__ == "__main__":
    unittest.main()

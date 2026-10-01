import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.settings_agent_page import _AgentSettingsPage


class LocalDecisionSettingsSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _saved(self, mode, direct):
        page = _AgentSettingsPage({"local_decision_mode": mode, "local_decision_direct_execution": direct})
        values = page.get_values()
        return values["local_decision_mode"], values["local_decision_direct_execution"]

    def test_missing_local_decision_settings_default_to_fast(self):
        page = _AgentSettingsPage({})

        self.assertTrue(page.local_decision_checkbox.isChecked())
        self.assertEqual(page.get_values()["local_decision_mode"], "fast")
        self.assertTrue(page.get_values()["local_decision_direct_execution"])

    def test_saving_other_settings_keeps_the_stored_pair(self):
        self.assertEqual(self._saved("off", False), ("off", False))
        self.assertEqual(self._saved("shadow", False), ("shadow", False))
        self.assertEqual(self._saved("fast", False), ("fast", False))
        self.assertEqual(self._saved("fast", True), ("fast", True))

    def test_toggle_turns_direct_execution_on_and_off(self):
        page = _AgentSettingsPage({"local_decision_mode": "off", "local_decision_direct_execution": False})
        page.local_decision_checkbox.setChecked(True)
        self.assertEqual(page.get_values()["local_decision_mode"], "fast")
        self.assertIs(page.get_values()["local_decision_direct_execution"], True)
        page.local_decision_checkbox.setChecked(False)
        self.assertEqual(page.get_values()["local_decision_mode"], "off")
        self.assertIs(page.get_values()["local_decision_direct_execution"], False)

    def test_learning_diagnostics_show_insufficient_samples(self):
        metrics = SimpleNamespace(
            get_component_diagnostics=lambda: [
                {"name": "EpisodeMemory", "state": "pending"},
                {"name": "GoalPredictor", "state": "active"},
            ]
        )
        with patch(
            "ui.settings_agent_page.get_learning_metrics", return_value=metrics
        ):
            with patch("ui.settings_agent_page._", side_effect=lambda value: value):
                page = _AgentSettingsPage({})

        self.assertIn("EpisodeMemory: 판정 보류(표본 부족)", page.learning_metrics_status.text())
        self.assertIn("GoalPredictor: 활성화", page.learning_metrics_status.text())

    def test_plugin_hot_reload_is_disabled_by_default_and_can_be_enabled(self):
        page = _AgentSettingsPage({})
        self.assertIs(page.get_values()["plugin_hot_reload_enabled"], False)

        page.plugin_hot_reload_checkbox.setChecked(True)

        self.assertIs(page.get_values()["plugin_hot_reload_enabled"], True)


if __name__ == "__main__":
    unittest.main()

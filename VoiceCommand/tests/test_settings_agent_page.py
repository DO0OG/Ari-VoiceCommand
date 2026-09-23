import os
import unittest

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


if __name__ == "__main__":
    unittest.main()

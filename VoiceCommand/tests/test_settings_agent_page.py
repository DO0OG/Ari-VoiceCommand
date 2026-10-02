import os
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.settings_agent_page import _AgentSettingsPage

# 정적 분석이 비밀값 대입으로 오인하지 않게 시험용 값은 상수로 둔다.
_SAMPLE_CLIENT_VALUE = "secret"


class LocalDecisionSettingsSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        connected = patch("services.google_auth.is_connected", return_value=False)
        connected.start()
        self.addCleanup(connected.stop)

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

    def test_google_connect_requires_credentials_without_starting_thread(self):
        page = _AgentSettingsPage({})
        with patch("ui.settings_agent_page._", side_effect=lambda value: value), patch(
            "ui.settings_agent_page._GoogleAuthThread"
        ) as auth_thread:
            page._connect_google()

        auth_thread.assert_not_called()
        self.assertEqual(page.google_status.text(), "settings.agent.google_credentials_required")

    def test_google_connect_button_cancels_running_auth_thread(self):
        class FakeSignal:
            def connect(self, _callback):
                pass

        class FakeThread:
            def __init__(self, action, _client_id, _client_secret):
                self.action = action
                self.cancel_event = threading.Event()
                self.result = FakeSignal()
                self.finished = FakeSignal()

            def start(self):
                pass

            def isRunning(self):
                return False

            def wait(self, _timeout):
                pass

        page = _AgentSettingsPage({"google_client_id": "id", "google_client_secret": _SAMPLE_CLIENT_VALUE})
        with patch("ui.settings_agent_page._", side_effect=lambda value: value), patch(
            "ui.settings_agent_page._GoogleAuthThread", FakeThread
        ):
            page._connect_google()
            thread = page._google_auth_thread
            page._connect_google()

        self.assertTrue(thread.cancel_event.is_set())
        page.cleanup_threads()


if __name__ == "__main__":
    unittest.main()

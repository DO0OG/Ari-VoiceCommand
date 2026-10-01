import os
import unittest
from dataclasses import asdict

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from agent.planner.action_step import ActionStep
from ui.execution_dashboard_panel import ExecutionDashboardPanel


class ExecutionDashboardPanelTests(unittest.TestCase):
    def setUp(self):
        self._app = QApplication.instance() or QApplication([])

    def test_plan_ready_accepts_orchestrator_step_dicts(self):
        panel = ExecutionDashboardPanel()
        self.addCleanup(panel.deleteLater)
        step = ActionStep(step_id=1, step_type="python", content="print(1)", description_kr="합계 계산")

        panel.on_progress("plan_ready", steps=[asdict(step)], iteration=0)
        panel.on_progress("step_start", step_id=1, desc="합계 계산", step_type="python")
        panel.on_progress("step_done", step_id=1, success=True, was_fixed=False, error="")

        self.assertEqual(panel._steps[1], {"desc": "합계 계산", "type": "python", "status": "done"})


if __name__ == "__main__":
    unittest.main()

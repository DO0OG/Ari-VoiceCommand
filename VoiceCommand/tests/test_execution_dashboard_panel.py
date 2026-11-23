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

    def test_plan_approval_shows_targets_and_reports_decision_once(self):
        panel = ExecutionDashboardPanel()
        self.addCleanup(panel.deleteLater)
        decisions = []
        panel.plan_decision.connect(decisions.append)
        step = ActionStep(
            step_id=1, step_type="python", content="x", description_kr="파일 정리",
            reads=["a.txt"], writes=["b.txt"],
        )

        panel.on_progress("plan_approval_request", steps=[asdict(step)], iteration=0)

        self.assertFalse(panel._approval_widget.isHidden())
        self.assertTrue(panel._awaiting_approval)
        self.assertEqual(panel._targets[1], (["a.txt"], ["b.txt"]))
        panel._run_btn.click()
        panel._run_btn.click()
        self.assertEqual(decisions, [True])
        self.assertTrue(panel._approval_widget.isHidden())

    def test_plan_declined_closes_approval_buttons_without_decision(self):
        panel = ExecutionDashboardPanel()
        self.addCleanup(panel.deleteLater)
        decisions = []
        panel.plan_decision.connect(decisions.append)
        step = ActionStep(step_id=1, step_type="python", content="x", description_kr="파일 정리")

        panel.on_progress("plan_approval_request", steps=[asdict(step)], iteration=0)
        panel.on_progress("plan_declined", iteration=0)

        self.assertTrue(panel._approval_widget.isHidden())
        self.assertFalse(panel._awaiting_approval)
        panel._cancel_btn.click()
        self.assertEqual(decisions, [])

    def test_auto_hide_timer_does_not_hide_pending_approval(self):
        panel = ExecutionDashboardPanel()
        self.addCleanup(panel.deleteLater)
        step = ActionStep(step_id=1, step_type="python", content="x", description_kr="파일 정리")

        panel.on_progress("plan_approval_request", steps=[asdict(step)], iteration=0)
        panel._auto_hide()  # 이전 실행 종료 뒤 걸린 숨김 타이머가 지금 불린 상황
        self.assertFalse(panel.isHidden())
        self.assertFalse(panel._approval_widget.isHidden())

        panel._run_btn.click()
        panel._auto_hide()
        self.assertTrue(panel.isHidden())

    def test_long_step_description_does_not_widen_panel(self):
        panel = ExecutionDashboardPanel()
        self.addCleanup(panel.deleteLater)
        step = ActionStep(
            step_id=1,
            step_type="python",
            content="print(1)",
            description_kr="downloads_folder_report_with_a_very_long_unbroken_name " * 2,
        )

        panel.on_progress("plan_ready", steps=[asdict(step)], iteration=0)

        self.assertLessEqual(panel.minimumSizeHint().width(), 420)


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.autonomous_executor import AutonomousExecutor


class AutonomousExecutorTests(unittest.TestCase):
    def test_runner_script_exposes_learned_strategies_helpers(self):
        executor = AutonomousExecutor()

        script = executor._build_python_runner_script("print('ok')")

        self.assertIn('"get_learned_strategies": _automation.get_learned_strategies', script)
        self.assertIn('"get_learned_strategy_summary": _automation.get_learned_strategy_summary', script)
        self.assertIn('"get_planning_snapshot": _automation.get_planning_snapshot', script)
        self.assertIn('"get_planning_snapshot_summary": _automation.get_planning_snapshot_summary', script)
        self.assertIn('"run_adaptive_browser_workflow": _automation.run_adaptive_browser_workflow', script)
        self.assertIn('"run_resilient_browser_workflow": _automation.run_resilient_browser_workflow', script)
        self.assertIn('"run_adaptive_desktop_workflow": _automation.run_adaptive_desktop_workflow', script)
        self.assertIn('"run_resilient_desktop_workflow": _automation.run_resilient_desktop_workflow', script)
        self.assertIn('"build_adaptive_browser_plan": _automation.build_adaptive_browser_plan', script)
        self.assertIn('"build_resilient_browser_plans": _automation.build_resilient_browser_plans', script)
        self.assertIn('"build_adaptive_desktop_plan": _automation.build_adaptive_desktop_plan', script)
        self.assertIn('"build_resilient_desktop_plans": _automation.build_resilient_desktop_plans', script)
        self.assertIn('"get_desktop_state": _automation.get_desktop_state', script)
        self.assertIn('"list_open_windows": _automation.list_open_windows', script)
        self.assertIn('"learned_strategies": _automation.get_learned_strategies()', script)
        self.assertIn('"learned_strategy_summary": _automation.get_learned_strategy_summary()', script)
        self.assertIn('"planning_snapshot": _automation.get_planning_snapshot()', script)
        self.assertIn('"planning_snapshot_summary": _automation.get_planning_snapshot_summary()', script)


if __name__ == "__main__":
    unittest.main()

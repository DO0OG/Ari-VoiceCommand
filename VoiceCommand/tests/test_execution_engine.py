import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.agent_planner import ActionStep
from agent.autonomous_executor import ExecutionResult
from agent.execution_engine import ExecutionEngine


class ExecutionEngineConditionTests(unittest.TestCase):
    def setUp(self):
        self.engine = ExecutionEngine.__new__(ExecutionEngine)

    def test_eval_condition_returns_false_for_invalid_expression(self):
        self.assertFalse(self.engine._eval_condition("step_outputs[", {}))

    def test_eval_condition_returns_false_for_disallowed_name(self):
        self.assertFalse(self.engine._eval_condition("unknown_name == 1", {}))

    def test_eval_condition_returns_true_for_valid_expression(self):
        context = {"step_1_output": "done"}
        self.assertTrue(
            self.engine._eval_condition("step_outputs.get('step_1_output') == 'done'", context)
        )

    def test_eval_condition_returns_true_for_allowed_length_check(self):
        context = {"step_1_output": "done", "step_2_output": "saved"}
        self.assertTrue(self.engine._eval_condition("len(step_outputs) == 2", context))

    def test_execute_step_with_retry_restores_backups_for_failed_write_steps(self):
        engine = ExecutionEngine.__new__(ExecutionEngine)
        engine.MAX_STEP_RETRIES = 0
        engine.executor = SimpleNamespace(restore_last_backup=MagicMock())
        engine.planner = SimpleNamespace(fix_step=lambda *args, **kwargs: None)
        engine._say = lambda message: None
        engine._auto_install_if_needed = lambda error: False
        engine._run_step = lambda step, context: ExecutionResult(success=False, error="boom")

        step = ActionStep(
            step_id=1,
            step_type="python",
            content="save_document(...)",
            description_kr="문서 저장",
            writes=[r"C:\temp\report.txt"],
        )

        result, attempts, was_fixed = engine._execute_step_with_retry(step, "보고서 저장", {})

        self.assertFalse(result.success)
        self.assertEqual(attempts, 1)
        self.assertFalse(was_fixed)
        engine.executor.restore_last_backup.assert_called_once_with(r"C:\temp\report.txt")
        self.assertIn("자동 복구", result.output)


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

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


if __name__ == "__main__":
    unittest.main()

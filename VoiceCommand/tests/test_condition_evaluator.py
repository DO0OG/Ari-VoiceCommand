import unittest


from agent.condition_evaluator import evaluate_condition


class ConditionEvaluatorTests(unittest.TestCase):
    def test_evaluate_condition_supports_dict_get(self):
        self.assertTrue(
            evaluate_condition("step_outputs.get('step_1_output') == 'done'", {"step_1_output": "done"})
        )

    def test_evaluate_condition_supports_comparison_chain(self):
        self.assertTrue(evaluate_condition("1 < 2 < 3", {}))

    def test_evaluate_condition_rejects_disallowed_function(self):
        with self.assertRaises(ValueError):
            evaluate_condition("sum([1, 2, 3]) > 0", {})


if __name__ == "__main__":
    unittest.main()

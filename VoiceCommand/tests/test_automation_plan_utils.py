import unittest


from agent.automation_plan_utils import (
    action_plan_cache_key,
    build_ranked_plans,
    merge_action_sequences,
)


class AutomationPlanUtilsTests(unittest.TestCase):
    def test_merge_action_sequences_deduplicates_same_action_fingerprint(self):
        actions = merge_action_sequences(
            [{"type": "click", "selectors": ["#download"]}],
            [{"type": "click", "selectors": ["#download"]}, {"type": "wait_url", "contains": "example.com"}],
        )

        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0]["type"], "click")
        self.assertEqual(actions[1]["type"], "wait_url")

    def test_build_ranked_plans_sorts_and_deduplicates_equivalent_plans(self):
        plan_specs = [
            ("adaptive", [{"type": "click", "selectors": ["#download"]}], True),
            ("learned_only", [{"type": "click", "selectors": ["#download"]}], True),
            ("fallback_only", [{"type": "wait_url", "contains": "example.com"}], False),
        ]

        plans = build_ranked_plans(
            plan_specs,
            goal_hint="로그인 후 다운로드",
            summary_kind="browser",
            base_fields={"domain": "example.com"},
            augment_actions=lambda actions: list(actions),
            dedupe_key=lambda actions: action_plan_cache_key(actions, "example.com"),
            score_plan=lambda plan: {"adaptive": 3.2, "learned_only": 2.1, "fallback_only": 1.0}[plan["plan_type"]],
            describe_reason=lambda plan: f"{plan['plan_type']} selected",
        )

        self.assertEqual([plan["plan_type"] for plan in plans], ["adaptive", "fallback_only"])
        self.assertEqual(plans[0]["selection_reason"], "adaptive selected")
        self.assertIn("browser:adaptive", plans[0]["summary"])


if __name__ == "__main__":
    unittest.main()

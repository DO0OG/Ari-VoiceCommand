import unittest

from agent.decision.semantics import (
    SemanticParse,
    action_anchor_count,
    connector_count,
    parse_candidate,
)


class DecisionSemanticsTests(unittest.TestCase):
    def test_success_requires_all_four_signals(self):
        parsed = parse_candidate("what time is it", "get_current_time")

        self.assertTrue(parsed.valid)
        self.assertTrue(parsed.intent_confirmed)
        self.assertFalse(parsed.contradiction)
        self.assertFalse(parsed.residual_action)
        self.assertTrue(parsed.parse_success)

    def test_each_failed_signal_blocks_success(self):
        cases = (
            SemanticParse("get_current_time", "en", valid=False, intent_confirmed=True),
            SemanticParse("get_current_time", "en", valid=True, intent_confirmed=False),
            SemanticParse("get_current_time", "en", valid=True, intent_confirmed=True, contradiction=True),
            SemanticParse("get_current_time", "en", valid=True, intent_confirmed=True, residual_action=True),
        )
        for parsed in cases:
            with self.subTest(parsed=parsed):
                self.assertFalse(parsed.parse_success)

    def test_window_close_is_a_contradiction_even_for_excluded_candidate(self):
        parsed = parse_candidate("Close the Chrome window", "focus_window")

        self.assertTrue(parsed.contradiction)
        self.assertFalse(parsed.parse_success)

    def test_connector_and_action_anchors_mark_compound_request(self):
        text = "what time is it and take a screenshot"

        self.assertGreaterEqual(connector_count(text, "en"), 1)
        self.assertGreaterEqual(action_anchor_count(text, "en"), 2)
        parsed = parse_candidate(text, "get_current_time")
        self.assertTrue(parsed.residual_action)
        self.assertFalse(parsed.parse_success)

    def test_relative_volume_requires_integer_amount(self):
        parsed = parse_candidate("increase volume by 10%", "adjust_volume")

        self.assertTrue(parsed.parse_success)
        self.assertEqual(parsed.arguments, {"direction": "up", "amount": 10})

        for text in ("increase volume", "set volume to 50", "increase volume by 10.5%"):
            with self.subTest(text=text):
                self.assertFalse(parse_candidate(text, "adjust_volume").parse_success)

    def test_mute_uses_fixed_safe_amount(self):
        parsed = parse_candidate("음소거해줘", "adjust_volume")

        self.assertTrue(parsed.parse_success)
        self.assertEqual(parsed.arguments, {"direction": "mute", "amount": 100})


if __name__ == "__main__":
    unittest.main()

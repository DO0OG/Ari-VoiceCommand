import json
import tempfile
import unittest
from pathlib import Path

from scripts.decision_data.acceptance import classify, run


class DecisionAcceptanceTests(unittest.TestCase):
    def test_outcomes_are_classified_by_what_actually_ran(self):
        volume = {"label": "adjust_volume", "expected_outcome": "direct_or_fallback",
                  "expected_arguments": {"direction": "up", "amount_percent": 20}}
        cases = (
            (volume, [("adjust_volume", {"direction": "up", "amount": 20})], 0, "direct"),
            (volume, [("adjust_volume", {"direction": "up"})], 0, "direct_mistake"),
            (volume, [("take_screenshot", {})], 0, "direct_mistake"),
            ({**volume, "expected_outcome": "fallback_required"},
             [("adjust_volume", {"direction": "up", "amount": 20})], 0, "direct_mistake"),
            (volume, [("adjust_volume", {"direction": "up", "amount": 20})], 1, "duplicate_action"),
            (volume, [], 0, "fallback_failure"),
            (volume, [], 1, "fallback"),
        )
        for row, calls, chats, expected in cases:
            with self.subTest(calls=calls, chats=chats, expected=expected):
                self.assertEqual(classify(row, calls, chats), expected)

    def test_harness_fails_when_a_fallback_only_sentence_runs_directly(self):
        rows = (
            {"id": "t1", "corpus": "fixture", "language": "en", "text": "what time is it",
             "label": "get_current_time", "expected_outcome": "fallback_required"},
            {"id": "t2", "corpus": "fixture", "language": "en", "text": "tell me a story",
             "label": "unknown_or_complex", "expected_outcome": "fallback_required"},
        )
        with tempfile.TemporaryDirectory() as directory:
            corpus = Path(directory) / "fixture.jsonl"
            corpus.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            result = run([corpus])

        self.assertFalse(result["passed"])
        self.assertEqual(result["failures"], [{"id": "t1", "outcome": "direct_mistake"}])
        self.assertEqual(result["totals"], {"direct_mistake": 1, "fallback": 1})


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from scripts.decision_data.acceptance import DIRECT_REQUIRED_ROWS, classify, run


class DecisionAcceptanceTests(unittest.TestCase):
    def test_outcomes_are_classified_by_what_actually_ran(self):
        volume = {"label": "adjust_volume", "expected_outcome": "direct_or_fallback",
                  "expected_arguments": {"direction": "up", "amount_percent": 20}}
        cases = (
            (volume, [("adjust_volume", {"direction": "up", "amount": 20})], 0, "direct"),
            ({"label": "adjust_volume", "expected_arguments": {"direction": "up"}},
             [("adjust_volume", {"direction": "up", "amount": 10})], 0, "direct"),
            ({"label": "adjust_volume", "expected_arguments": {"direction": "up"}},
             [("adjust_volume", {"direction": "up"})], 0, "direct"),
            (volume, [("adjust_volume", {"direction": "up"})], 0, "direct_mistake"),
            (volume, [("take_screenshot", {})], 0, "direct_mistake"),
            ({"label": "take_screenshot", "expected_arguments": {}},
             [("take_screenshot", {"path": "unexpected.png"})], 0, "direct_mistake"),
            ({"label": "take_screenshot", "expected_arguments": {"target": "current_display"}},
             [("take_screenshot", {})], 0, "direct"),
            ({"label": "adjust_volume", "expected_arguments": {"direction": "up"}},
             [("adjust_volume", {"direction": "up", "amount": 100})], 0, "direct_mistake"),
            ({"label": "adjust_volume", "expected_arguments": {"direction": "up", "amount_percent": 20}},
             [("adjust_volume", {"direction": "up", "amount": 20, "unexpected": True})], 0,
             "direct_mistake"),
            ({**volume, "expected_outcome": "fallback_required"},
             [("adjust_volume", {"direction": "up", "amount": 20})], 0, "direct_mistake"),
            (volume, [("adjust_volume", {"direction": "up", "amount": 20})], 1, "duplicate_action"),
            (volume, [], 0, "fallback_failure"),
            (volume, [], 1, "fallback"),
            ({**volume, "expected_outcome": "direct_required"}, [], 1, "direct_miss"),
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

    def test_required_rows_run_directly_and_rejected_rows_are_skipped(self):
        rejected = {"id": "r1", "corpus": "fixture", "language": "en", "text": "what time is it",
                    "label": "get_current_time", "expected_outcome": "fallback_required",
                    "review_status": "human_rejected"}
        with tempfile.TemporaryDirectory() as directory:
            corpus = Path(directory) / "fixture.jsonl"
            corpus.write_text(json.dumps(rejected), encoding="utf-8")
            result = run([corpus], required_rows=DIRECT_REQUIRED_ROWS)

        self.assertTrue(result["passed"], result["failures"])
        self.assertEqual(result["totals"], {"direct": len(DIRECT_REQUIRED_ROWS)})
        self.assertEqual(
            {(row["label"], row["language"]) for row in DIRECT_REQUIRED_ROWS},
            {(tool, language) for tool in ("get_current_time", "adjust_volume", "take_screenshot",
                                           "get_running_apps") for language in ("ko", "en", "ja")},
        )


if __name__ == "__main__":
    unittest.main()

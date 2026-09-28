import unittest
from datetime import datetime, timedelta

from memory.trust_engine import batch_decay


class TrustEngineTests(unittest.TestCase):
    def test_decay_is_idempotent_for_repeated_calls_on_same_date(self):
        now = datetime(2026, 9, 29)
        facts = {
            "fact": {
                "updated_at": (now - timedelta(days=90)).isoformat(),
                "confidence": 0.55,
                "base_confidence": 0.55,
                "access_count": 0,
                "conflict_count": 0,
            }
        }

        first = batch_decay(facts, now)
        repeated = first
        for _ in range(10):
            repeated = batch_decay(repeated, now)

        self.assertEqual(repeated, first)

    def test_fact_at_180_days_has_expected_confidence_and_is_retained(self):
        now = datetime(2026, 9, 29)
        facts = {
            "fact": {
                "updated_at": (now - timedelta(days=180)).isoformat(),
                "confidence": 0.55,
                "base_confidence": 0.55,
                "access_count": 0,
                "conflict_count": 0,
            }
        }

        decayed = batch_decay(facts, now)

        self.assertIn("fact", decayed)
        self.assertAlmostEqual(decayed["fact"]["confidence"], 0.40, places=2)


if __name__ == "__main__":
    unittest.main()

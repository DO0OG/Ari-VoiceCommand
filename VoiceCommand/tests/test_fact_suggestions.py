import tempfile
import unittest

from memory.fact_suggestions import FactSuggestionStore


class FactSuggestionStoreTests(unittest.TestCase):
    def test_deduplicates_pending_and_resolved_suggestions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/fact_suggestions.json"
            store = FactSuggestionStore(path)
            candidate = {
                "type": "fact",
                "key": "직장",
                "value": "게임 회사",
                "kind": "stable",
                "evidence": "저는 게임 회사에서 일해요.",
                "confidence": 0.9,
            }

            self.assertEqual(store.add_suggestions([candidate, candidate]), 1)
            suggestion = store.get_suggestions()[0]
            self.assertIsNotNone(store.resolve(suggestion["id"], approved=False))
            self.assertEqual(store.add_suggestions([candidate]), 0)

            loaded = FactSuggestionStore(path)
            self.assertEqual(loaded.get_suggestions(), [])
            self.assertEqual(loaded.get_stats(), {"approved": 0, "rejected": 1})

    def test_limits_pending_suggestions(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = FactSuggestionStore(f"{tmp}/fact_suggestions.json")
            candidates = [
                {
                    "type": "fact",
                    "key": f"key-{index}",
                    "value": f"value-{index}",
                    "kind": "stable",
                    "evidence": "user said this",
                    "confidence": 0.8,
                }
                for index in range(105)
            ]

            self.assertEqual(store.add_suggestions(candidates), 105)
            self.assertEqual(len(store.get_suggestions()), 100)


if __name__ == "__main__":
    unittest.main()

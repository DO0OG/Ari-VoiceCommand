import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from memory.user_context import UserContextManager


class UserContextManagerTests(unittest.TestCase):
    def test_topics_and_bounded_lists_are_tracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "user_context.json")
            manager = UserContextManager(context_file=path)
            manager.record_topics(["자동화", "메모리", "자동화"])
            manager.update_bio("interests", "코딩")
            manager.update_bio("interests", "코딩")
            summary = manager.get_context_summary()
            self.assertIn("최근 대화 주제", summary)
            self.assertIn("관심사", summary)
            self.assertEqual(manager.context["conversation_topics"]["자동화"], 2)
            self.assertEqual(manager.context["user_bio"]["interests"], ["코딩"])

    def test_legacy_fact_shape_is_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "user_context.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"facts": {"좋아함": "커피"}}, handle, ensure_ascii=False)
            manager = UserContextManager(context_file=path)
            self.assertEqual(manager.context["facts"]["좋아함"]["value"], "커피")
            self.assertIn("confidence", manager.context["facts"]["좋아함"])


if __name__ == "__main__":
    unittest.main()

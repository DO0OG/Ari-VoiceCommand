import json
import os
import tempfile
import unittest


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

    def test_preference_and_time_based_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "user_context.json")
            manager = UserContextManager(context_file=path)
            manager.record_preference("음악", "로파이")
            manager.record_preference("음악", "로파이")
            manager.record_preference("음료", "커피")
            manager.record_command("weather")
            manager.record_command("weather")

            prefs = manager.get_top_preferences(limit=2)
            suggestions = manager.get_time_based_suggestions(limit=2)

            self.assertIn("음악:로파이", prefs)
            self.assertIn("weather", suggestions)

    def test_fact_conflicts_and_topic_recommendations_are_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "user_context.json")
            manager = UserContextManager(context_file=path)
            manager.record_fact("favorite_drink", "coffee", confidence=0.8)
            manager.record_fact("favorite_drink", "tea", confidence=0.6)
            manager.record_topics(["자동화", "자동화", "브라우저"])

            conflicts = manager.get_fact_conflicts("favorite_drink")
            recommendations = manager.get_topic_recommendations(limit=2, include_strategy=False)

            self.assertEqual(conflicts[0]["conflicted_with"], "coffee")
            self.assertTrue(any(item.startswith("자동화:") for item in recommendations))


if __name__ == "__main__":
    unittest.main()

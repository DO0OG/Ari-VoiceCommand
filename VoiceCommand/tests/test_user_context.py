import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch


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
            self.assertEqual(
                manager.context["facts"]["좋아함"]["base_confidence"],
                manager.context["facts"]["좋아함"]["confidence"],
            )

    def test_load_migrates_base_confidence_from_current_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "user_context.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {"facts": {"favorite": {"value": "tea", "confidence": 0.55}}},
                    handle,
                )

            manager = UserContextManager(context_file=path)

            self.assertEqual(manager.context["facts"]["favorite"]["base_confidence"], 0.55)

    def test_corrupt_context_is_backed_up_before_defaults_are_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "user_context.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{broken")

            manager = UserContextManager(context_file=path)

            self.assertEqual(manager.context["facts"], {})
            backups = [name for name in os.listdir(tmp) if ".corrupt-" in name]
            self.assertEqual(len(backups), 1)
            with open(os.path.join(tmp, backups[0]), encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "{broken")

    def test_concurrent_fact_mutations_keep_saved_json_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "user_context.json")
            manager = UserContextManager(context_file=path)
            barrier = threading.Barrier(4)
            errors = []

            def mutate(worker_id):
                try:
                    barrier.wait(timeout=2)
                    for index in range(25):
                        key = f"fact-{index % 5}"
                        manager.record_fact(key, f"value-{worker_id}-{index}")
                        if index % 2 == 0:
                            manager.optimize_memory()
                        if index % 3 == 0:
                            manager.delete_fact(key)
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=mutate, args=(worker,)) for worker in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            with open(path, encoding="utf-8") as handle:
                self.assertIsInstance(json.load(handle), dict)

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

    def test_update_bio_replaces_list_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(
                context_file=os.path.join(tmp, "user_context.json")
            )

            manager.update_bio("interests", ["music", "books", "music"])
            manager.update_bio("memos", [])

            self.assertEqual(manager.context["user_bio"]["interests"], ["books", "music"])
            self.assertEqual(manager.context["user_bio"]["memos"], [])

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
            conflicted = manager.context["facts"]["favorite_drink"]
            self.assertEqual(conflicted["base_confidence"], conflicted["confidence"])
            self.assertTrue(conflicted["updated_at"])

    def test_reinforcement_resets_base_confidence_and_update_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(
                context_file=os.path.join(tmp, "user_context.json")
            )
            manager.record_fact("favorite_color", "blue", source="user", ttl_days=0)
            manager.record_fact("favorite_color", "blue", source="user", ttl_days=0)

            fact = manager.context["facts"]["favorite_color"]

            self.assertEqual(fact["base_confidence"], fact["confidence"])
            self.assertTrue(fact["updated_at"])

    def test_default_fact_survives_180_day_decay(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(
                context_file=os.path.join(tmp, "user_context.json")
            )
            manager.record_fact("long_lived", "value", source="user", confidence=0.45)
            fact = manager.context["facts"]["long_lived"]
            now = datetime(2026, 9, 29, 12)
            fact["updated_at"] = (now - timedelta(days=180)).isoformat()
            fact["confidence"] = 0.55
            fact["base_confidence"] = 0.55
            fact["expires_at"] = now.isoformat()

            with patch("memory.user_context.datetime") as mocked_datetime:
                mocked_datetime.now.return_value = now
                mocked_datetime.fromisoformat.side_effect = datetime.fromisoformat
                manager.optimize_memory()

            fact = manager.context["facts"]["long_lived"]
            self.assertAlmostEqual(fact["confidence"], 0.40, places=2)


if __name__ == "__main__":
    unittest.main()

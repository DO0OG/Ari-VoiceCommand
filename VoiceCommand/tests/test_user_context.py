import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch


from memory.user_context import UserContextManager
from memory.memory_index import MemoryIndex
from memory.conversation_history import ConversationHistory


class UserContextManagerTests(unittest.TestCase):
    def setUp(self):
        self.index_temp_dir = tempfile.TemporaryDirectory()
        self.test_index = MemoryIndex(os.path.join(self.index_temp_dir.name, "memory.db"))
        patcher = patch("memory.memory_index.get_memory_index", return_value=self.test_index)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.index_temp_dir.cleanup)

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
            index_patcher = patch("memory.memory_index.get_memory_index")
            memory_index = index_patcher.start()
            self.addCleanup(index_patcher.stop)
            memory_index.return_value.delete_fact.return_value = True
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

    def test_situation_metadata_resets_daily_and_after_idle_without_saving_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "user_context.json")
            manager = UserContextManager(context_file=path)
            start = datetime(2026, 9, 29, 9, 0)
            manager.record_interaction("You did great, Ari", now=start)

            active = manager.get_situation_metrics(now=start + timedelta(minutes=20))
            self.assertEqual(active["today_interaction_count"], 1)
            self.assertEqual(active["continuous_use_minutes"], 20)
            self.assertEqual(active["last_interaction_elapsed_minutes"], 20)
            self.assertEqual(active["seconds_since_last_interaction"], 20 * 60)
            self.assertEqual(active["recent_praise_count"], 1)

            follow_up = start + timedelta(minutes=20)
            manager.record_interaction("ordinary request", now=follow_up)
            active = manager.get_situation_metrics(now=start + timedelta(minutes=25))
            self.assertEqual(active["today_interaction_count"], 2)
            self.assertEqual(active["continuous_use_minutes"], 25)
            self.assertEqual(active["last_interaction_elapsed_minutes"], 5)
            self.assertEqual(active["seconds_since_last_interaction"], 5 * 60)

            idle = manager.get_situation_metrics(now=start + timedelta(minutes=51))
            self.assertEqual(idle["continuous_use_minutes"], 0)
            self.assertEqual(idle["last_interaction_elapsed_minutes"], 31)
            self.assertEqual(idle["seconds_since_last_interaction"], 31 * 60)

            next_day = start + timedelta(days=1, minutes=1)
            manager.record_interaction("ordinary request", now=next_day)
            next_day_metrics = manager.get_situation_metrics(now=next_day)
            self.assertEqual(next_day_metrics["today_interaction_count"], 1)
            self.assertEqual(next_day_metrics["recent_praise_count"], 0)
            self.assertEqual(next_day_metrics["continuous_use_minutes"], 0)
            self.assertEqual(
                set(manager.context["situation"]),
                {
                    "last_interaction_at",
                    "session_started_at",
                    "today_date",
                    "today_interaction_count",
                    "praise_timestamps",
                },
            )
            with open(path, encoding="utf-8") as handle:
                saved_context = handle.read()
            self.assertNotIn("You did great, Ari", saved_context)

    def test_interaction_records_praise_and_late_night_long_use_for_character_mood(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(
                context_file=os.path.join(tmp, "user_context.json")
            )
            mood_state = Mock()
            start = datetime(2026, 9, 29, 0, 0)

            with patch("memory.user_context.get_mood_state", return_value=mood_state):
                manager.record_interaction("You did great, Ari", now=start)
                manager.record_interaction(
                    "That's wrong, Ari",
                    now=start + timedelta(minutes=1),
                )
                for minutes in range(30, 181, 30):
                    now = start + timedelta(minutes=minutes)
                    manager.record_interaction("ordinary request", now=now)

            self.assertTrue(
                mood_state.record_interaction.call_args_list[0].kwargs["praised"]
            )
            self.assertTrue(
                mood_state.record_interaction.call_args_list[1].kwargs["criticized"]
            )
            self.assertTrue(
                mood_state.record_interaction.call_args_list[-1].kwargs[
                    "late_night_long_use"
                ]
            )
            with open(manager.context_file, "r", encoding="utf-8") as handle:
                saved_context = handle.read()
            self.assertNotIn("You did great, Ari", saved_context)

    def test_late_night_long_use_triggers_after_midnight_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(
                context_file=os.path.join(tmp, "user_context.json")
            )
            mood_state = Mock()
            start = datetime(2026, 9, 28, 21, 0)

            with patch("memory.user_context.get_mood_state", return_value=mood_state):
                for minutes in range(0, 211, 30):
                    manager.record_interaction(
                        "ordinary request",
                        now=start + timedelta(minutes=minutes),
                    )
                manager.record_interaction(
                    "ordinary request",
                    now=start + timedelta(hours=4),
                )
                manager.record_interaction(
                    "ordinary request",
                    now=start + timedelta(hours=4, minutes=30),
                )

            results = [
                call.kwargs["late_night_long_use"]
                for call in mood_state.record_interaction.call_args_list
            ]
            self.assertTrue(results[-2])
            self.assertFalse(results[-1])

    def test_negated_praise_markers_do_not_increase_mood(self):
        self.assertFalse(UserContextManager._contains_praise("not great"))
        self.assertFalse(UserContextManager._contains_praise("not good job"))
        self.assertFalse(UserContextManager._contains_praise("대단하지 않아"))
        self.assertFalse(UserContextManager._contains_praise("すごいわけではない"))
        self.assertFalse(UserContextManager._contains_praise("最高ではない"))
        self.assertTrue(UserContextManager._contains_praise("not great, thanks"))

    def test_praise_markers_cover_korean_english_and_japanese(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(
                context_file=os.path.join(tmp, "user_context.json")
            )
            start = datetime(2026, 9, 29, 9, 0)
            for minute, message in enumerate(("잘했어", "great job", "ありがとう", "👍")):
                manager.record_interaction(message, now=start + timedelta(minutes=minute))

            metrics = manager.get_situation_metrics(now=start + timedelta(minutes=3))

        self.assertEqual(metrics["recent_praise_count"], 4)

    def test_update_bio_replaces_list_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(
                context_file=os.path.join(tmp, "user_context.json")
            )

            manager.update_bio("interests", ["music", "books", "music"])
            manager.update_bio("memos", [])

            self.assertEqual(manager.context["user_bio"]["interests"], ["books", "music"])
            self.assertEqual(manager.context["user_bio"]["memos"], [])

    def test_bio_change_waits_for_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "user_context.json")
            manager = UserContextManager(
                context_file=path
            )
            manager.update_bio("name", "Min")

            applied = manager.request_bio_update("name", "Mina", "날씨 알려줘")
            reloaded = UserContextManager(context_file=path)

            self.assertFalse(applied)
            self.assertEqual(manager.context["user_bio"]["name"], "Min")
            self.assertEqual(
                reloaded.context["pending_bio"],
                [{"field": "name", "value": "Mina"}],
            )
            self.assertTrue(manager.approve_pending_bio("name", "Mina"))
            self.assertEqual(manager.context["user_bio"]["name"], "Mina")
            self.assertEqual(manager.context["pending_bio"], [])

    def test_repeated_bio_value_confirms_pending_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(
                context_file=os.path.join(tmp, "user_context.json")
            )
            manager.update_bio("name", "Min")
            manager.request_bio_update("name", "Mina", "오늘 날씨 알려줘")

            applied = manager.request_bio_update("name", "Mina", "내 이름은 Mina야")

            self.assertTrue(applied)
            self.assertEqual(manager.context["user_bio"]["name"], "Mina")
            self.assertEqual(manager.context["pending_bio"], [])

    def test_delete_fact_removes_fts_fact_and_optional_conversations(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(
                context_file=os.path.join(tmp, "user_context.json")
            )
            index = MemoryIndex(os.path.join(tmp, "memory.db"))
            manager.record_fact("favorite_drink", "coffee", source="user")
            index.index_fact("favorite_drink", "coffee", 0.8)
            index.index_conversation("I like coffee", "Noted", datetime.now().isoformat())

            with patch("memory.memory_index.get_memory_index", return_value=index), patch(
                "memory.conversation_history.get_conversation_history"
            ) as get_history:
                self.assertTrue(manager.delete_fact("favorite_drink", True))

            get_history.return_value.delete_containing.assert_called_once_with("coffee")
            self.assertFalse(index.search("favorite_drink"))
            self.assertFalse(index.search("coffee"))

    def test_delete_fact_keeps_conversations_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(
                context_file=os.path.join(tmp, "user_context.json")
            )
            index = MemoryIndex(os.path.join(tmp, "memory.db"))
            with patch("memory.memory_index.get_memory_index", return_value=index):
                manager.record_fact("favorite_drink", "coffee", source="user")
                index.index_conversation(
                    "I like coffee", "Noted", datetime.now().isoformat()
                )
                self.assertTrue(manager.delete_fact("favorite_drink"))

            self.assertTrue(index.search("coffee", kind="conversation"))

    def test_record_fact_enforces_limit_and_removes_trimmed_index_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(
                context_file=os.path.join(tmp, "user_context.json")
            )
            facts = {
                f"fact-{number}": {
                    "value": "oldneedle" if number == 0 else f"value-{number}",
                    "updated_at": f"2020-01-{(number % 28) + 1:02d}T00:00:{number:02d}",
                    "confidence": 0.8,
                }
                for number in range(150)
            }
            manager.context["facts"] = facts
            manager.context["fact_history"] = {"fact-0": [{"value": "oldneedle"}]}
            manager.save_context()
            self.test_index.index_fact("fact-0", "oldneedle", 0.8)

            self.assertTrue(manager.record_fact("new-fact", "new-value"))

            self.assertEqual(len(manager.context["facts"]), 150)
            with open(manager.context_file, "r", encoding="utf-8") as handle:
                self.assertEqual(len(json.load(handle)["facts"]), 150)
            self.assertNotIn("fact-0", manager.context["facts"])
            self.assertNotIn("fact-0", manager.context["fact_history"])
            self.assertFalse(self.test_index.search("oldneedle", kind="fact"))

    def test_optimize_memory_removes_expired_and_low_confidence_facts_from_fts(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(
                context_file=os.path.join(tmp, "user_context.json")
            )
            now = datetime.now()
            manager.context["facts"] = {
                "expired": {
                    "value": "stale fact",
                    "confidence": 0.9,
                    "base_confidence": 0.9,
                    "updated_at": now.isoformat(),
                    "expires_at": (now - timedelta(days=1)).isoformat(),
                },
                "weak": {
                    "value": "weak fact",
                    "confidence": 0.1,
                    "base_confidence": 0.1,
                    "updated_at": now.isoformat(),
                    "expires_at": None,
                },
                "kept": {
                    "value": "stable fact",
                    "confidence": 0.9,
                    "base_confidence": 0.9,
                    "updated_at": now.isoformat(),
                    "expires_at": None,
                },
            }
            index = MemoryIndex(os.path.join(tmp, "memory.db"))
            for key, fact in manager.context["facts"].items():
                index.index_fact(key, fact["value"], fact["confidence"])

            with patch("memory.memory_index.get_memory_index", return_value=index):
                manager.optimize_memory()

            self.assertFalse(index.search("stale", kind="fact"))
            self.assertFalse(index.search("weak", kind="fact"))
            self.assertTrue(index.search("stable", kind="fact"))

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

    def test_force_record_replaces_a_conflicting_user_fact(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(
                context_file=os.path.join(tmp, "user_context.json")
            )
            manager.record_fact("favorite_drink", "coffee", source="user", ttl_days=0)

            manager.record_fact(
                "favorite_drink", "tea", source="user", confidence=1.0,
                ttl_days=0, force=True,
            )

            fact = manager.context["facts"]["favorite_drink"]
            self.assertEqual(fact["value"], "tea")
            self.assertEqual(fact["source"], "user")
            self.assertEqual(fact["confidence"], 1.0)

    def test_failed_fact_save_restores_previous_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(
                context_file=os.path.join(tmp, "user_context.json")
            )
            manager.record_fact("favorite_drink", "coffee", source="user", ttl_days=0)

            with patch(
                "memory.user_context.write_text_atomic",
                side_effect=OSError("disk full"),
            ):
                self.assertFalse(
                    manager.record_fact(
                        "favorite_drink", "tea", source="user", confidence=1.0,
                        ttl_days=0, force=True,
                    )
                )

            self.assertEqual(
                manager.context["facts"]["favorite_drink"]["value"], "coffee"
            )
            self.assertEqual(
                manager.context["fact_history"]["favorite_drink"][-1]["value"],
                "coffee",
            )

    def test_fact_snapshot_is_detached_from_later_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(
                context_file=os.path.join(tmp, "user_context.json")
            )
            manager.record_fact("favorite_drink", "coffee")

            snapshot = manager.get_facts_snapshot()
            manager.record_fact("favorite_drink", "tea", force=True)

            self.assertEqual(snapshot["favorite_drink"]["value"], "coffee")

    def test_delete_fact_removes_history_and_fts_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(
                context_file=os.path.join(tmp, "user_context.json")
            )
            manager.record_fact("favorite_drink", "coffee", source="user")
            manager.context["fact_history"]["favorite_drink"] = [{"value": "coffee"}]

            with patch("memory.memory_index.get_memory_index") as get_index:
                get_index.return_value.delete_fact.return_value = True
                self.assertTrue(manager.delete_fact("favorite_drink"))

            get_index.return_value.delete_fact.assert_called_once_with("favorite_drink")
            self.assertNotIn("favorite_drink", manager.context["facts"])
            self.assertNotIn("favorite_drink", manager.context["fact_history"])

    def test_delete_fact_rejects_stale_confirmation_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(
                context_file=os.path.join(tmp, "user_context.json")
            )
            manager.record_fact("favorite_drink", "coffee", source="user")

            with patch("memory.memory_index.get_memory_index") as get_index:
                self.assertFalse(
                    manager.delete_fact("favorite_drink", expected_value="tea")
                )

            get_index.assert_not_called()
            self.assertIn("favorite_drink", manager.context["facts"])

    def test_delete_fact_restores_memory_when_context_save_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "user_context.json")
            manager = UserContextManager(context_file=path)
            manager.record_fact("favorite_drink", "coffee", source="user")

            index = Mock()
            with patch("memory.memory_index.get_memory_index", return_value=index):
                with patch(
                    "memory.user_context.write_text_atomic",
                    side_effect=OSError("disk full"),
                ):
                    self.assertFalse(manager.delete_fact("favorite_drink"))

            self.assertEqual(
                manager.context["facts"]["favorite_drink"]["value"], "coffee"
            )
            index.delete_fact.assert_called_once_with("favorite_drink")
            index.delete_conversations_containing.assert_not_called()

    def test_delete_fact_can_retry_after_fact_index_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(context_file=os.path.join(tmp, "context.json"))
            index = MemoryIndex(os.path.join(tmp, "memory.db"))
            manager.record_fact("drink", "coffee", source="user")
            index.index_fact("drink", "coffee", 1.0)
            with patch("memory.memory_index.get_memory_index", return_value=index), patch.object(
                index, "delete_fact", side_effect=RuntimeError("index unavailable")
            ):
                self.assertFalse(manager.delete_fact("drink"))
                self.assertIn("drink", manager.context["facts"])

            with patch("memory.memory_index.get_memory_index", return_value=index):
                self.assertTrue(manager.delete_fact("drink"))
            self.assertNotIn("drink", manager.context["facts"])
            self.assertFalse(index.search("coffee", kind="fact"))

    def test_delete_fact_save_failure_restores_source_after_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(context_file=os.path.join(tmp, "context.json"))
            index = MemoryIndex(os.path.join(tmp, "memory.db"))
            history = Mock()
            with patch("memory.memory_index.get_memory_index", return_value=index):
                manager.record_fact("drink", "coffee", source="user")
                index.index_conversation("coffee", "noted", datetime.now().isoformat())
                with (
                    patch("memory.conversation_history.get_conversation_history", return_value=history),
                    patch("memory.user_context.write_text_atomic", side_effect=OSError("disk full")),
                ):
                    self.assertFalse(manager.delete_fact("drink", delete_conversations=True))
                    history.delete_containing.assert_called_once_with("coffee")
            self.assertIn("drink", manager.context["facts"])
            self.assertFalse(index.search("coffee", kind="conversation"))

    def test_delete_fact_restores_history_when_conversation_write_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(context_file=os.path.join(tmp, "context.json"))
            manager.record_fact("drink", "tea", source="user")
            history = ConversationHistory.__new__(ConversationHistory)
            history.file_path = os.path.join(tmp, "history.json")
            history._lock = threading.RLock()
            history.active = [{"user": "I like tea.", "ai": "Noted"}]
            history.summaries = []
            before = list(history.active)
            with patch("memory.memory_index.get_memory_index"), patch(
                "memory.conversation_history.get_conversation_history", return_value=history
            ), patch(
                "memory.conversation_history.write_json_atomic",
                side_effect=OSError("disk full"),
            ):
                self.assertFalse(manager.delete_fact("drink", delete_conversations=True))
                self.assertEqual(history.active, before)

    def test_delete_fact_can_retry_after_conversation_file_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(context_file=os.path.join(tmp, "context.json"))
            manager.record_fact("drink", "tea", source="user")
            history = ConversationHistory.__new__(ConversationHistory)
            history.file_path = os.path.join(tmp, "history.json")
            history._lock = threading.RLock()
            history.active = [{"user": "I like tea", "ai": "Noted"}]
            history.summaries = []
            history._schedule_save = Mock()
            with patch("memory.memory_index.get_memory_index"), patch(
                "memory.conversation_history.get_conversation_history", return_value=history
            ), patch.object(history, "delete_containing", side_effect=OSError("disk full")):
                self.assertFalse(manager.delete_fact("drink", delete_conversations=True))
                self.assertIn("drink", manager.context["facts"])

            with patch("memory.memory_index.get_memory_index"), patch(
                "memory.conversation_history.get_conversation_history", return_value=history
            ):
                self.assertTrue(manager.delete_fact("drink", delete_conversations=True))
            self.assertEqual(history.active, [])
            self.assertNotIn("drink", manager.context["facts"])

    def test_delete_fact_can_retry_after_conversation_index_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(context_file=os.path.join(tmp, "context.json"))
            index = MemoryIndex(os.path.join(tmp, "memory.db"))
            history = ConversationHistory.__new__(ConversationHistory)
            history.file_path = os.path.join(tmp, "history.json")
            history._lock = threading.RLock()
            history.active = [{"user": "I like tea", "ai": "Noted"}]
            history.summaries = []
            history._schedule_save = Mock()
            manager.record_fact("drink", "tea", source="user")
            index.index_fact("drink", "tea", 1.0)
            index.index_conversation("I like tea", "Noted", datetime.now().isoformat())
            with patch("memory.memory_index.get_memory_index", return_value=index), patch(
                "memory.conversation_history.get_conversation_history", return_value=history
            ), patch.object(
                index, "delete_conversations_containing", side_effect=RuntimeError("index unavailable")
            ):
                self.assertFalse(manager.delete_fact("drink", delete_conversations=True))
                self.assertIn("drink", manager.context["facts"])

            with patch("memory.memory_index.get_memory_index", return_value=index), patch(
                "memory.conversation_history.get_conversation_history", return_value=history
            ):
                self.assertTrue(manager.delete_fact("drink", delete_conversations=True))
            self.assertNotIn("drink", manager.context["facts"])
            self.assertEqual(history.active, [])
            self.assertFalse(index.search("tea", kind="conversation"))

    def test_delete_preference_can_retry_after_index_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(context_file=os.path.join(tmp, "context.json"))
            manager.context["preferences"] = {"drink": {"coffee": 1}}
            index = MemoryIndex(os.path.join(tmp, "memory.db"))
            history = ConversationHistory.__new__(ConversationHistory)
            history.file_path = os.path.join(tmp, "history.json")
            history._lock = threading.RLock()
            history.active = [{"user": "I like coffee", "ai": "Noted"}]
            history.summaries = []
            history._schedule_save = Mock()
            index.index_fact(index.preference_key("drink", "coffee"), "coffee", 1.0)
            index.index_conversation("I like coffee", "Noted", datetime.now().isoformat())
            with patch("memory.memory_index.get_memory_index", return_value=index), patch(
                "memory.conversation_history.get_conversation_history", return_value=history
            ), patch.object(index, "delete_fact", side_effect=RuntimeError("index unavailable")):
                self.assertFalse(manager.delete_preference("drink", "coffee", True))
                self.assertIn("coffee", manager.context["preferences"]["drink"])

            with patch("memory.memory_index.get_memory_index", return_value=index), patch(
                "memory.conversation_history.get_conversation_history", return_value=history
            ):
                self.assertTrue(manager.delete_preference("drink", "coffee", True))
            self.assertNotIn("drink", manager.context["preferences"])
            self.assertEqual(history.active, [])
            self.assertFalse(index.search("coffee", kind="fact"))
            self.assertFalse(index.search("coffee", kind="conversation"))

    def test_record_preference_restores_bucket_when_save_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(context_file=os.path.join(tmp, "context.json"))
            manager.context["preferences"] = {"drink": {"tea": 2}}
            with patch("memory.user_context.write_text_atomic", side_effect=OSError("disk full")):
                self.assertFalse(manager.record_preference("drink", "coffee"))

            self.assertEqual(manager.context["preferences"]["drink"], {"tea": 2})

    def test_preference_index_keeps_values_separate_and_cleans_legacy_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserContextManager(context_file=os.path.join(tmp, "context.json"))
            index = MemoryIndex(os.path.join(tmp, "memory.db"))
            with patch("memory.memory_index.get_memory_index", return_value=index):
                index.index_fact("선호: drink", "old", 1.0)
                manager.record_preference("drink", "coffee")
                manager.record_preference("drink", "tea")
                self.assertTrue(index.search("coffee", kind="fact"))
                self.assertTrue(index.search("tea", kind="fact"))
                manager.delete_preference("drink", "coffee")

            self.assertFalse(index.search("coffee", kind="fact"))
            self.assertTrue(index.search("tea", kind="fact"))
            self.assertFalse(index.search("old", kind="fact"))

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

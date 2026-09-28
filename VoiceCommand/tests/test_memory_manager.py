import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from memory.fact_suggestions import FactSuggestionStore
from memory.memory_manager import MemoryManager
from memory.user_context import UserContextManager


class MemoryManagerTests(unittest.TestCase):
    def test_process_interaction_records_situation_after_conversation_save(self):
        events = []
        fake_context = Mock()
        fake_context.context = {"last_commands": []}
        fake_context.extract_topics.return_value = []
        fake_context.record_interaction.side_effect = lambda message: events.append(
            ("situation", message)
        )
        fake_index = Mock()
        fake_profile = Mock()

        with patch("memory.memory_manager.get_context_manager", return_value=fake_context):
            manager = MemoryManager()
        with patch(
            "memory.memory_manager.add_conversation",
            side_effect=lambda user, response: events.append(("saved", user, response)),
        ), patch("memory.memory_manager.get_memory_index", return_value=fake_index), patch(
            "memory.memory_manager.get_user_profile_engine", return_value=fake_profile
        ):
            manager.process_interaction("Great job", "Done")

        self.assertEqual(events[0], ("saved", "Great job", "Done"))
        self.assertEqual(events[1], ("situation", "Great job"))
        fake_context.record_interaction.assert_called_once_with("Great job")

    def test_process_interaction_counts_when_conversation_save_fails(self):
        fake_context = Mock()
        fake_context.context = {"last_commands": []}
        fake_context.extract_topics.return_value = []
        with patch("memory.memory_manager.get_context_manager", return_value=fake_context):
            manager = MemoryManager()
        with patch(
            "memory.memory_manager.add_conversation",
            side_effect=OSError("disk full"),
        ), patch(
            "memory.memory_manager.get_memory_index", return_value=Mock()
        ), patch("memory.memory_manager.get_user_profile_engine", return_value=Mock()):
            manager.process_interaction("hello", "hi")

        fake_context.record_interaction.assert_called_once_with("hello")

    def test_free_form_fact_is_not_duplicated_in_prompt(self):
        fake_context = SimpleNamespace(
            context={"facts": {"I like tea": {"value": "I like tea", "confidence": 1.0}}},
            extract_topics=lambda user_msg, ai_response: [],
        )
        with patch("memory.memory_manager.get_context_manager", return_value=fake_context):
            manager = MemoryManager()

        self.assertEqual(manager.get_top_facts_prompt(), "[기억하고 있는 사실]\n- I like tea")

    def test_get_top_facts_prompt_uses_highest_confidence_facts(self):
        fake_context = SimpleNamespace(
            context={
                "facts": {
                    "낮음": {"value": "1", "confidence": 0.2},
                    "높음": {"value": "2", "confidence": 0.9},
                    "중간": {"value": "3", "confidence": 0.5},
                }
            },
            extract_topics=lambda user_msg, ai_response: [],
        )

        with patch("memory.memory_manager.get_context_manager", return_value=fake_context):
            manager = MemoryManager()

        prompt = manager.get_top_facts_prompt(n=2)

        self.assertIn("- 높음: 2", prompt)
        self.assertIn("- 중간: 3", prompt)
        self.assertNotIn("- 낮음: 1", prompt)

    def test_get_memory_prompt_delegates_to_full_context_prompt(self):
        fake_context = SimpleNamespace(
            context={"facts": {}},
            extract_topics=lambda user_msg, ai_response: [],
            get_context_summary=lambda: "요약",
        )
        fake_profile_engine = SimpleNamespace(get_prompt_injection=lambda: "프로필")

        with patch("memory.memory_manager.get_context_manager", return_value=fake_context):
            with patch("memory.memory_manager.get_user_profile_engine", return_value=fake_profile_engine):
                manager = MemoryManager()
                prompt = manager.get_memory_prompt()

        self.assertIn("프로필", prompt)
        self.assertIn("요약", prompt)

    def test_full_context_prompt_keeps_minute_precision_by_default(self):
        fake_context = SimpleNamespace(
            context={"facts": {}},
            extract_topics=lambda user_msg, ai_response: [],
            get_context_summary=lambda: "요약",
        )
        fixed_now = datetime(2026, 9, 29, 12, 34, 56)

        with patch("memory.memory_manager.datetime") as mock_datetime:
            mock_datetime.now.return_value = fixed_now
            with patch("memory.memory_manager.get_context_manager", return_value=fake_context):
                manager = MemoryManager()
                prompt = manager.get_full_context_prompt()

        self.assertIn("현재 시간: 2026-09-29 12:34", prompt)
        self.assertNotIn("12:34:56", prompt)

    def test_full_context_prompt_can_return_only_dynamic_summary(self):
        fake_context = SimpleNamespace(
            context={"facts": {}},
            extract_topics=lambda user_msg, ai_response: [],
            get_context_summary=lambda: "요약",
        )
        fake_profile_engine = SimpleNamespace(get_prompt_injection=lambda: "프로필")

        with patch("memory.memory_manager.get_context_manager", return_value=fake_context):
            with patch(
                "memory.memory_manager.get_user_profile_engine",
                return_value=fake_profile_engine,
            ):
                manager = MemoryManager()
                with patch.object(manager, "get_top_facts_prompt", return_value="사실"):
                    prompt = manager.get_full_context_prompt(
                        include_profile=False,
                        include_facts=False,
                        include_time=False,
                    )

        self.assertEqual(prompt, "요약")

    def test_ephemeral_fact_keys_match_whole_normalized_keys(self):
        manager = MemoryManager.__new__(MemoryManager)

        self.assertFalse(manager._is_persistent_fact(" CURRENT "))
        self.assertFalse(manager._is_persistent_fact("今日"))
        self.assertTrue(manager._is_persistent_fact("수면시간"))
        self.assertTrue(manager._is_persistent_fact("작업환경"))

    def test_tool_result_turn_does_not_apply_bio_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = UserContextManager(
                context_file=f"{tmp}/user_context.json"
            )
            context.update_bio("name", "Min")
            manager = MemoryManager.__new__(MemoryManager)
            manager.context_manager = context

            manager._extract_info_from_response(
                "[BIO: name=Mina]",
                user_message="웹에서 이름을 찾아줘",
                contains_tool_result=True,
            )

            self.assertEqual(context.context["user_bio"]["name"], "Min")
            self.assertEqual(context.context["pending_bio"], [])

    def test_bio_tags_wait_for_user_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = UserContextManager(
                context_file=f"{tmp}/user_context.json"
            )
            context.update_bio("name", "Min")
            manager = MemoryManager.__new__(MemoryManager)
            manager.context_manager = context

            manager._extract_info_from_response(
                "[BIO: name=Mina]", user_message="다른 질문"
            )
            self.assertEqual(context.context["user_bio"]["name"], "Min")
            self.assertEqual(len(context.context["pending_bio"]), 1)

            manager._extract_info_from_response(
                "[BIO: name=Mina]", user_message="내 이름은 Mina야"
            )
            self.assertEqual(context.context["user_bio"]["name"], "Mina")
            self.assertEqual(context.context["pending_bio"], [])

    def test_extracted_facts_and_preferences_wait_for_approval(self):
        user_message = "저는 Mina이고, 주말에는 하이킹을 좋아해요."
        payload = (
            '{"facts":[{"key":"직장","value":"게임 회사",'
            '"kind":"stable","evidence":"저는 Mina이고",'
            '"confidence":0.9}],"preferences":[{"category":"취미",'
            '"value":"하이킹","evidence":"주말에는 하이킹을 좋아해요."}],'
            '"bio":[{"field":"name","value":"Mina",'
            '"evidence":"저는 Mina이고"}]}'
        )
        with tempfile.TemporaryDirectory() as tmp:
            context = UserContextManager(context_file=f"{tmp}/user_context.json")
            store = FactSuggestionStore(f"{tmp}/fact_suggestions.json")
            manager = MemoryManager.__new__(MemoryManager)
            manager.context_manager = context

            with patch(
                "memory.memory_manager.get_fact_suggestion_store",
                return_value=store,
            ):
                manager._extract_fact_suggestions(user_message, lambda _text: payload)

            self.assertEqual(context.context["facts"], {})
            self.assertEqual(context.context["preferences"], {})
            self.assertEqual(len(store.get_suggestions()), 2)
            self.assertEqual(context.context["user_bio"]["name"], "사용자")
            self.assertEqual(
                context.context["pending_bio"],
                [{"field": "name", "value": "Mina"}],
            )

    def test_invalid_evidence_and_sensitive_candidates_are_dropped(self):
        user_message = "나는 요리를 좋아하고 계좌번호 12345678901234를 쓴다."
        payload = (
            '{"facts":[{"key":"취미","value":"독서","kind":"stable",'
            '"evidence":"원문에 없는 말","confidence":0.9}],'
            '"preferences":[{"category":"계좌","value":"12345678901234",'
            '"evidence":"계좌번호 12345678901234"}],"bio":[]}'
        )
        with tempfile.TemporaryDirectory() as tmp:
            manager = MemoryManager.__new__(MemoryManager)
            manager.context_manager = Mock()
            store = FactSuggestionStore(f"{tmp}/fact_suggestions.json")
            with patch(
                "memory.memory_manager.get_fact_suggestion_store",
                return_value=store,
            ):
                manager._extract_fact_suggestions(user_message, lambda _text: payload)

            self.assertEqual(store.get_suggestions(), [])

    def test_suggestion_extraction_runs_in_background_after_local_checks(self):
        extractor = Mock(return_value="{}")
        with patch("memory.memory_manager.ConfigManager.get", return_value=True), patch(
            "memory.memory_manager.threading.Thread"
        ) as thread:
            manager = MemoryManager.__new__(MemoryManager)
            manager.start_fact_suggestion_extraction(
                "나는 주말마다 음악을 듣는 걸 좋아해요.", extractor
            )

        thread.assert_called_once()
        thread.return_value.start.assert_called_once()
        self.assertEqual(
            thread.call_args.kwargs["args"][0],
            "나는 주말마다 음악을 듣는 걸 좋아해요.",
        )

    def test_suggestion_extraction_skips_short_sensitive_and_memory_commands(self):
        extractor = Mock()
        manager = MemoryManager.__new__(MemoryManager)
        with patch("memory.memory_manager.ConfigManager.get", return_value=True), patch(
            "memory.memory_manager.threading.Thread"
        ) as thread:
            manager.start_fact_suggestion_extraction("나는 음악 좋아", extractor)
            manager.start_fact_suggestion_extraction(
                "저는 건강 진단 결과가 있어요.", extractor
            )
            manager.start_fact_suggestion_extraction(
                "기억해줘 나는 주말마다 음악을 듣는 걸 좋아해요.", extractor
            )

        thread.assert_not_called()
        extractor.assert_not_called()

    def test_tool_turn_extracts_only_the_user_utterance(self):
        user_message = "나는 주말마다 음악을 듣는 걸 좋아해요."
        extractor = Mock()
        manager = MemoryManager.__new__(MemoryManager)
        manager.context_manager = Mock()
        manager.context_manager.context = {"last_commands": []}
        with (
            patch("memory.memory_manager.ConfigManager.get", return_value=True),
            patch("memory.memory_manager.threading.Thread") as thread,
            patch("memory.memory_manager.add_conversation"),
            patch("memory.memory_manager.get_memory_index"),
            patch("memory.memory_manager.get_user_profile_engine"),
            patch.object(manager, "_extract_info_from_response"),
            patch.object(manager, "_extract_topics", return_value=[]),
        ):
            manager.process_interaction(
                user_message,
                "검색 결과의 건강 진단 본문",
                contains_tool_result=True,
                memory_extractor=extractor,
            )

        thread.assert_called_once()
        self.assertEqual(
            thread.call_args.kwargs["args"],
            (user_message, extractor),
        )

    def test_approved_facts_use_kind_ttl_source_and_fts(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = UserContextManager(context_file=f"{tmp}/user_context.json")
            store = FactSuggestionStore(f"{tmp}/fact_suggestions.json")
            manager = MemoryManager.__new__(MemoryManager)
            manager.context_manager = context
            index = Mock()
            expected_days = {"state": 1, "plan": 30, "stable": 180}

            for kind, ttl_days in expected_days.items():
                store.add_suggestions([{
                    "type": "fact",
                    "key": kind,
                    "value": f"{kind} value",
                    "kind": kind,
                    "evidence": "user said this",
                    "confidence": 0.9,
                }])
                suggestion = store.get_suggestions()[-1]
                with patch(
                    "memory.memory_manager.get_fact_suggestion_store",
                    return_value=store,
                ), patch(
                    "memory.memory_manager.get_memory_index",
                    return_value=index,
                ):
                    self.assertTrue(
                        manager.approve_fact_suggestion(suggestion["id"])
                    )
                fact = context.context["facts"][kind]
                self.assertEqual(fact["source"], "user_utterance")
                self.assertAlmostEqual(
                    (
                        datetime.fromisoformat(fact["expires_at"])
                        - datetime.fromisoformat(fact["updated_at"])
                    ).total_seconds(),
                    ttl_days * 86400,
                    delta=1,
                )

            self.assertEqual(index.index_fact.call_count, 3)
            self.assertEqual(store.get_stats(), {"approved": 3, "rejected": 0})

    def test_approved_preferences_update_context_and_fts(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = UserContextManager(context_file=f"{tmp}/user_context.json")
            store = FactSuggestionStore(f"{tmp}/fact_suggestions.json")
            manager = MemoryManager.__new__(MemoryManager)
            manager.context_manager = context
            store.add_suggestions([{
                "type": "preference",
                "key": "응답 길이",
                "value": "짧게",
                "kind": "",
                "evidence": "I prefer short replies.",
                "confidence": 0.8,
            }])
            suggestion = store.get_suggestions()[0]
            index = Mock()

            with patch(
                "memory.memory_manager.get_fact_suggestion_store",
                return_value=store,
            ), patch(
                "memory.memory_manager.get_memory_index",
                return_value=index,
            ):
                self.assertTrue(manager.approve_fact_suggestion(suggestion["id"]))

            self.assertEqual(
                context.context["preferences"]["응답 길이"]["짧게"],
                1,
            )
            index.index_fact.assert_called_once_with("선호: 응답 길이", "짧게", 0.8)


if __name__ == "__main__":
    unittest.main()

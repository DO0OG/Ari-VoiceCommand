import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

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


if __name__ == "__main__":
    unittest.main()

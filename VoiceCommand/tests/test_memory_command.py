import unittest
from unittest.mock import Mock, patch

from commands.memory_command import MemoryCommand, _parse_explicit_command


class MemoryCommandTests(unittest.TestCase):
    def test_remember_and_forget_forms_match_in_three_languages(self):
        command = MemoryCommand(lambda _message: None)
        commands = {
            "기억해: 취미=등산": ("remember", "취미=등산"),
            "remember this: favorite=tea": ("remember", "favorite=tea"),
            "remember: favorite=tea": ("remember", "favorite=tea"),
            "これを覚えておいて: 好きな飲み物=お茶": (
                "remember",
                "好きな飲み物=お茶",
            ),
            "覚えて: 好きな飲み物=お茶": ("remember", "好きな飲み物=お茶"),
            "favorite tea 잊어줘": ("forget", "favorite tea"),
            "favorite tea는 잊어줘": ("forget", "favorite tea"),
            "forget favorite tea": ("forget", "favorite tea"),
            "forget about favorite tea": ("forget", "favorite tea"),
            "お茶を忘れて": ("forget", "お茶"),
            "お茶のことを忘れて": ("forget", "お茶"),
            "방금 거 잊어": ("forget_recent", ""),
            "forget that": ("forget_recent", ""),
            "今のを忘れて": ("forget_recent", ""),
        }
        for text, expected in commands.items():
            with self.subTest(text=text):
                self.assertEqual(_parse_explicit_command(text), expected)
                self.assertTrue(command.matches(text))

    def test_remember_records_and_indexes_explicit_fact(self):
        context = Mock()
        memory_index = Mock()
        spoken = []
        command = MemoryCommand(spoken.append)

        with patch("memory.user_context.get_context_manager", return_value=context), patch(
            "memory.memory_index.get_memory_index", return_value=memory_index
        ):
            command.execute("remember: favorite drink=tea")

        context.record_fact.assert_called_once_with(
            "favorite drink", "tea", source="user", confidence=1.0,
            ttl_days=0, force=True,
        )
        memory_index.index_fact.assert_called_once_with("favorite drink", "tea", 1.0)
        self.assertEqual(spoken, ["기억했어요: tea"])

    def test_remember_rejects_card_resident_id_and_ssn_numbers(self):
        sensitive_commands = (
            "기억해: 카드 4111 1111 1111 1111",
            "기억해: 주민번호 900101-1234567",
            "기억해: SSN 123-45-6789",
            "기억해: 건강 진단=불안증",
        )
        for text in sensitive_commands:
            with self.subTest(text=text):
                context = Mock()
                memory_index = Mock()
                spoken = []
                command = MemoryCommand(spoken.append)
                with patch(
                    "memory.user_context.get_context_manager", return_value=context
                ), patch(
                    "memory.memory_index.get_memory_index", return_value=memory_index
                ):
                    command.execute(text)

                context.record_fact.assert_not_called()
                memory_index.index_fact.assert_not_called()
                self.assertEqual(spoken, ["민감 정보는 저장하지 않아요."])

    def test_remember_reports_context_save_failure(self):
        context = Mock()
        context.record_fact.return_value = False
        memory_index = Mock()
        spoken = []
        command = MemoryCommand(spoken.append)

        with patch("memory.user_context.get_context_manager", return_value=context), patch(
            "memory.memory_index.get_memory_index", return_value=memory_index
        ):
            command.execute("remember: favorite=tea")

        memory_index.index_fact.assert_not_called()
        self.assertEqual(spoken, ["기억을 저장하지 못했어요."])

    def test_empty_remember_and_forget_prompt_for_content(self):
        spoken = []
        command = MemoryCommand(spoken.append)

        with patch("memory.conversation_history.get_conversation_history") as get_history:
            get_history.return_value.get_recent.return_value = []
            command.execute("기억해:")
            command.execute("이거 기억해 둬")
            command.execute("remember this.")
            command.execute("これを覚えておいて")
            command.execute("forget")

        self.assertEqual(
            spoken,
            [
                "무엇을 기억할까요?",
                "무엇을 기억할까요?",
                "무엇을 기억할까요?",
                "무엇을 기억할까요?",
                "무엇을 잊을까요?",
            ],
        )

    def test_empty_remember_saves_previous_user_utterance(self):
        context = Mock()
        memory_index = Mock()
        history = Mock()
        history.get_recent.return_value = [{"user": "I prefer green tea."}]
        spoken = []
        command = MemoryCommand(spoken.append)

        with patch(
            "memory.conversation_history.get_conversation_history",
            return_value=history,
        ), patch(
            "memory.user_context.get_context_manager", return_value=context
        ), patch("memory.memory_index.get_memory_index", return_value=memory_index):
            command.execute("remember this")

        context.record_fact.assert_called_once_with(
            "I prefer green tea.", "I prefer green tea.", source="user",
            confidence=1.0, ttl_days=0, force=True,
        )
        memory_index.index_fact.assert_called_once_with(
            "I prefer green tea.", "I prefer green tea.", 1.0
        )
        self.assertEqual(spoken, ["기억했어요: I prefer green tea."])

    def test_forget_prefers_exact_matches_and_confirms_before_deleting(self):
        context = Mock()
        context.get_facts_snapshot.return_value = {
            "favorite tea": {"value": "green tea"},
            "drink": {"value": "tea"},
        }
        spoken = []
        command = MemoryCommand(spoken.append)
        with patch("memory.user_context.get_context_manager", return_value=context), patch(
            "agent.confirmation_manager.get_confirmation_manager"
        ) as get_manager:
            get_manager.return_value.request_confirmation.return_value = True
            command.execute("forget tea")

        get_manager.return_value.request_confirmation.assert_called_once()
        context.delete_fact.assert_called_once_with("drink", expected_value="tea")
        self.assertEqual(spoken, ["기억을 잊었어요: drink"])

    def test_ambiguous_forget_lists_matches_without_deleting(self):
        context = Mock()
        context.get_facts_snapshot.return_value = {
            "favorite coffee": {"value": "iced coffee"},
            "coffee shop": {"value": "near home"},
        }
        spoken = []
        command = MemoryCommand(spoken.append)

        with patch("memory.user_context.get_context_manager", return_value=context):
            command.execute("forget coffee")

        context.delete_fact.assert_not_called()
        self.assertEqual(
            spoken,
            [
                "여러 기억이 있어요: favorite coffee: iced coffee, coffee shop: near home. "
                "어떤 기억인지 골라 주세요."
            ],
        )

    def test_recent_alias_targets_latest_updated_fact(self):
        context = Mock()
        context.get_facts_snapshot.return_value = {
            "older user fact": {
                "source": "user",
                "updated_at": "2026-09-28T10:00:00",
                "value": "old",
            },
            "latest user fact": {
                "source": "user",
                "updated_at": "2026-09-29T10:00:00",
                "value": "latest",
            },
            "assistant fact": {
                "source": "assistant",
                "updated_at": "2026-09-29T11:00:00",
                "value": "latest fact",
            },
        }
        command = MemoryCommand(lambda _message: None)
        with patch("memory.user_context.get_context_manager", return_value=context), patch(
            "agent.confirmation_manager.get_confirmation_manager"
        ) as get_manager:
            get_manager.return_value.request_confirmation.return_value = True
            command.execute("방금 거 잊어")

        context.delete_fact.assert_called_once_with(
            "assistant fact", expected_value="latest fact"
        )

    def test_confirmation_failure_keeps_fact(self):
        context = Mock()
        context.get_facts_snapshot.return_value = {
            "hobby": {"value": "hiking"}
        }
        spoken = []
        command = MemoryCommand(spoken.append)
        with patch("memory.user_context.get_context_manager", return_value=context), patch(
            "agent.confirmation_manager.get_confirmation_manager"
        ) as get_manager:
            get_manager.return_value.request_confirmation.side_effect = RuntimeError(
                "confirmation unavailable"
            )
            command.execute("hobby 잊어줘")

        context.delete_fact.assert_not_called()
        self.assertEqual(spoken, ["삭제를 취소했어요."])


if __name__ == "__main__":
    unittest.main()

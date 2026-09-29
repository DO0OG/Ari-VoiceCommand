import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from i18n.translator import _
from memory.memory_consolidator import MemoryConsolidator


class FakeMemoryIndex:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.index_digest = Mock(side_effect=self._index_digest)
        self.prune_digests_older_than = Mock()

    def search_by_date(self, start, end):
        return [
            row for row in self.rows
            if start <= datetime.fromisoformat(row.timestamp) <= end
        ]

    def _index_digest(self, digest_date, content):
        day = (
            digest_date.isoformat()
            if isinstance(digest_date, date)
            else str(digest_date)
        )
        if any(
            row.entry_type == "digest"
            and row.timestamp.startswith(day)
            for row in self.rows
        ):
            return False
        self.rows.append(
            SimpleNamespace(
                entry_type="digest",
                content=content,
                timestamp=f"{day}T00:00:00",
            )
        )
        return True


class MemoryConsolidatorTests(unittest.TestCase):
    def test_daily_digest_collects_available_sources_and_runs_once_per_date(self):
        target_day = date(2026, 1, 2)
        timestamp = f"{target_day.isoformat()}T12:00:00"
        indexed_conversation = (
            "\uC0AC\uC6A9\uC790: same question\n"
            "\uC544\uB9AC: same answer"
        )
        memory_index = FakeMemoryIndex([
            SimpleNamespace(
                entry_type="conversation",
                content=indexed_conversation,
                timestamp=timestamp,
            ),
            SimpleNamespace(
                entry_type="fact",
                content="ignored fact",
                timestamp=timestamp,
            ),
        ])
        history = SimpleNamespace(active=[
            {
                "timestamp": timestamp,
                "user": "same question",
                "ai": "same answer",
            },
            {
                "timestamp": timestamp,
                "user": "unique question",
                "ai": "unique answer",
            },
            {
                "timestamp": timestamp,
                "user": "medical diagnosis",
                "ai": "sensitive detail",
            },
            {
                "timestamp": "2026-01-01T12:00:00",
                "user": "older question",
                "ai": "older answer",
            },
        ])
        episode = SimpleNamespace(
            timestamp=timestamp,
            achieved=True,
            goal="episode goal",
            summary="episode summary",
            failure_kind="",
            state_change_summary="state changed",
            policy_summary="policy",
        )
        episode_memory = SimpleNamespace(
            get_recent_episodes=Mock(return_value=[episode])
        )
        context = SimpleNamespace(context={"last_commands": [
            {"timestamp": timestamp, "command": "open app", "params": "notes"},
            {
                "timestamp": "2026-01-01T12:00:00",
                "command": "older command",
                "params": "",
            },
        ]})
        task_runs = [
            {
                "finished_at": timestamp,
                "goal": "scheduled goal",
                "summary": "backup complete",
                "success": True,
            },
            {
                "finished_at": "2026-01-01T12:00:00",
                "goal": "older task",
                "summary": "ignored run",
                "success": False,
            },
        ]
        scheduler = SimpleNamespace(get_task_runs=Mock(return_value=task_runs))
        provider = SimpleNamespace(
            _has_any_client=Mock(return_value=True),
            # 번역 함수는 아래에서 원문을 돌려주도록 고정하므로 응답도 원문 표식을 쓴다.
            chat=Mock(return_value="Summary. Keywords: notes, backup"),
        )

        with patch("memory.memory_index.get_memory_index", return_value=memory_index), \
                patch(
                    "memory.conversation_history.get_conversation_history",
                    return_value=history,
                ), patch(
                    "agent.episode_memory.get_episode_memory",
                    return_value=episode_memory,
                ), patch(
                    "memory.user_context.get_context_manager",
                    return_value=context,
                ), patch(
                    "agent.proactive_scheduler.get_scheduler",
                    return_value=scheduler,
                ), patch(
                    "agent.llm_provider.get_llm_provider",
                    return_value=provider,
                ), patch(
                    "i18n.translator._", side_effect=lambda message: message
                ), patch("i18n.translator.get_language", return_value="ja"):
            consolidator = MemoryConsolidator()

            self.assertTrue(consolidator.build_daily_digest(target_day))
            self.assertFalse(consolidator.build_daily_digest(target_day.isoformat()))

        episode_memory.get_recent_episodes.assert_called_once_with(limit=120)
        scheduler.get_task_runs.assert_called_once_with(
            since=datetime(2026, 1, 2),
            until=datetime(2026, 1, 2, 23, 59, 59, 999999),
            limit=1000,
        )
        self.assertEqual(memory_index.index_digest.call_count, 1)
        self.assertEqual(memory_index.index_digest.call_args.args[0], target_day)
        self.assertFalse(provider.chat.call_args.kwargs["include_history"])
        self.assertFalse(provider.chat.call_args.kwargs["save_history"])
        prompt = provider.chat.call_args.args[0]
        self.assertIn("2026-01-02", prompt)
        self.assertIn("ja", prompt.split("\n\n", 1)[0])
        self.assertEqual(prompt.count("same question"), 1)
        self.assertIn("unique question", prompt)
        self.assertIn("episode goal", prompt)
        self.assertIn("open app", prompt)
        self.assertIn("backup complete", prompt)
        self.assertNotIn("older question", prompt)
        self.assertNotIn("medical diagnosis", prompt)
        self.assertNotIn("older command", prompt)
        self.assertNotIn("ignored run", prompt)

    def test_sensitive_generated_digest_is_not_indexed(self):
        target_day = date(2026, 1, 2)
        timestamp = f"{target_day.isoformat()}T12:00:00"
        memory_index = FakeMemoryIndex()
        provider = SimpleNamespace(
            _has_any_client=Mock(return_value=True),
            chat=Mock(return_value=f"Medical diagnosis: private detail. {_('Keywords:')} health"),
        )

        with patch("memory.memory_index.get_memory_index", return_value=memory_index), \
                patch(
                    "memory.conversation_history.get_conversation_history",
                    return_value=SimpleNamespace(active=[{
                        "timestamp": timestamp,
                        "user": "safe conversation",
                        "ai": "safe response",
                    }]),
                ), patch(
                    "agent.episode_memory.get_episode_memory",
                    return_value=SimpleNamespace(
                        get_recent_episodes=Mock(return_value=[])
                    ),
                ), patch(
                    "memory.user_context.get_context_manager",
                    return_value=SimpleNamespace(context={"last_commands": []}),
                ), patch(
                    "agent.proactive_scheduler.get_scheduler",
                    return_value=SimpleNamespace(get_task_runs=Mock(return_value=[])),
                ), patch(
                    "agent.llm_provider.get_llm_provider",
                    return_value=provider,
                ):
            created = MemoryConsolidator().build_daily_digest(target_day)

        self.assertFalse(created)
        memory_index.index_digest.assert_not_called()

    def test_unavailable_provider_does_not_block_run_all_and_prunes_old_digests(self):
        yesterday = date.today() - timedelta(days=1)
        history = SimpleNamespace(active=[
            {
                "timestamp": f"{yesterday.isoformat()}T12:00:00",
                "user": "yesterday conversation",
                "ai": "response",
            }
        ])
        memory_index = FakeMemoryIndex()
        provider = SimpleNamespace(
            _has_any_client=Mock(return_value=False),
            chat=Mock(),
        )
        consolidator = MemoryConsolidator()

        with patch.object(consolidator, "consolidate_facts", return_value=2), \
                patch.object(consolidator, "consolidate_strategies", return_value=1), \
                patch.object(consolidator, "summarize_old_conversations", return_value=0), \
                patch.object(consolidator, "collect_insights", return_value={}), \
                patch("memory.memory_index.get_memory_index", return_value=memory_index), \
                patch(
                    "memory.conversation_history.get_conversation_history",
                    return_value=history,
                ), patch(
                    "agent.episode_memory.get_episode_memory",
                    return_value=SimpleNamespace(
                        get_recent_episodes=Mock(return_value=[])
                    ),
                ), patch(
                    "memory.user_context.get_context_manager",
                    return_value=SimpleNamespace(context={"last_commands": []}),
                ), patch(
                    "agent.proactive_scheduler.get_scheduler",
                    return_value=SimpleNamespace(get_task_runs=Mock(return_value=[])),
                ), patch(
                    "agent.llm_provider.get_llm_provider",
                    return_value=provider,
                ):
            result = consolidator.run_all()

        self.assertEqual(set(result), {"facts", "strategies", "conversations", "insights"})
        provider.chat.assert_not_called()
        memory_index.prune_digests_older_than.assert_called_once_with(days=90)


if __name__ == "__main__":
    unittest.main()

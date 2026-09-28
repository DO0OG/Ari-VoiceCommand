import os
import tempfile
import types
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from memory.fts_utils import build_fts_query
from memory.memory_index import MemoryIndex


class MemoryIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "memory.db")
        self.index = MemoryIndex(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_fts_query_quotes_tokens_and_escapes_quotes(self):
        self.assertEqual(
            build_fts_query('ari-voice say hel"lo'),
            r'"ari-voice" OR "say" OR "hel""lo"',
        )
        self.assertEqual(build_fts_query('"Ari"'), '"Ari"')

    def test_review_search_cases(self):
        self.index.index_conversation("내 프로젝트는 Ari야", "", "2026-09-29T10:00:00")
        self.index.index_conversation("今日は天気がいいですね", "", "2026-09-29T10:01:00")
        self.index.index_conversation("c++", "", "2026-09-29T10:02:00")
        self.index.index_conversation("ari-voice", "", "2026-09-29T10:03:00")

        self.assertIn("프로젝트는", self.index.search("프로젝트")[0].content)
        self.assertIn("今日は天気", self.index.search("天気")[0].content)
        self.assertIn("c++", self.index.search("c++")[0].content)
        self.assertIn("ari-voice", self.index.search("ari-voice")[0].content)

    def test_short_and_quoted_terms_use_safe_search(self):
        self.index.index_conversation('앱 이름은 "Ari"입니다', "", "2026-09-29T10:00:00")

        self.assertTrue(self.index.search('"앱"'))
        self.assertTrue(self.index.search("이름"))
        self.assertTrue(self.index.search('"Ari"'))

    def test_migration_preserves_legacy_rows_and_sets_user_version(self):
        with self.index._connect() as conn:
            conn.execute("DROP TABLE memory_entries")
            conn.execute(
                "CREATE VIRTUAL TABLE memory_entries "
                "USING fts5(entry_type, content, timestamp)"
            )
            conn.execute(
                "INSERT INTO memory_entries(rowid, entry_type, content, timestamp) "
                "VALUES (17, 'conversation', '내 프로젝트는 Ari야', '2026-09-28T10:00:00')"
            )
            conn.execute(
                "INSERT INTO memory_entries(rowid, entry_type, content, timestamp) "
                "VALUES (18, 'fact', 'favorite_drink: coffee (confidence=0.80)', "
                "'2026-09-28T10:01:00')"
            )
            conn.execute("PRAGMA user_version = 0")

        migrated = MemoryIndex(self.db_path)

        self.assertTrue(migrated.search("프로젝트"))
        with self.index._connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(memory_entries)")
            }
            row = conn.execute(
                "SELECT rowid, content FROM memory_entries WHERE rowid=17"
            ).fetchone()
        self.assertEqual(version, 1)
        self.assertTrue({"content", "entry_type", "timestamp", "ref_key"}.issubset(columns))
        self.assertEqual(row, (17, "내 프로젝트는 Ari야"))
        self.assertEqual(migrated.delete_fact("favorite_drink"), 1)

    def test_like_fallback_escapes_wildcards_and_matches_any_token(self):
        self.index._supports_trigram = False
        self.index.index_conversation(
            "literal 100%_complete", "", "2026-09-29T10:00:00"
        )
        self.index.index_conversation("beta result", "", "2026-09-29T10:01:00")
        self.index.index_conversation(
            "literal 100X_complete", "", "2026-09-29T10:02:00"
        )

        results = self.index.search("100%_complete beta")

        self.assertEqual(
            [result.content for result in results],
            [
                "사용자: beta result\n아리: ",
                "사용자: literal 100%_complete\n아리: ",
            ],
        )

    def test_indexing_same_fact_ten_times_keeps_one_row(self):
        for confidence in range(10):
            self.index.index_fact("favorite_drink", "coffee", confidence / 10)

        with self.index._connect() as conn:
            count = conn.execute(
                "SELECT count(*) FROM memory_entries "
                "WHERE entry_type='fact' AND ref_key='fact:favorite_drink'"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_fact_and_matching_conversations_can_be_deleted(self):
        self.index.index_fact("favorite_drink", "coffee", 0.8)
        self.index.index_conversation("I like COFFEE", "", "2026-09-29T10:00:00")
        self.index.index_conversation("I like tea", "", "2026-09-29T10:01:00")

        self.assertEqual(self.index.delete_fact("favorite_drink"), 1)
        self.assertEqual(self.index.delete_conversations_containing("coffee"), 1)
        with self.index._connect() as conn:
            rows = conn.execute(
                "SELECT entry_type, content FROM memory_entries"
            ).fetchall()
        self.assertEqual(rows, [("conversation", "사용자: I like tea\n아리: ")])

    def test_prune_removes_only_old_conversations(self):
        old = (datetime.now() - timedelta(days=181)).isoformat()
        recent = datetime.now().isoformat()
        self.index.index_conversation("old item", "", old)
        self.index.index_conversation("recent item", "", recent)
        self.index.index_fact("keep", "fact", 0.7)

        self.assertEqual(self.index.prune_conversations_older_than(180), 1)
        with self.index._connect() as conn:
            rows = conn.execute(
                "SELECT entry_type, content FROM memory_entries ORDER BY timestamp"
            ).fetchall()
        self.assertEqual(
            [row[1] for row in rows],
            [
                "사용자: recent item\n아리: ",
                "keep: fact (confidence=0.70)",
            ],
        )

    def test_rebuild_restores_conversations_and_facts(self):
        history = types.SimpleNamespace(
            active=[{
                "user": "내 프로젝트는 Ari야",
                "ai": "확인했어요",
                "timestamp": "2026-09-29T10:00:00",
            }],
            summaries=["이전 프로젝트 요약"],
        )
        context_manager = types.SimpleNamespace(
            context={
                "facts": {
                    "favorite_drink": {
                        "value": "coffee",
                        "confidence": 0.8,
                        "updated_at": "2026-09-29T10:01:00",
                    }
                }
            }
        )
        history_module = types.ModuleType("memory.conversation_history")
        history_module.get_conversation_history = lambda: history
        context_module = types.ModuleType("memory.user_context")
        context_module.get_context_manager = lambda: context_manager
        self.index.index_fact("stale", "remove me", 0.5)

        with patch.dict(
            "sys.modules",
            {
                "memory.conversation_history": history_module,
                "memory.user_context": context_module,
            },
        ):
            self.index.rebuild_index()

        self.assertTrue(self.index.search("프로젝트"))
        self.assertTrue(self.index.search("요약"))
        self.assertTrue(self.index.search("coffee"))
        self.assertEqual(self.index.delete_fact("stale"), 0)

    def test_sqlite_version_gates_trigram_and_unsupported_uses_like(self):
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = ("3.33.0",)
        self.assertFalse(self.index._probe_trigram(connection))
        connection.execute.assert_called_once_with("SELECT sqlite_version()")

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "no-trigram.db")
            with patch.object(MemoryIndex, "_probe_trigram", return_value=False):
                index = MemoryIndex(path)
            index.index_conversation("今日は天気がいいですね", "", "2026-09-29T10:00:00")

            self.assertFalse(index._supports_trigram)
            self.assertTrue(index.search("天気"))


if __name__ == "__main__":
    unittest.main()

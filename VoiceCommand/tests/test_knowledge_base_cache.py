import os
import tempfile
import unittest
from unittest.mock import patch

from memory.knowledge_base import KnowledgeBase


class KnowledgeBaseCacheTests(unittest.TestCase):
    def test_query_uses_like_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb = KnowledgeBase(os.path.join(tmp, "knowledge.db"))
            kb.upsert("user", "likes", "black tea")
            with kb._connect() as conn:
                conn.execute("DROP TABLE knowledge_fts")

            results = kb.query("black")

        self.assertEqual(results[0]["value"], "black tea")

    def test_empty_prompt_caches_row_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb = KnowledgeBase(os.path.join(tmp, "knowledge.db"))
            with patch.object(kb, "_connect", wraps=kb._connect) as connect:
                self.assertEqual(kb.prompt_for("something"), "")
                self.assertEqual(kb.prompt_for("another query"), "")

            self.assertEqual(connect.call_count, 1)

    def test_upsert_invalidates_empty_row_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb = KnowledgeBase(os.path.join(tmp, "knowledge.db"))
            self.assertEqual(kb.prompt_for("cake"), "")

            kb.upsert("user", "likes", "cake")

            self.assertIn("cake", kb.prompt_for("cake"))


if __name__ == "__main__":
    unittest.main()

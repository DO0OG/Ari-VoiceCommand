"""SQLite FTS 기반 메모리 검색."""
from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import List


@dataclass
class MemorySearchResult:
    entry_type: str
    content: str
    timestamp: str
    score: float


class MemoryIndex:
    def __init__(self):
        from core.resource_manager import ResourceManager
        self.db_path = ResourceManager.get_writable_path("ari_memory.db")
        self._ensure_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _ensure_db(self):
        with self._connect() as conn:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memory_entries USING fts5(entry_type, content, timestamp)"
            )

    def index_conversation(self, user_msg: str, ai_response: str, timestamp: str):
        content = f"사용자: {user_msg}\n아리: {ai_response}"
        self._insert("conversation", content, timestamp)

    def index_fact(self, key: str, value: str, confidence: float):
        content = f"{key}: {value} (confidence={confidence:.2f})"
        self._insert("fact", content, datetime.now().isoformat())

    def _insert(self, entry_type: str, content: str, timestamp: str):
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO memory_entries(entry_type, content, timestamp) VALUES (?, ?, ?)",
                    (entry_type, content, timestamp),
                )
        except Exception as e:
            logging.debug(f"[MemoryIndex] insert 실패: {e}")

    def search(self, query: str, limit: int = 5) -> List[MemorySearchResult]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT entry_type, content, timestamp, bm25(memory_entries) "
                    "FROM memory_entries WHERE memory_entries MATCH ? "
                    "ORDER BY bm25(memory_entries) LIMIT ?",
                    (query, limit),
                ).fetchall()
            return [
                MemorySearchResult(
                    entry_type=row[0],
                    content=row[1],
                    timestamp=row[2],
                    score=float(row[3]),
                )
                for row in rows
            ]
        except Exception as e:
            logging.debug(f"[MemoryIndex] search 실패: {e}")
            return []

    def search_by_date(self, start: datetime, end: datetime) -> List[MemorySearchResult]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT entry_type, content, timestamp, 0.0 FROM memory_entries "
                    "WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp DESC",
                    (start.isoformat(), end.isoformat()),
                ).fetchall()
            return [MemorySearchResult(*row) for row in rows]
        except Exception as e:
            logging.debug(f"[MemoryIndex] search_by_date 실패: {e}")
            return []

    def rebuild_index(self):
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM memory_entries")
        except Exception as e:
            logging.warning(f"[MemoryIndex] 초기화 실패: {e}")


_index: MemoryIndex | None = None
_index_lock = threading.Lock()


def get_memory_index() -> MemoryIndex:
    global _index
    if _index is None:
        with _index_lock:
            if _index is None:
                _index = MemoryIndex()
    return _index

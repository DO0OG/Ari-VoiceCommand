"""SQLite FTS 기반 메모리 검색."""
from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterator, List

from memory.fts_utils import build_fts_query, split_fts_tokens

_SCHEMA_VERSION = 1
_TRIGRAM_MIN_VERSION = (3, 34, 0)
_ENTRY_COLUMNS = {"content", "entry_type", "timestamp", "ref_key"}
_SEARCH_LIKE_SQL = (
    "SELECT entry_type, content, timestamp, 0.0 FROM memory_entries WHERE ("
    "content LIKE '%' || ? || '%' ESCAPE '\\' OR "
    "content LIKE '%' || ? || '%' ESCAPE '\\' OR "
    "content LIKE '%' || ? || '%' ESCAPE '\\' OR "
    "content LIKE '%' || ? || '%' ESCAPE '\\' OR "
    "content LIKE '%' || ? || '%' ESCAPE '\\' OR "
    "content LIKE '%' || ? || '%' ESCAPE '\\' OR "
    "content LIKE '%' || ? || '%' ESCAPE '\\' OR "
    "content LIKE '%' || ? || '%' ESCAPE '\\' OR "
    "content LIKE '%' || ? || '%' ESCAPE '\\' OR "
    "content LIKE '%' || ? || '%' ESCAPE '\\' OR "
    "content LIKE '%' || ? || '%' ESCAPE '\\' OR "
    "content LIKE '%' || ? || '%' ESCAPE '\\') "
    "AND (? IS NULL OR entry_type = ?) "
    "AND (? IS NULL OR timestamp >= ?) "
    "ORDER BY timestamp DESC LIMIT ?"
)


@dataclass
class MemorySearchResult:
    entry_type: str
    content: str
    timestamp: str
    score: float


class MemoryIndex:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            from core.resource_manager import ResourceManager

            db_path = ResourceManager.get_writable_path("ari_memory.db")
        self.db_path = db_path
        self._lock = threading.RLock()
        self._fts5_available = False
        self._supports_trigram = False
        self._ensure_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # sqlite3 연결의 with 문은 커밋만 하므로 연결은 따로 닫는다.
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _ensure_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._fts5_available = self._probe_fts5(conn)
            self._supports_trigram = self._probe_trigram(conn)
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='memory_entries'"
            ).fetchone()
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if row is None:
                self._create_entries_table(conn)
            else:
                schema = str(row[0] or "").lower()
                columns = {
                    str(column[1])
                    for column in conn.execute("PRAGMA table_info(memory_entries)")
                }
                current_trigram = "trigram" in schema
                needs_migration = (
                    version < _SCHEMA_VERSION
                    or not _ENTRY_COLUMNS.issubset(columns)
                    or current_trigram != self._supports_trigram
                )
                if needs_migration:
                    self._migrate_entries_table(conn)
                else:
                    self._fts5_available = "using fts5" in schema
            if version <= _SCHEMA_VERSION:
                conn.execute("PRAGMA user_version = 1")

    def _probe_fts5(self, conn: sqlite3.Connection) -> bool:
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE temp._memory_fts_probe USING fts5(content)"
            )
            conn.execute("DROP TABLE temp._memory_fts_probe")
            return True
        except sqlite3.Error:
            return False

    def _probe_trigram(self, conn: sqlite3.Connection) -> bool:
        try:
            version_row = conn.execute("SELECT sqlite_version()").fetchone()
            version = tuple(int(part) for part in str(version_row[0]).split(".")[:3])
        except (IndexError, sqlite3.Error, TypeError, ValueError):
            return False
        if version < _TRIGRAM_MIN_VERSION:
            return False
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE temp._memory_trigram_probe "
                "USING fts5(content, tokenize='trigram')"
            )
            conn.execute("DROP TABLE temp._memory_trigram_probe")
            return True
        except sqlite3.Error:
            return False

    def _create_entries_table(self, conn: sqlite3.Connection) -> None:
        if self._fts5_available:
            if self._supports_trigram:
                try:
                    conn.execute(
                        "CREATE VIRTUAL TABLE memory_entries USING fts5("
                        "content, entry_type UNINDEXED, timestamp UNINDEXED, "
                        "ref_key UNINDEXED, tokenize='trigram')"
                    )
                    return
                except sqlite3.Error as exc:
                    logging.debug("[MemoryIndex] trigram 생성 실패: %s", exc)
                    self._supports_trigram = False
            try:
                conn.execute(
                    "CREATE VIRTUAL TABLE memory_entries USING fts5("
                    "content, entry_type UNINDEXED, timestamp UNINDEXED, "
                    "ref_key UNINDEXED)"
                )
                return
            except sqlite3.Error as exc:
                logging.debug("[MemoryIndex] FTS5 생성 실패: %s", exc)
                self._fts5_available = False
        conn.execute(
            "CREATE TABLE memory_entries ("
            "content TEXT NOT NULL, entry_type TEXT NOT NULL, "
            "timestamp TEXT NOT NULL, ref_key TEXT NOT NULL DEFAULT '')"
        )

    def _migrate_entries_table(self, conn: sqlite3.Connection) -> None:
        old_columns = {
            str(column[1])
            for column in conn.execute("PRAGMA table_info(memory_entries)")
        }
        migrated_rows = []
        if {"entry_type", "content", "timestamp"}.issubset(old_columns):
            if "ref_key" in old_columns:
                rows = conn.execute(
                    "SELECT rowid, entry_type, content, timestamp, ref_key "
                    "FROM memory_entries"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT rowid, entry_type, content, timestamp, NULL AS ref_key "
                    "FROM memory_entries"
                ).fetchall()
            for row in rows:
                entry_type = str(row[1] or "")
                content = str(row[2] or "")
                ref_key = row[4] or ""
                if entry_type == "fact" and not ref_key:
                    legacy_key, separator, _ = content.partition(": ")
                    if separator and legacy_key:
                        ref_key = self._fact_ref_key(legacy_key)
                migrated_rows.append(
                    (
                        row[0],
                        content,
                        entry_type,
                        row[3],
                        ref_key,
                    )
                )
        conn.execute("DROP TABLE memory_entries")
        self._create_entries_table(conn)
        conn.executemany(
            "INSERT INTO memory_entries"
            "(rowid, content, entry_type, timestamp, ref_key) "
            "VALUES (?, ?, ?, ?, ?)",
            migrated_rows,
        )
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='memory_entries'"
        ).fetchone()
        schema = str(row[0] or "").lower() if row else ""
        self._fts5_available = "using fts5" in schema
        self._supports_trigram = "trigram" in schema

    def index_conversation(self, user_msg: str, ai_response: str, timestamp: str) -> None:
        content = f"사용자: {user_msg}\n아리: {ai_response}"
        self._insert("conversation", content, timestamp)

    def index_fact(self, key: str, value: str, confidence: float) -> None:
        fact_key = self._fact_ref_key(key)
        content = f"{key}: {value} (confidence={confidence:.2f})"
        timestamp = datetime.now().isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM memory_entries WHERE entry_type='fact' AND ref_key=?",
                (fact_key,),
            )
            conn.execute(
                "INSERT INTO memory_entries"
                "(entry_type, content, timestamp, ref_key) VALUES (?, ?, ?, ?)",
                ("fact", content, timestamp, fact_key),
            )

    def index_digest(self, digest_date: date, content: str) -> bool:
        text = str(content or "").strip()
        if not text:
            return False
        day = digest_date.date() if isinstance(digest_date, datetime) else digest_date
        ref_key = f"digest:{day.isoformat()}"
        timestamp = datetime.combine(day, datetime.min.time()).isoformat()
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM memory_entries WHERE entry_type='digest' "
                "AND ref_key=? LIMIT 1",
                (ref_key,),
            ).fetchone()
            if existing:
                return False
            conn.execute(
                "INSERT INTO memory_entries"
                "(entry_type, content, timestamp, ref_key) VALUES (?, ?, ?, ?)",
                ("digest", text, timestamp, ref_key),
            )
        return True

    def delete_fact(self, key: str) -> int:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM memory_entries WHERE entry_type='fact' AND ref_key=?",
                (self._fact_ref_key(key),),
            )
            return max(0, cursor.rowcount)

    def sync_facts(self, facts: dict) -> None:
        expected = {}
        for key, raw in (facts or {}).items():
            if isinstance(raw, dict):
                value = str(raw.get("value", "") or "")
                confidence = float(raw.get("confidence", 0.0))
            else:
                value = str(raw or "")
                confidence = 0.0
            if key and value:
                expected[self._fact_ref_key(str(key))] = (
                    value,
                    confidence,
                    f"{key}: {value} (confidence={confidence:.2f})",
                )

        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT rowid, ref_key, content FROM memory_entries "
                "WHERE entry_type='fact'"
            ).fetchall()
        indexed = {}
        stale_rowids = []
        for rowid, raw_ref_key, content in rows:
            ref_key = str(raw_ref_key or "")
            fact_key = ref_key.removeprefix("fact:")
            if ref_key not in expected and not fact_key.startswith("선호: "):
                stale_rowids.append((rowid,))
            else:
                indexed.setdefault(ref_key, []).append((rowid, str(content)))
        if stale_rowids:
            with self._lock, self._connect() as conn:
                conn.executemany(
                    "DELETE FROM memory_entries WHERE rowid=?", stale_rowids
                )
        for ref_key, (value, confidence, content) in expected.items():
            entries = indexed.get(ref_key, [])
            if len(entries) != 1 or entries[0][1] != content:
                key = ref_key[len("fact:"):]
                self.index_fact(key, value, confidence)

    def delete_conversations_containing(self, text: str) -> int:
        needle = str(text or "").casefold()
        if not needle:
            return 0
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT rowid, content FROM memory_entries "
                "WHERE entry_type='conversation'"
            ).fetchall()
            rowids = [
                (rowid,)
                for rowid, content in rows
                if needle in str(content or "").casefold()
            ]
            conn.executemany(
                "DELETE FROM memory_entries WHERE rowid=?",
                rowids,
            )
            return len(rowids)

    def prune_conversations_older_than(self, days: int) -> int:
        cutoff = datetime.now() - timedelta(days=max(0, int(days)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT rowid, timestamp FROM memory_entries "
                "WHERE entry_type='conversation'"
            ).fetchall()
            expired = []
            for rowid, raw_timestamp in rows:
                try:
                    timestamp = datetime.fromisoformat(str(raw_timestamp))
                    if timestamp.tzinfo is not None:
                        timestamp = timestamp.astimezone().replace(tzinfo=None)
                except (OverflowError, TypeError, ValueError):
                    continue
                if timestamp < cutoff:
                    expired.append((rowid,))
            conn.executemany(
                "DELETE FROM memory_entries WHERE rowid=?", expired
            )
            return len(expired)

    def prune_digests_older_than(self, days: int = 90) -> int:
        cutoff = datetime.now() - timedelta(days=max(0, int(days)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT rowid, timestamp FROM memory_entries "
                "WHERE entry_type='digest'"
            ).fetchall()
            expired = []
            for rowid, raw_timestamp in rows:
                try:
                    timestamp = datetime.fromisoformat(str(raw_timestamp))
                    if timestamp.tzinfo is not None:
                        timestamp = timestamp.astimezone().replace(tzinfo=None)
                except (OverflowError, TypeError, ValueError):
                    continue
                if timestamp < cutoff:
                    expired.append((rowid,))
            conn.executemany(
                "DELETE FROM memory_entries WHERE rowid=?", expired
            )
            return len(expired)

    def _insert(
        self,
        entry_type: str,
        content: str,
        timestamp: str,
        ref_key: str = "",
    ) -> None:
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "INSERT INTO memory_entries"
                    "(entry_type, content, timestamp, ref_key) VALUES (?, ?, ?, ?)",
                    (entry_type, content, timestamp, ref_key),
                )
        except sqlite3.Error as exc:
            logging.debug("[MemoryIndex] insert 실패: %s", exc)

    def search(
        self,
        query: str,
        limit: int = 5,
        kind: str | None = None,
        since: str | None = None,
    ) -> List[MemorySearchResult]:
        text = str(query or "").strip()
        tokens = split_fts_tokens(text)
        if not tokens or limit <= 0:
            return []
        entry_type = str(kind or "").strip() or None
        since_filter = None
        if since:
            try:
                since_value = datetime.fromisoformat(str(since).strip())
            except (TypeError, ValueError):
                return []
            if since_value.tzinfo is not None:
                since_value = since_value.astimezone().replace(tzinfo=None)
            since_filter = since_value.isoformat()
        use_like = not self._supports_trigram or any(len(token) < 3 for token in tokens)
        try:
            with self._lock, self._connect() as conn:
                if use_like:
                    rows = self._search_like(
                        conn, tokens, limit, entry_type, since_filter
                    )
                else:
                    try:
                        rows = conn.execute(
                            "SELECT entry_type, content, timestamp, bm25(memory_entries) "
                            "FROM memory_entries WHERE memory_entries MATCH ? "
                            "AND (? IS NULL OR entry_type = ?) "
                            "AND (? IS NULL OR timestamp >= ?) "
                            "ORDER BY bm25(memory_entries) LIMIT ?",
                            (
                                build_fts_query(text), entry_type, entry_type,
                                since_filter, since_filter, limit,
                            ),
                        ).fetchall()
                    except sqlite3.Error as exc:
                        logging.debug("[MemoryIndex] FTS 검색 실패, LIKE 폴백: %s", exc)
                        rows = self._search_like(
                            conn, tokens, limit, entry_type, since_filter
                        )
            return [MemorySearchResult(*row) for row in rows]
        except sqlite3.Error as exc:
            logging.debug("[MemoryIndex] search 실패: %s", exc)
            return []

    def _search_like(
        self,
        conn: sqlite3.Connection,
        tokens: list[str],
        limit: int,
        kind: str | None = None,
        since: str | None = None,
    ) -> list[tuple[str, str, str, float]]:
        patterns = tuple(self._escape_like(token) for token in tokens)
        parameters = (
            patterns + (None,) * (12 - len(patterns))
            + (kind, kind, since, since, limit)
        )
        rows = conn.execute(
            _SEARCH_LIKE_SQL,
            parameters,
        ).fetchall()
        return rows

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @staticmethod
    def _fact_ref_key(key: str) -> str:
        return f"fact:{key}"

    def search_by_date(self, start: datetime, end: datetime) -> List[MemorySearchResult]:
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    "SELECT entry_type, content, timestamp, 0.0 FROM memory_entries "
                    "WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp DESC",
                    (start.isoformat(), end.isoformat()),
                ).fetchall()
            return [MemorySearchResult(*row) for row in rows]
        except sqlite3.Error as exc:
            logging.debug("[MemoryIndex] search_by_date 실패: %s", exc)
            return []

    def rebuild_index(self) -> None:
        from memory.conversation_history import get_conversation_history
        from memory.user_context import get_context_manager

        history = get_conversation_history()
        context = get_context_manager().context
        conversations = list(getattr(history, "active", []))
        summaries = list(getattr(history, "summaries", []))
        facts = context.get("facts", {})
        now = datetime.now().isoformat()
        with self._lock, self._connect() as conn:
            digests = conn.execute(
                "SELECT entry_type, content, timestamp, ref_key "
                "FROM memory_entries WHERE entry_type='digest'"
            ).fetchall()
        rows = []
        for entry in conversations:
            user_msg = str(entry.get("user", "") or "")
            assistant_response = str(entry.get("ai", "") or "")
            if not user_msg and not assistant_response:
                continue
            content = f"사용자: {user_msg}\n아리: {assistant_response}"
            timestamp = str(entry.get("timestamp", now) or now)
            rows.append(("conversation", content, timestamp, ""))
        for summary in summaries:
            content = str(summary or "").strip()
            if content:
                rows.append(("conversation", content, now, ""))
        if isinstance(facts, dict):
            for key, raw_fact in facts.items():
                if isinstance(raw_fact, dict):
                    value = str(raw_fact.get("value", "") or "")
                    confidence = float(raw_fact.get("confidence", 0.0))
                    timestamp = str(raw_fact.get("updated_at", now) or now)
                else:
                    value = str(raw_fact or "")
                    confidence = 0.0
                    timestamp = now
                if not str(key) or not value:
                    continue
                content = f"{key}: {value} (confidence={confidence:.2f})"
                rows.append(("fact", content, timestamp, self._fact_ref_key(str(key))))
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM memory_entries")
            conn.executemany(
                "INSERT INTO memory_entries"
                "(entry_type, content, timestamp, ref_key) VALUES (?, ?, ?, ?)",
                rows + digests,
            )


_index: MemoryIndex | None = None
_index_lock = threading.Lock()


def get_memory_index() -> MemoryIndex:
    global _index
    if _index is None:
        with _index_lock:
            if _index is None:
                _index = MemoryIndex()
    return _index

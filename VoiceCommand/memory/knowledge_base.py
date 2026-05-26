"""구조화 지식 베이스 저장소.

대화에서 추출한 사실을 entity/relation/value 단위로 저장하고 FTS5로 조회한다.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)


class KnowledgeBase:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            from core.resource_manager import ResourceManager
            db_path = ResourceManager.get_runtime_path("knowledge_base.db")
        self.db_path = db_path
        self._lock = threading.RLock()
        self._ensure_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _ensure_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge (
                    id INTEGER PRIMARY KEY,
                    entity TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    source TEXT NOT NULL DEFAULT 'conversation',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(entity, relation, value)
                )
                """
            )
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(entity, relation, value)"
            )

    def upsert(
        self,
        entity: str,
        relation: str,
        value: str,
        confidence: float = 0.7,
        source: str = "conversation",
    ) -> int:
        entity = str(entity or "").strip()
        relation = str(relation or "").strip()
        value = str(value or "").strip()
        if not entity or not relation or not value:
            raise ValueError("entity, relation, value가 필요합니다.")
        confidence = max(0.0, min(1.0, float(confidence)))
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge(entity, relation, value, confidence, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity, relation, value) DO UPDATE SET
                    confidence=max(knowledge.confidence, excluded.confidence),
                    source=excluded.source,
                    updated_at=excluded.updated_at
                """,
                (entity, relation, value, confidence, source, now, now),
            )
            row = conn.execute(
                "SELECT id FROM knowledge WHERE entity=? AND relation=? AND value=?",
                (entity, relation, value),
            ).fetchone()
            knowledge_id = int(row[0])
            conn.execute("DELETE FROM knowledge_fts WHERE rowid=?", (knowledge_id,))
            conn.execute(
                "INSERT INTO knowledge_fts(rowid, entity, relation, value) VALUES (?, ?, ?, ?)",
                (knowledge_id, entity, relation, value),
            )
            return knowledge_id

    def query(self, text: str, top_k: int = 5) -> list[dict[str, Any]]:
        text = str(text or "").strip()
        if not text:
            return []
        safe_query = self._fts_query(text)
        with self._lock, self._connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT k.id, k.entity, k.relation, k.value, k.confidence, k.source,
                           k.created_at, k.updated_at, bm25(knowledge_fts) AS score
                    FROM knowledge_fts
                    JOIN knowledge k ON k.id = knowledge_fts.rowid
                    WHERE knowledge_fts MATCH ?
                    ORDER BY score LIMIT ?
                    """,
                    (safe_query, int(top_k)),
                ).fetchall()
            except sqlite3.Error as exc:
                log.debug("[KnowledgeBase] FTS 조회 실패, LIKE 폴백: %s", exc)
                like = f"%{text}%"
                rows = conn.execute(
                    """
                    SELECT id, entity, relation, value, confidence, source, created_at, updated_at, 0.0
                    FROM knowledge
                    WHERE entity LIKE ? OR relation LIKE ? OR value LIKE ?
                    ORDER BY updated_at DESC LIMIT ?
                    """,
                    (like, like, like, int(top_k)),
                ).fetchall()
        return [
            {
                "id": row[0],
                "entity": row[1],
                "relation": row[2],
                "value": row[3],
                "confidence": float(row[4]),
                "source": row[5],
                "created_at": row[6],
                "updated_at": row[7],
                "score": float(row[8]),
            }
            for row in rows
        ]

    def prompt_for(self, text: str, top_k: int = 3) -> str:
        facts = self.query(text, top_k=top_k)
        if not facts:
            return ""
        lines = ["[관련 지식]"]
        for fact in facts:
            lines.append(
                f"- {fact['entity']} {fact['relation']}: {fact['value']} "
                f"(신뢰도 {fact['confidence']:.2f})"
            )
        return "\n".join(lines)

    def extract_facts(self, conversation_turn: str) -> list[dict[str, Any]]:
        """가벼운 규칙 기반 사실 후보 추출."""
        text = str(conversation_turn or "").strip()
        if not text:
            return []
        facts: list[dict[str, Any]] = []
        for marker in ("좋아해", "선호", "작업 중", "사용 중", "이름은"):
            if marker in text:
                facts.append({
                    "entity": "사용자",
                    "relation": marker,
                    "value": text[:300],
                    "confidence": 0.55,
                    "source": "conversation",
                })
                break
        return facts

    @staticmethod
    def _fts_query(text: str) -> str:
        tokens = [token.strip('"\'`.,:;()[]{}') for token in text.split()]
        tokens = [token for token in tokens if token]
        if not tokens:
            return '""'
        return " OR ".join(f'"{token}"' for token in tokens[:12])


_instance: KnowledgeBase | None = None
_lock = threading.Lock()


def get_knowledge_base() -> KnowledgeBase:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = KnowledgeBase()
    return _instance

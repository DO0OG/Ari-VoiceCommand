"""
전략 기억 (Strategy Memory) — Phase 3.2 고도화
실패 원인 분석(Lesson)을 포함한 지능형 검색 및 전략 주입을 지원한다.
"""
import atexit
import hashlib
import io
import json
import logging
import os
import re
import threading
import uuid
from collections import Counter
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from typing import List, Optional

import numpy as np

from agent.tag_keywords import TAG_KEYWORDS as _TAG_KEYWORDS
from agent.execution_analysis import classify_failure_message, extract_workflow_hints
from core.atomic_io import write_bytes_atomic, write_json_atomic
from i18n.translator import _

def _get_memory_file() -> str:
    try:
        from core.resource_manager import ResourceManager
        return ResourceManager.get_writable_path("strategy_memory.json")
    except Exception:
        return os.path.join(os.path.dirname(__file__), "strategy_memory.json")

_MEMORY_FILE = _get_memory_file()
_MAX_RECORDS = 500

_TOKEN_STOPWORDS = {
    "해줘", "해주세요", "하고", "다음", "이후", "정리", "저장", "실행", "요청", "작업",
    "그리고", "해서", "한뒤", "후에", "대한", "관련", "위한", "the", "and", "for"
}

_NGRAM_SIZE = 3


@dataclass
class StrategyRecord:
    goal_summary: str
    tags: List[str]
    goal_tokens: List[str]
    steps_desc: List[str]
    success: bool
    error_summary: str
    failure_kind: str
    workflow_hints: List[str]
    lesson: str = ""           # Phase 3.2: 실패로부터 배운 교훈 (Self-Reflection)
    skill_id: str = ""
    user_feedback: str = ""
    few_shot_eligible: bool = False
    duration_ms: int = 0
    timestamp: str = ""
    embedding: List[float] = field(default_factory=list)
    record_id: str = field(default_factory=lambda: uuid.uuid4().hex)


class StrategyMemory:
    """과거 전략을 기억하고 현재 목표에 맞춤형 가이드를 제공한다."""

    def __init__(self, filepath: str = _MEMORY_FILE):
        self.filepath = filepath
        self.embedding_filepath = os.path.join(
            os.path.dirname(filepath) or ".", "strategy_embeddings.npy"
        )
        self._records: List[StrategyRecord] = []
        self._save_lock = threading.RLock()
        self._save_timer: Optional[threading.Timer] = None
        self._embedding_thread: Optional[threading.Thread] = None
        self._embedding_model_id = ""
        self._embedding_dim = 0
        self._embedding_valid = False
        self._save_delay_seconds = 5.0
        self._load()

    def record(self, goal: str, steps: list, success: bool, error: str = "", 
               duration_ms: int = 0, failure_kind: str = "", lesson: str = "",
               skill_id: str = "", user_feedback: str = "", few_shot_eligible: bool = False):
        rec = StrategyRecord(
            goal_summary=goal[:200],
            tags=self._extract_tags(goal),
            goal_tokens=sorted(list(self._extract_tokens(goal))),
            steps_desc=[getattr(s, "description_kr", str(s))[:100] for s in (steps or [])],
            success=success,
            error_summary=error[:200],
            failure_kind=failure_kind or self._classify_failure(error),
            workflow_hints=extract_workflow_hints(
                [
                    getattr(step, "content", "")
                    for step in (steps or [])
                ] + [
                    getattr(step, "description_kr", "")
                    for step in (steps or [])
                ]
            )[:5],
            lesson=lesson[:400],
            skill_id=skill_id[:80],
            user_feedback=user_feedback[:40],
            few_shot_eligible=bool(few_shot_eligible),
            duration_ms=duration_ms,
            timestamp=datetime.now().isoformat(),
            embedding=[],
        )
        embedder = None
        try:
            from agent.embedder import get_embedder
            embedder = get_embedder()
            vector = embedder.embed(rec.goal_summary)
            rec.embedding = (
                np.asarray(vector, dtype=np.float32).tolist()
                if vector is not None
                else []
            )
        except (ImportError, OSError, RuntimeError, TypeError, ValueError):
            rec.embedding = []
        with self._save_lock:
            empty_before = not self._records
            if embedder is not None and (
                self._embedding_model_id != embedder.model_id
                or self._embedding_dim != embedder.dim
            ):
                self._embedding_valid = False
            if rec.embedding and embedder is not None and len(rec.embedding) == embedder.dim:
                if empty_before or self._embedding_valid:
                    self._embedding_model_id = embedder.model_id
                    self._embedding_dim = embedder.dim
                    self._embedding_valid = True
            self._records.append(rec)
            self._prune()
            if not rec.embedding:
                self._embedding_valid = False
        self._schedule_save()
        if not self._embedding_valid:
            self._backfill_missing_embeddings()
        logging.info("[StrategyMemory] 저장됨: %s", '성공' if success else '실패')

    def get_relevant_context(self, goal: str) -> str:
        """현재 목표와 유사한 과거 사례를 분석하여 교훈과 함께 가이드 제공."""
        goal_tags = set(self._extract_tags(goal))
        goal_tokens = self._extract_tokens(goal)
        goal_ngrams = self._extract_ngrams(goal)

        scored = []
        for rec in self._records:
            tag_overlap = len(goal_tags & set(rec.tags))
            token_score = self._token_similarity(goal_tokens, set(rec.goal_tokens))
            ngram_score = self._ngram_similarity(goal_ngrams, self._extract_ngrams(rec.goal_summary))

            if tag_overlap == 0 and token_score < 0.1 and ngram_score < 0.2:
                continue
            
            exact_phrase_bonus = 20 if rec.goal_summary and rec.goal_summary[:30] in goal else 0
            failure_hint_bonus = 8 if (not rec.success and rec.lesson) else 0
            score = tag_overlap * 15 + token_score * 50 + ngram_score * 30
            score += exact_phrase_bonus + failure_hint_bonus
            if rec.success:
                score += 10
            
            recency = datetime.fromisoformat(rec.timestamp)
            days_diff = (datetime.now() - recency).days
            score += max(0, 20 - days_diff)
            scored.append((score, rec))

        relevant = [
            item[1]
            for item in sorted(scored, key=lambda item: item[0], reverse=True)[:3]
        ]
        if not relevant:
            return ""

        lines = [_("## 과거 유사 사례 및 교훈 (Planning Guide):")]
        for rec in relevant:
            status = _("성공") if rec.success else _("실패")
            lines.append(f"- [{status}] {rec.goal_summary[:100]}")
            if rec.lesson:
                lines.append(_("  💡 교훈: {lesson}").format(lesson=rec.lesson))
            elif not rec.success and rec.error_summary:
                lines.append(_("  ⚠️ 실패 이유: {error}").format(error=rec.error_summary[:100]))
            
            if rec.success and rec.steps_desc:
                lines.append(_("  ✅ 추천 접근: {steps}").format(steps=' -> '.join(rec.steps_desc[:3])))
                if rec.workflow_hints:
                    lines.append(_("  🧭 재사용 힌트: {hints}").format(hints=' | '.join(rec.workflow_hints[:2])))
            elif not rec.success and rec.failure_kind:
                lines.append(_("  🔎 실패 유형: {kind}").format(kind=rec.failure_kind))
        
        lines.append(_("\n※ 위 사례를 참고하여 동일한 실수를 피하고 검증된 방식을 사용하세요."))
        return "\n".join(lines)

    def search_similar_records(self, goal: str, limit: int = 3) -> List[StrategyRecord]:
        from agent.embedder import get_embedder

        embedder = get_embedder()
        with self._save_lock:
            records = list(self._records)
            if (
                self._embedding_model_id != embedder.model_id
                or self._embedding_dim != embedder.dim
            ):
                self._embedding_valid = False
            embedding_valid = self._embedding_valid
        if records and not embedding_valid:
            self._backfill_missing_embeddings()

        goal_tags = set(self._extract_tags(goal)) - {"일반"}
        goal_tokens = self._extract_tokens(goal)
        goal_ngrams = self._extract_ngrams(goal)
        goal_embedding = embedder.embed(goal) if embedding_valid else None
        manual_scores = []
        for index, rec in enumerate(records):
            tag_overlap = len(goal_tags & (set(rec.tags) - {"일반"}))
            token_score = self._token_similarity(goal_tokens, set(rec.goal_tokens))
            ngram_score = self._ngram_similarity(goal_ngrams, self._extract_ngrams(rec.goal_summary))
            manual_score = tag_overlap * 12 + token_score * 40 + ngram_score * 25
            manual_scores.append((index, manual_score))

        embedding_scores = {}
        if embedding_valid and goal_embedding is not None and records:
            vectors = np.asarray([rec.embedding for rec in records], dtype=np.float32)
            query = np.asarray(goal_embedding, dtype=np.float32)
            if vectors.shape == (len(records), embedder.dim) and query.shape == (embedder.dim,):
                norms = np.linalg.norm(vectors, axis=1) * float(np.linalg.norm(query))
                dots = vectors @ query
                similarities = np.divide(
                    dots,
                    norms,
                    out=np.zeros_like(dots),
                    where=norms > 0,
                )
                embedding_scores = {
                    index: float(score)
                    for index, score in enumerate(similarities)
                    if score > 0
                }

        rescored = []
        for index, manual_score in manual_scores:
            embedding_score = embedding_scores.get(index)
            if manual_score <= 0 and embedding_score is None:
                continue
            score = manual_score
            if embedding_score is not None:
                score = manual_score * 0.4 + embedding_score * 100 * 0.6
            rescored.append((score, records[index]))
        return [
            item[1]
            for item in sorted(rescored, key=lambda item: item[0], reverse=True)[:limit]
        ]

    def recent_failures(self, goal: str, limit: int = 3) -> List[str]:
        """현재 목표와 유사한 최근 실패 사례를 짧게 반환."""
        goal_tokens = self._extract_tokens(goal)
        goal_ngrams = self._extract_ngrams(goal)
        scored = []
        for rec in self._records:
            if rec.success:
                continue
            token_score = self._token_similarity(goal_tokens, set(rec.goal_tokens))
            ngram_score = self._ngram_similarity(goal_ngrams, self._extract_ngrams(rec.goal_summary))
            score = token_score * 0.5 + ngram_score * 0.2
            if rec.lesson:
                score += 0.05
            if score <= 0:
                continue
            scored.append((score, rec))

        failures = []
        for _score, rec in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]:
            reason = rec.lesson or rec.error_summary or rec.failure_kind or _("실패 기록")
            failures.append(f"{rec.goal_summary[:80]} -> {reason[:120]}")
        return failures

    def get_lessons_by_cause(self, root_cause: str, limit: int = 3) -> List[str]:
        normalized = str(root_cause or "").strip().lower()
        if not normalized:
            return []
        lessons: List[str] = []
        for rec in sorted(self._records, key=lambda item: item.timestamp or "", reverse=True):
            failure_kind = str(rec.failure_kind or self._classify_failure(rec.error_summary)).strip().lower()
            lesson = str(rec.lesson or "").strip()
            if rec.success or failure_kind != normalized or not lesson:
                continue
            if lesson not in lessons:
                lessons.append(lesson)
            if len(lessons) >= limit:
                break
        return lessons

    def update_latest_lesson(self, goal: str, lesson: str, failure_kind: str = "") -> bool:
        normalized_goal = str(goal or "")[:200]
        normalized_lesson = str(lesson or "").strip()[:400]
        normalized_failure_kind = str(failure_kind or "").strip()[:80]
        if not normalized_goal or not normalized_lesson:
            return False
        for record in reversed(self._records):
            if record.goal_summary != normalized_goal:
                continue
            if normalized_failure_kind and record.failure_kind and record.failure_kind != normalized_failure_kind:
                continue
            record.lesson = normalized_lesson
            if normalized_failure_kind and not record.failure_kind:
                record.failure_kind = normalized_failure_kind
            self._schedule_save()
            return True
        return False

    def get_stats(self, days: int = 7, offset: int = 0) -> dict:
        now = datetime.now()
        safe_days = max(int(days or 0), 0)
        safe_offset = max(int(offset or 0), 0)
        window_end = now - timedelta(days=safe_offset)
        window_start = window_end - timedelta(days=safe_days)
        records = [
            rec for rec in self._records
            # 상한을 <=로 포함한다. record() 직후 곧바로 get_stats()를 호출하면
            # 두 datetime.now() 호출이 (특히 해상도가 낮은 환경에서) 완전히
            # 같은 값을 반환할 수 있는데, 예전의 엄격한 < 비교는 그 경계에
            # 정확히 걸친 기록을 조용히 누락시켰다.
            if window_start <= self._parse_timestamp(rec.timestamp) <= window_end
        ]
        success_count = len([rec for rec in records if rec.success])
        fail_count = len(records) - success_count
        durations = [int(rec.duration_ms or 0) for rec in records if int(rec.duration_ms or 0) > 0]
        failure_counts = Counter(
            str(rec.failure_kind or self._classify_failure(rec.error_summary) or "execution_failed")
            for rec in records
            if not rec.success
        )
        return {
            "days": safe_days,
            "offset": safe_offset,
            "total": len(records),
            "success": success_count,
            "fail": fail_count,
            "success_rate": round((success_count / len(records)) if records else 0.0, 4),
            "avg_duration_ms": int(sum(durations) / len(durations)) if durations else 0,
            "top_failure_kinds": [
                {"failure_kind": kind, "count": count}
                for kind, count in failure_counts.most_common(5)
            ],
        }

    def get_repeated_failures(self, min_count: int = 3) -> List[tuple[str, int]]:
        threshold = max(int(min_count or 0), 1)
        counts = Counter(
            str(rec.failure_kind or self._classify_failure(rec.error_summary) or "execution_failed")
            for rec in self._records
            if not rec.success
        )
        return [
            (kind, count)
            for kind, count in counts.most_common()
            if count >= threshold
        ]

    def count(self) -> int:
        return len(self._records)

    # ── 내부 로직 ──────────────────────────────────────────────────────────────

    def _extract_tags(self, text: str) -> List[str]:
        tags = [tag for tag, words in _TAG_KEYWORDS.items() if any(w in text for w in words)]
        return tags or ["일반"]

    def _extract_tokens(self, text: str) -> set[str]:
        tokens = set()
        for token in re.findall(r"[가-힣A-Za-z][가-힣A-Za-z0-9_-]{1,20}", (text or "").lower()):
            if token in _TOKEN_STOPWORDS:
                continue
            tokens.add(token)
        return tokens

    def _token_similarity(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)

    def _extract_ngrams(self, text: str) -> set[str]:
        normalized = re.sub(r"\s+", "", (text or "").lower())
        if len(normalized) < _NGRAM_SIZE:
            return {normalized} if normalized else set()
        return {
            normalized[idx:idx + _NGRAM_SIZE]
            for idx in range(len(normalized) - _NGRAM_SIZE + 1)
        }

    def _ngram_similarity(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)

    def _prune(self):
        if len(self._records) <= _MAX_RECORDS:
            return
        now = datetime.now()
        scored = []
        for idx, record in enumerate(self._records):
            try:
                age_days = max((now - datetime.fromisoformat(record.timestamp)).days, 0)
            except Exception:
                age_days = 365
            score = 0.0
            if record.success:
                score += 6.0
            else:
                score -= 2.0
            if record.user_feedback == "positive":
                score += 4.0
            elif record.user_feedback == "negative":
                score -= 3.0
            if record.few_shot_eligible:
                score += 4.0
            if record.skill_id:
                score += 2.0
            if record.lesson:
                score += 1.5
            elif not record.success:
                score -= 1.5
            score -= min(age_days / 45.0, 8.0)
            scored.append((score, idx, record))
        kept = sorted(scored, key=lambda item: item[0], reverse=True)[:_MAX_RECORDS]
        self._records = [
            item[2] for item in sorted(kept, key=lambda item: item[1])
        ]

    def _load(self):
        from agent.embedder import get_embedder

        embedder = get_embedder()
        self._embedding_model_id = embedder.model_id
        self._embedding_dim = embedder.dim
        if not os.path.exists(self.filepath):
            self._embedding_valid = True
            return
        try:
            with open(self.filepath, encoding="utf-8") as handle:
                data = json.load(handle)
            legacy = isinstance(data, list)
            if legacy:
                raw_records = data
                stored_model_id = ""
                stored_dim = 0
                stored_ids = []
                stored_digest = ""
                complete = False
            elif isinstance(data, dict):
                raw_records = data.get("records", [])
                stored_model_id = str(data.get("embedding_model_id", ""))
                stored_dim = data.get("dim", 0)
                stored_ids = data.get("record_ids", [])
                stored_digest = str(data.get("embedding_sha256", ""))
                complete = data.get("embedding_complete") is True
            else:
                raise ValueError("지원하지 않는 전략 기억 형식입니다.")
            if not isinstance(raw_records, list) or any(
                not isinstance(record, dict) for record in raw_records
            ):
                raise ValueError("전략 기억 레코드 형식이 올바르지 않습니다.")
            self._records = [self._normalize_record(record) for record in raw_records]
            record_ids = [record.record_id for record in self._records]
            valid = (
                not legacy
                and complete
                and stored_model_id == embedder.model_id
                and stored_dim == embedder.dim
                and stored_ids == record_ids
            )
            if legacy:
                legacy_vectors = (
                    np.asarray(
                        [record.embedding for record in self._records],
                        dtype=np.float32,
                    )
                    if self._records
                    else np.empty((0, embedder.dim), dtype=np.float32)
                )
                valid = (
                    legacy_vectors.shape == (len(self._records), embedder.dim)
                    and np.isfinite(legacy_vectors).all()
                )
                if valid:
                    for record, vector in zip(self._records, legacy_vectors):
                        record.embedding = vector.tolist()
                    self._embedding_model_id = embedder.model_id
                    self._embedding_dim = embedder.dim
            if valid and not legacy:
                try:
                    with open(self.embedding_filepath, "rb") as handle:
                        embedding_bytes = handle.read()
                    valid = hashlib.sha256(embedding_bytes).hexdigest() == stored_digest
                    if valid:
                        matrix = np.load(io.BytesIO(embedding_bytes), allow_pickle=False)
                        valid = (
                            matrix.dtype == np.float16
                            and matrix.shape == (len(self._records), embedder.dim)
                        )
                        if valid:
                            for record, vector in zip(self._records, matrix):
                                record.embedding = vector.astype(np.float32).tolist()
                except (AttributeError, OSError, ValueError, EOFError):
                    valid = False
            self._embedding_valid = bool(valid)
            if not self._embedding_valid:
                for record in self._records:
                    record.embedding = []
                self._backfill_missing_embeddings()
            if legacy:
                self._schedule_save()
        except (AttributeError, OSError, TypeError, ValueError, EOFError, OverflowError) as exc:
            logging.warning("[StrategyMemory] 로드 오류: %s", exc)

    def _save(self):
        with self._save_lock:
            self._save_timer = None
            try:
                from agent.embedder import get_embedder

                embedder = get_embedder()
                model_id = self._embedding_model_id or embedder.model_id
                dim = self._embedding_dim or embedder.dim
                records = list(self._records)
                complete = self._embedding_valid and all(
                    len(record.embedding) == dim for record in records
                )
                matrix = np.zeros((len(records), dim), dtype=np.float16)
                if complete:
                    matrix = np.asarray(
                        [record.embedding for record in records], dtype=np.float16
                    ).reshape((len(records), dim))
                buffer = io.BytesIO()
                np.save(buffer, matrix, allow_pickle=False)
                embedding_bytes = buffer.getvalue()
                write_bytes_atomic(self.embedding_filepath, embedding_bytes)
                payload = {
                    "embedding_model_id": model_id,
                    "dim": dim,
                    "record_ids": [record.record_id for record in records],
                    "embedding_sha256": hashlib.sha256(embedding_bytes).hexdigest(),
                    "embedding_complete": complete,
                    "records": [
                        {key: value for key, value in asdict(record).items()
                         if key != "embedding"}
                        for record in records
                    ],
                }
                write_json_atomic(
                    self.filepath,
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            except (OSError, TypeError, ValueError) as exc:
                logging.warning("[StrategyMemory] 저장 오류: %s", exc)

    def _normalize_record(self, raw: dict) -> StrategyRecord:
        goal_summary = str(raw.get("goal_summary", ""))
        goal_tokens = list(raw.get("goal_tokens", []))
        if not goal_tokens and goal_summary:
            goal_tokens = sorted(list(self._extract_tokens(goal_summary)))
            
        return StrategyRecord(
            goal_summary=goal_summary,
            tags=list(raw.get("tags", ["일반"])),
            goal_tokens=goal_tokens,
            steps_desc=list(raw.get("steps_desc", [])),
            success=bool(raw.get("success", False)),
            error_summary=str(raw.get("error_summary", "")),
            failure_kind=str(raw.get("failure_kind", "")),
            workflow_hints=list(raw.get("workflow_hints", [])),
            lesson=str(raw.get("lesson", "")),
            skill_id=str(raw.get("skill_id", "")),
            user_feedback=str(raw.get("user_feedback", "")),
            few_shot_eligible=bool(raw.get("few_shot_eligible", False)),
            duration_ms=int(raw.get("duration_ms", 0)),
            timestamp=str(raw.get("timestamp", datetime.now().isoformat())),
            embedding=list(raw.get("embedding", []) or []),
            record_id=str(raw.get("record_id", "") or uuid.uuid4().hex),
        )

    def _classify_failure(self, error: str) -> str:
        return classify_failure_message(error)

    def _parse_timestamp(self, timestamp: str) -> datetime:
        try:
            return datetime.fromisoformat(str(timestamp or ""))
        except Exception:
            return datetime.min

    def _backfill_missing_embeddings(self) -> None:
        from agent.embedder import get_embedder

        embedder = get_embedder()
        with self._save_lock:
            if not self._records or (
                self._embedding_thread is not None and self._embedding_thread.is_alive()
            ):
                return
            if embedder.status == "failed":
                return

        def _worker():
            try:
                if not embedder.wait_until_ready():
                    return
                while True:
                    with self._save_lock:
                        records = list(self._records)
                        record_ids = [record.record_id for record in records]
                    vectors = []
                    for record in records:
                        vector = embedder.embed(record.goal_summary)
                        if vector is None or len(vector) != embedder.dim:
                            return
                        vectors.append(vector.tolist())
                    with self._save_lock:
                        if record_ids != [record.record_id for record in self._records]:
                            continue
                        for record, vector in zip(self._records, vectors):
                            record.embedding = vector
                        self._embedding_model_id = embedder.model_id
                        self._embedding_dim = embedder.dim
                        self._embedding_valid = True
                    self._schedule_save()
                    return
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
                logging.debug("[StrategyMemory] 임베딩 백필 중단: %s", exc)
            finally:
                with self._save_lock:
                    self._embedding_thread = None

        with self._save_lock:
            if self._embedding_thread is None or not self._embedding_thread.is_alive():
                self._embedding_thread = threading.Thread(
                    target=_worker,
                    daemon=True,
                    name="AriStrategyEmbeddingBackfill",
                )
                try:
                    self._embedding_thread.start()
                except RuntimeError as exc:
                    self._embedding_thread = None
                    logging.debug("[StrategyMemory] 백필 시작 실패: %s", exc)

    def _schedule_save(self) -> None:
        with self._save_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(self._save_delay_seconds, self._save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def flush(self) -> None:
        with self._save_lock:
            timer = self._save_timer
            self._save_timer = None
        if timer is not None:
            timer.cancel()
        self._save()


_instance: Optional[StrategyMemory] = None
_instance_lock = threading.Lock()

def get_strategy_memory() -> StrategyMemory:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = StrategyMemory()
    return _instance


def flush_strategy_memory() -> None:
    if _instance is None:
        return
    try:
        _instance.flush()
    except Exception as exc:
        logging.debug("[StrategyMemory] flush 생략: %s", exc)


atexit.register(flush_strategy_memory)

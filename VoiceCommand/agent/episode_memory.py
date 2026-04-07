"""
목표 에피소드 기억 (Episode Memory)
최근 자율 실행 에피소드의 요약을 저장하고 유사 목표 planning/replan에 재주입합니다.
"""
from __future__ import annotations

import atexit
import json
import hashlib
import logging
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import List

_DEVELOPER_SCOPE_RE = re.compile(
    r"(voicecommand(?:/(?:agent|core|ui|plugins|tests)\b|\s*(?:저장소|repository|codebase|repo)\b)?|저장소|repository|codebase|\brepo\b|\bdocs\b)",
    re.IGNORECASE,
)
_DEVELOPER_ACTION_RE = re.compile(
    r"(validate_repo\.py|--compile-only|pytest|unittest|코드\s*(?:변경|수정)|검증|테스트(?:\s*실행)?|구현|개선(?:\s*과제)?|분석|전체\s*파악)",
    re.IGNORECASE,
)


def _get_memory_file() -> str:
    try:
        from core.resource_manager import ResourceManager
        return ResourceManager.get_writable_path("episode_memory.json")
    except Exception:
        return os.path.join(os.path.dirname(__file__), "episode_memory.json")


_MEMORY_FILE = _get_memory_file()
_MAX_EPISODES = 120
_EMBED_DIM = 64
_LOCK = threading.RLock()
_INSTANCE: EpisodeMemory | None = None


@dataclass
class GoalEpisode:
    goal: str
    achieved: bool
    summary: str
    failure_kind: str = ""
    duration_ms: int = 0
    target_domains: List[str] = field(default_factory=list)
    target_windows: List[str] = field(default_factory=list)
    target_paths: List[str] = field(default_factory=list)
    state_change_summary: str = ""
    policy_summary: str = ""
    timestamp: str = ""
    embedding: List[float] = field(default_factory=list)


class EpisodeMemory:
    def __init__(self, filepath: str = _MEMORY_FILE):
        self.filepath = filepath
        self._episodes: List[GoalEpisode] = []
        self._save_lock = threading.RLock()
        self._save_timer: threading.Timer | None = None
        self._save_delay_seconds = 0.1
        self._load()

    def record(self, episode: GoalEpisode) -> None:
        summary = (episode.summary or "")[:300]
        similarity_text = self._build_similarity_text(
            goal=(episode.goal or "")[:200],
            summary=summary,
            target_domains=episode.target_domains or [],
            target_windows=episode.target_windows or [],
            target_paths=episode.target_paths or [],
            state_change_summary=(episode.state_change_summary or "")[:300],
            policy_summary=(episode.policy_summary or "")[:300],
        )
        item = GoalEpisode(
            goal=(episode.goal or "")[:200],
            achieved=bool(episode.achieved),
            summary=summary,
            failure_kind=(episode.failure_kind or "")[:80],
            duration_ms=int(episode.duration_ms or 0),
            target_domains=list(dict.fromkeys(episode.target_domains or []))[:5],
            target_windows=list(dict.fromkeys(episode.target_windows or []))[:5],
            target_paths=list(dict.fromkeys(episode.target_paths or []))[:5],
            state_change_summary=(episode.state_change_summary or "")[:300],
            policy_summary=(episode.policy_summary or "")[:300],
            timestamp=episode.timestamp or datetime.now().isoformat(),
            embedding=list(episode.embedding or self._compute_embedding(similarity_text)),
        )
        self._episodes.append(item)
        if len(self._episodes) > _MAX_EPISODES:
            self._episodes = self._episodes[-_MAX_EPISODES:]
        self._schedule_save()

    def get_recent_episodes(self, limit: int = 10) -> List[GoalEpisode]:
        return list(self._episodes[-limit:])

    def get_recent_summary(self, goal: str = "", limit: int = 3) -> str:
        normalized_goal = (goal or "").strip().lower()
        candidates = self._episodes
        matched_by_goal = False
        if normalized_goal:
            goal_embedding = self._compute_embedding(normalized_goal)
            scored = []
            for episode in self._episodes:
                overlap = self._score_episode(goal, episode, goal_embedding=goal_embedding)
                if overlap == 0 and normalized_goal not in (episode.goal or "").lower():
                    continue
                scored.append((overlap, episode))
            if scored:
                matched_by_goal = True
                candidates = [
                    episode
                    for _, episode in sorted(
                        scored,
                        key=lambda item: (item[0], getattr(item[1], "timestamp", "")),
                        reverse=True,
                    )
                ]
            else:
                candidates = self._episodes
        filtered = [episode for episode in candidates if not self._is_suspicious_developer_success(episode)]
        candidates = filtered or candidates

        lines: List[str] = []
        selected = candidates[:limit] if matched_by_goal else candidates[-limit:]
        for episode in selected:
            status = "성공" if episode.achieved else "실패"
            line = f"[{status}] {episode.goal[:60]}"
            if episode.policy_summary:
                line += f" | policy={episode.policy_summary[:80]}"
            if episode.state_change_summary:
                line += f" | state={episode.state_change_summary[:80]}"
            if not episode.achieved and episode.failure_kind:
                line += f" | failure={episode.failure_kind}"
            lines.append(line)
        return "\n".join(lines)

    def get_failure_patterns(self, domain: str, limit: int = 5) -> List[str]:
        normalized = str(domain or "").strip().lower()
        if not normalized:
            return []
        goal_embedding = self._compute_embedding(normalized)
        scored = []
        for episode in self._episodes:
            if episode.achieved:
                continue
            score = self._score_episode(domain, episode, goal_embedding=goal_embedding)
            if normalized in (episode.goal or "").lower():
                score += 0.2
            if normalized in (episode.summary or "").lower():
                score += 0.15
            if any(normalized in value.lower() for value in (episode.target_domains or [])):
                score += 0.2
            if any(normalized in value.lower() for value in (episode.target_windows or [])):
                score += 0.1
            if any(normalized in value.lower() for value in (episode.target_paths or [])):
                score += 0.1
            if score <= 0:
                continue
            reason = episode.failure_kind or episode.summary or "실패 기록"
            scored.append((score, episode.timestamp or "", f"{episode.goal[:80]} -> {reason[:120]}"))

        patterns: List[str] = []
        for _, _, pattern in sorted(scored, key=lambda item: (item[0], item[1]), reverse=True):
            if pattern not in patterns:
                patterns.append(pattern)
            if len(patterns) >= limit:
                break
        return patterns

    def _looks_like_developer_goal(self, goal: str) -> bool:
        normalized = (goal or "").strip().lower()
        return bool(normalized and _DEVELOPER_SCOPE_RE.search(normalized) and _DEVELOPER_ACTION_RE.search(normalized))

    def _is_suspicious_developer_success(self, episode: GoalEpisode) -> bool:
        if not episode.achieved or not self._looks_like_developer_goal(episode.goal):
            return False
        summary = (episode.summary or "").lower()
        if "화면 ocr" in summary:
            return True
        if "실제 경로(documents)" in summary:
            return True
        return False

    def get_goal_guidance(self, goal: str, limit: int = 3) -> str:
        summary = self.get_recent_summary(goal=goal, limit=limit)
        if not summary:
            return ""
        lines = ["최근 유사 목표 에피소드:"]
        lines.extend(summary.splitlines())
        return "\n".join(lines)

    def prune_old_failures(self, max_age_days: int = 30) -> int:
        """max_age_days일 이상 된 실패 에피소드 제거. 반환: 삭제된 수."""
        cutoff = datetime.now() - timedelta(days=max_age_days)
        before = len(self._episodes)
        self._episodes = [
            ep for ep in self._episodes
            if ep.achieved or not ep.timestamp or self._parse_ts(ep.timestamp) >= cutoff
        ]
        removed = before - len(self._episodes)
        if removed:
            self._save()
        return removed

    def _parse_ts(self, ts: str) -> datetime:
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            return datetime.min

    def _load(self) -> None:
        if not os.path.exists(self.filepath):
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self._episodes = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                episode = GoalEpisode(**item)
                if not episode.embedding:
                    episode.embedding = self._compute_embedding(self._build_similarity_text(
                        goal=episode.goal,
                        summary=episode.summary,
                        target_domains=episode.target_domains,
                        target_windows=episode.target_windows,
                        target_paths=episode.target_paths,
                        state_change_summary=episode.state_change_summary,
                        policy_summary=episode.policy_summary,
                    ))
                self._episodes.append(episode)
        except Exception as exc:
            logging.warning(f"[EpisodeMemory] 로드 실패: {exc}")

    def _save(self) -> None:
        with self._save_lock:
            self._save_timer = None
            try:
                os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
                with open(self.filepath, "w", encoding="utf-8") as handle:
                    json.dump([asdict(item) for item in self._episodes], handle, ensure_ascii=False, indent=2)
            except Exception as exc:
                logging.warning(f"[EpisodeMemory] 저장 실패: {exc}")

    def _build_similarity_text(
        self,
        goal: str,
        summary: str,
        target_domains: List[str],
        target_windows: List[str],
        target_paths: List[str],
        state_change_summary: str,
        policy_summary: str,
    ) -> str:
        return " ".join(
            part for part in [
                goal,
                summary,
                " ".join(target_domains or []),
                " ".join(target_windows or []),
                " ".join(target_paths or []),
                state_change_summary,
                policy_summary,
            ]
            if part
        )

    def _score_episode(self, goal: str, episode: GoalEpisode, goal_embedding: List[float] | None = None) -> float:
        goal_text = str(goal or "")
        episode_text = self._build_similarity_text(
            goal=episode.goal,
            summary=episode.summary,
            target_domains=episode.target_domains,
            target_windows=episode.target_windows,
            target_paths=episode.target_paths,
            state_change_summary=episode.state_change_summary,
            policy_summary=episode.policy_summary,
        )
        token_score = self._token_similarity(self._extract_tokens(goal_text), self._extract_tokens(episode_text))
        ngram_score = self._ngram_similarity(self._extract_ngrams(goal_text), self._extract_ngrams(episode_text))
        embedding_score = self._cosine_similarity(
            goal_embedding or self._compute_embedding(goal_text),
            episode.embedding or self._compute_embedding(episode_text),
        )
        return token_score * 0.35 + ngram_score * 0.2 + max(0.0, embedding_score) * 0.45

    def _extract_tokens(self, text: str) -> set[str]:
        return set(re.findall(r"[가-힣A-Za-z][가-힣A-Za-z0-9_-]{1,20}", str(text or "").lower()))

    def _extract_ngrams(self, text: str, size: int = 3) -> set[str]:
        normalized = re.sub(r"\s+", "", str(text or "").lower())
        if not normalized:
            return set()
        if len(normalized) < size:
            return {normalized}
        return {
            normalized[idx:idx + size]
            for idx in range(len(normalized) - size + 1)
        }

    def _token_similarity(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)

    def _ngram_similarity(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)

    def _compute_embedding(self, text: str) -> List[float]:
        try:
            from agent.embedder import get_embedder
            return get_embedder().embed(text).tolist()
        except Exception:
            vector = [0.0] * _EMBED_DIM
            for token in self._extract_tokens(text):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "big") % _EMBED_DIM
                vector[index] += 1.0
            return vector

    def _cosine_similarity(self, left: List[float], right: List[float]) -> float:
        if not left or not right:
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = sum(a * a for a in left) ** 0.5
        right_norm = sum(b * b for b in right) ** 0.5
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)

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


def get_episode_memory() -> EpisodeMemory:
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None:
            _INSTANCE = EpisodeMemory()
        return _INSTANCE


def flush_episode_memory() -> None:
    if _INSTANCE is None:
        return
    try:
        _INSTANCE.flush()
    except Exception as exc:
        logging.debug("[EpisodeMemory] flush 생략: %s", exc)


atexit.register(flush_episode_memory)

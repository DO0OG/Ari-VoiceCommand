"""
목표 에피소드 기억 (Episode Memory)
최근 자율 실행 에피소드의 요약을 저장하고 유사 목표 planning/replan에 재주입합니다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
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
_LOCK = threading.RLock()
_INSTANCE = None


@dataclass
class GoalEpisode:
    goal: str
    achieved: bool
    summary_kr: str
    failure_kind: str = ""
    duration_ms: int = 0
    target_domains: List[str] = field(default_factory=list)
    target_windows: List[str] = field(default_factory=list)
    target_paths: List[str] = field(default_factory=list)
    state_change_summary: str = ""
    policy_summary: str = ""
    timestamp: str = ""


class EpisodeMemory:
    def __init__(self, filepath: str = _MEMORY_FILE):
        self.filepath = filepath
        self._episodes: List[GoalEpisode] = []
        self._load()

    def record(self, episode: GoalEpisode) -> None:
        item = GoalEpisode(
            goal=(episode.goal or "")[:200],
            achieved=bool(episode.achieved),
            summary_kr=(episode.summary_kr or "")[:300],
            failure_kind=(episode.failure_kind or "")[:80],
            duration_ms=int(episode.duration_ms or 0),
            target_domains=list(dict.fromkeys(episode.target_domains or []))[:5],
            target_windows=list(dict.fromkeys(episode.target_windows or []))[:5],
            target_paths=list(dict.fromkeys(episode.target_paths or []))[:5],
            state_change_summary=(episode.state_change_summary or "")[:300],
            policy_summary=(episode.policy_summary or "")[:300],
            timestamp=episode.timestamp or datetime.now().isoformat(),
        )
        self._episodes.append(item)
        if len(self._episodes) > _MAX_EPISODES:
            self._episodes = self._episodes[-_MAX_EPISODES:]
        self._save()

    def get_recent_episodes(self, limit: int = 10) -> List[GoalEpisode]:
        return list(self._episodes[-limit:])

    def get_recent_summary(self, goal: str = "", limit: int = 3) -> str:
        normalized_goal = (goal or "").strip().lower()
        candidates = self._episodes
        matched_by_goal = False
        if normalized_goal:
            goal_tokens = set(normalized_goal.split())
            scored = []
            for episode in self._episodes:
                episode_tokens = set((episode.goal or "").lower().split())
                overlap = len(goal_tokens & episode_tokens)
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

    def _looks_like_developer_goal(self, goal: str) -> bool:
        normalized = (goal or "").strip().lower()
        return bool(normalized and _DEVELOPER_SCOPE_RE.search(normalized) and _DEVELOPER_ACTION_RE.search(normalized))

    def _is_suspicious_developer_success(self, episode: GoalEpisode) -> bool:
        if not episode.achieved or not self._looks_like_developer_goal(episode.goal):
            return False
        summary = (episode.summary_kr or "").lower()
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

    def _load(self) -> None:
        if not os.path.exists(self.filepath):
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self._episodes = [GoalEpisode(**item) for item in data if isinstance(item, dict)]
        except Exception as exc:
            logging.warning(f"[EpisodeMemory] 로드 실패: {exc}")

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8") as handle:
                json.dump([asdict(item) for item in self._episodes], handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            logging.warning(f"[EpisodeMemory] 저장 실패: {exc}")


def get_episode_memory() -> EpisodeMemory:
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None:
            _INSTANCE = EpisodeMemory()
        return _INSTANCE

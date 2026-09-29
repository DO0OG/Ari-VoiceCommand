"""사건 발화의 문구와 빈도를 관리한다."""

from __future__ import annotations

import json
import logging
import os
import random
import threading
from datetime import datetime, timedelta
from typing import Any, Callable

from core.atomic_io import backup_corrupt_file, write_json_atomic
from core.resource_manager import ResourceManager
from i18n.translator import _


_RNG = random.SystemRandom()
_MAX_SPEECHES_PER_DAY = 3
_IGNORE_AFTER_SECONDS = 120
_SUGGESTION_COOLDOWN = timedelta(minutes=30)
_EVENT_COOLDOWNS = {
    "return": timedelta(minutes=30),
    "long_use": timedelta(days=1),
    "late_night": timedelta(days=1),
    "agent_done": timedelta(minutes=15),
    "weekly_report": timedelta(days=6),
    "praise_streak": timedelta(days=1),
    "maintenance_result": timedelta(hours=20),
}
_ONCE_DAILY = {"long_use", "late_night", "praise_streak"}
_MOOD_BUCKETS = ("good", "calm", "down")

EVENT_PHRASES = {
    "return": {
        "good": ("다시 오셨네요, 반가워요.||돌아오셔서 기뻐요. 같이 이어서 해봐요.",),
        "calm": ("다시 오셨네요.||돌아오셨군요. 어디부터 이어갈까요?",),
        "down": ("돌아오셨네요. 천천히 다시 시작해요.||기다리고 있었어요. 무리하지 말고 해봐요.",),
    },
    "long_use": {
        "good": ("오래 집중하셨네요. 잠깐 쉬고 다시 해봐요.||많이 해내셨네요. 물 한잔 어때요?",),
        "calm": ("계속 집중하고 계시네요. 잠깐 쉬어 가는 건 어때요?||오래 일하셨네요. 잠깐 몸을 풀어봐요.",),
        "down": ("너무 오래 붙잡고 계셨어요. 조금 쉬어요.||잠깐 쉬어도 괜찮아요. 몸을 돌봐주세요.",),
    },
    "late_night": {
        "good": ("늦은 시간까지 수고 많으셨어요. 이제 쉬어도 좋아요.||오늘은 여기까지 하고 푹 쉬어요.",),
        "calm": ("시간이 늦었네요. 잠깐 쉬는 건 어때요?||아직 깨어 계셨네요. 조금 쉬어 가요.",),
        "down": ("밤이 꽤 깊었어요. 무리하지 말고 쉬어요.||오늘은 일찍 마무리해도 괜찮아요.",),
    },
    "agent_done": {
        "good": ("작업이 끝났어요. 결과를 확인해 주세요: {summary}||요청하신 일을 마쳤어요: {summary}",),
        "calm": ("작업을 마쳤어요. 결과는 이렇습니다: {summary}||완료된 내용이에요: {summary}",),
        "down": ("작업 결과가 나왔어요. 확인해 주세요: {summary}||요청하신 작업을 끝냈어요: {summary}",),
    },
    "weekly_report": {
        "good": ("이번 주 학습 리포트를 정리했어요.||이번 주에 배운 내용을 모아뒀어요.",),
        "calm": ("이번 주 학습 리포트를 준비했어요.||주간 리포트를 확인할 수 있어요.",),
        "down": ("이번 주 학습 결과를 정리해 뒀어요.||주간 리포트를 준비했어요. 편할 때 확인해 주세요.",),
    },
    "praise_streak": {
        "good": ("계속 칭찬해 주셔서 기분이 좋아요.||칭찬을 들으니 더 힘이 나요.",),
        "calm": ("따뜻한 말씀 고마워요.||계속 응원해 주셔서 고마워요.",),
        "down": ("다정하게 말해 주셔서 고마워요.||칭찬해 주셔서 힘이 나요.",),
    },
    "maintenance_result": {
        "good": ("새벽 정리 결과가 나왔어요. {summary}||메모리 정리 결과예요. {summary}",),
        "calm": ("정리 작업 결과예요. {summary}||새벽 정리 결과가 나왔어요. {summary}",),
        "down": ("정리 결과가 나왔어요. {summary}||메모리 정리 결과예요. {summary}",),
    },
}


def mood_bucket(mood_state=None) -> str:
    """기분의 valence를 세 구간으로 나눈다."""
    if mood_state is None:
        return "calm"
    try:
        valence = mood_state.values()[0]
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return "calm"
    if valence >= 0.25:
        return "good"
    if valence <= -0.25:
        return "down"
    return "calm"


def choose_phrase(
    phrases: dict[str, Any],
    mood_state=None,
    *,
    translator: Callable[[str], str] = _,
    values: dict[str, Any] | None = None,
) -> str:
    """기분 구간과 언어에 맞는 문구를 고른다."""
    bucket = mood_bucket(mood_state)
    candidates = phrases.get(bucket) or phrases.get("calm") or ()
    if isinstance(candidates, str):
        candidates = (candidates,)
    if not candidates:
        return ""
    translated = translator(_RNG.choice(candidates))
    options = tuple(part.strip() for part in translated.split("||") if part.strip())
    if not options:
        return ""
    phrase = _RNG.choice(options)
    if not values:
        return phrase
    try:
        return phrase.format(**values)
    except (KeyError, ValueError):
        return ""


class EventSpeechScheduler:
    """사건 발화를 가드·쿨다운·일일 상한에 따라 전달한다."""

    def __init__(
        self,
        tts_func: Callable[[str], Any],
        *,
        guard_state: Callable[[], dict] | None = None,
        context_provider: Callable[[], dict] | None = None,
        mood_provider: Callable[[], Any] | None = None,
        suggestions_provider: Callable[[], list[dict]] | None = None,
        state_path: str | None = None,
        clock: Callable[[], datetime] = datetime.now,
    ):
        self._tts = tts_func
        self._guard_state = guard_state or (lambda: {})
        self._context_provider = context_provider or self._get_context_metrics
        self._mood_provider = mood_provider or self._get_mood_state
        self._suggestions_provider = suggestions_provider
        self._clock = clock
        self._lock = threading.RLock()
        self._state_path = state_path
        self._pending: list[tuple[str, dict[str, Any]]] = []
        self._dispatching = False
        self._last_delivered: dict[str, str] = {}
        self._daily_count_date = ""
        self._daily_count = 0
        self._ignored_streak = 0
        self._last_reaction: dict[str, Any] | None = None
        self._suggestions_cache: list[dict[str, Any]] = []
        self._next_suggestion_at: datetime | None = None

        if not self._state_path:
            try:
                self._state_path = ResourceManager.get_writable_path(
                    "speech_scheduler.json"
                )
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                logging.warning("발화 상태 저장 경로를 사용할 수 없습니다: %s", exc)
        self._load()

    @staticmethod
    def _get_context_metrics() -> dict:
        from memory.user_context import get_context_manager

        return get_context_manager().get_situation_metrics()

    @staticmethod
    def _get_mood_state():
        from core.mood_state import get_mood_state

        return get_mood_state()

    def request(self, event: str, **values: Any) -> bool:
        """사건을 큐에 넣고 가드가 풀릴 때까지 보류한다."""
        if event not in EVENT_PHRASES:
            return False
        with self._lock:
            for index, (pending_event, _payload) in enumerate(self._pending):
                if pending_event == event:
                    self._pending[index] = (event, dict(values))
                    return True
            self._pending.append((event, dict(values)))
        return True

    def tick(self) -> bool:
        """상황 사건을 확인하고 발화 하나를 전달한다."""
        now = self._clock()
        self._check_context_events(now)
        self._update_ignored_streak(now)
        return self._flush_one(now)

    def get_proactive_suggestions(self) -> list[dict[str, Any]]:
        """제안 바의 새로고침 빈도를 관리한다."""
        now = self._clock()
        with self._lock:
            if self._next_suggestion_at and now < self._next_suggestion_at:
                return list(self._suggestions_cache)
            provider = self._suggestions_provider
            if provider is None:
                self._suggestions_cache = []
                return []
            self._next_suggestion_at = now + _SUGGESTION_COOLDOWN

        try:
            suggestions = provider()
        except (
            AttributeError,
            ImportError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            logging.debug("선제 제안을 갱신하지 못했습니다: %s", exc)
            suggestions = []
        if not isinstance(suggestions, list):
            suggestions = []
        with self._lock:
            self._suggestions_cache = [
                item for item in suggestions if isinstance(item, dict)
            ][:5]
            return list(self._suggestions_cache)

    def _context_metrics(self) -> dict:
        try:
            metrics = self._context_provider()
        except (
            AttributeError,
            ImportError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            logging.debug("발화 상황 지표를 읽지 못했습니다: %s", exc)
            return {}
        return metrics if isinstance(metrics, dict) else {}

    def _check_context_events(self, now: datetime) -> None:
        metrics = self._context_metrics()
        try:
            continuous_minutes = float(metrics.get("continuous_use_minutes", 0))
        except (TypeError, ValueError):
            continuous_minutes = 0
        try:
            praise_count = int(metrics.get("recent_praise_count", 0))
        except (TypeError, ValueError):
            praise_count = 0

        if continuous_minutes >= 180:
            self.request("long_use")
        if 1 <= now.hour < 5 and continuous_minutes >= 60:
            self.request("late_night")
        if praise_count >= 3:
            self.request("praise_streak")

    def _update_ignored_streak(self, now: datetime) -> None:
        with self._lock:
            reaction = self._last_reaction
            if reaction is None:
                return
            elapsed = max(0.0, (now - reaction["delivered_at"]).total_seconds())
            if elapsed < _IGNORE_AFTER_SECONDS:
                return

        metrics = self._context_metrics()
        current_since_interaction = metrics.get("seconds_since_last_interaction")
        baseline = reaction["since_interaction"]
        if current_since_interaction is None:
            # 상호작용 정보가 없으면 무시했는지 알 수 없으므로 세지 않는다.
            ignored = False
        else:
            try:
                current_since_interaction = float(current_since_interaction)
            except (TypeError, ValueError):
                return
            ignored = (
                baseline is not None
                and current_since_interaction >= baseline + elapsed - 15
            )
        with self._lock:
            if self._last_reaction is not reaction:
                return
            self._ignored_streak = self._ignored_streak + 1 if ignored else 0
            self._last_reaction = None
            self._save()
        if ignored:
            self._record_ignored_mood(now)

    def _record_ignored_mood(self, now: datetime) -> None:
        try:
            mood_state = self._mood_provider()
            if mood_state is not None:
                mood_state.record_ignored_suggestion(now.timestamp())
        except (
            AttributeError,
            ImportError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            logging.debug("무시된 발화의 기분 반영을 건너뜁니다: %s", exc)

    def _daily_limit(self) -> int:
        return max(1, _MAX_SPEECHES_PER_DAY - min(self._ignored_streak, 2))

    def _is_event_allowed(self, event: str, now: datetime) -> bool:
        last_text = self._last_delivered.get(event, "")
        if last_text:
            try:
                last = datetime.fromisoformat(last_text)
            except ValueError:
                last = None
            if last is not None:
                if event in _ONCE_DAILY and last.date() == now.date():
                    return False
                cooldown = _EVENT_COOLDOWNS[event] * (2 ** min(self._ignored_streak, 3))
                if now - last < cooldown:
                    return False
        if self._daily_count_date == now.date().isoformat():
            if self._daily_count >= self._daily_limit():
                return False
        return True

    def _flush_one(self, now: datetime) -> bool:
        with self._lock:
            if self._dispatching or not self._pending:
                return False
            try:
                guards = self._guard_state()
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
                logging.debug("발화 가드를 확인하지 못했습니다: %s", exc)
                return False
            if not isinstance(guards, dict) or any(
                guards.get(name, False)
                for name in (
                    "locked",
                    "away",
                    "quiet",
                    "fullscreen",
                    "game",
                    "tts",
                    "agent",
                )
            ):
                return False

            selected = None
            for index, item in enumerate(self._pending):
                event, _payload = item
                if event == "agent_done" and not guards.get("other_window", False):
                    continue
                if self._is_event_allowed(event, now):
                    selected = (index, item)
                    break
            if selected is None:
                return False

            index, (event, payload) = selected
            message = self._render(event, payload)
            if not message:
                self._pending.pop(index)
                return False
            metrics = self._context_metrics()
            raw_since_interaction = metrics.get("seconds_since_last_interaction")
            if raw_since_interaction is None:
                since_interaction = None
            else:
                try:
                    since_interaction = max(0.0, float(raw_since_interaction))
                except (TypeError, ValueError):
                    since_interaction = None
            self._dispatching = True

        try:
            self._tts(message)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logging.warning("사건 발화를 전달하지 못했습니다: %s", exc)
            with self._lock:
                self._dispatching = False
            return False

        with self._lock:
            self._dispatching = False
            if index < len(self._pending) and self._pending[index][0] == event:
                self._pending.pop(index)
            self._last_delivered[event] = now.isoformat()
            if self._daily_count_date != now.date().isoformat():
                self._daily_count_date = now.date().isoformat()
                self._daily_count = 0
            self._daily_count += 1
            self._last_reaction = {
                "delivered_at": now,
                "since_interaction": since_interaction,
            }
            self._save()
        return True

    def _render(self, event: str, payload: dict[str, Any]) -> str:
        try:
            mood_state = self._mood_provider()
        except (
            AttributeError,
            ImportError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            mood_state = None
        values = dict(payload)
        if event == "agent_done":
            values["summary"] = " ".join(str(values.get("summary", "")).split())[:120]
        if event == "return":
            phrase = choose_phrase(EVENT_PHRASES[event], mood_state)
            summary = " ".join(str(values.get("summary", "")).split())[:120]
            return f"{phrase} {summary}".strip() if summary else phrase
        if event == "maintenance_result":
            values["summary"] = " ".join(str(values.get("summary", "")).split())[:100]
        return choose_phrase(EVENT_PHRASES[event], mood_state, values=values)

    def _load(self) -> None:
        if not self._state_path or not os.path.isfile(self._state_path):
            return
        try:
            with open(self._state_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("발화 상태 형식이 올바르지 않습니다.")
            delivered = data.get("last_delivered", {})
            if isinstance(delivered, dict):
                self._last_delivered = {
                    str(key): value
                    for key, value in delivered.items()
                    if key in EVENT_PHRASES and isinstance(value, str)
                }
            date_text = data.get("daily_count_date", "")
            count = data.get("daily_count", 0)
            if (
                isinstance(date_text, str)
                and isinstance(count, int)
                and not isinstance(count, bool)
            ):
                self._daily_count_date = date_text
                self._daily_count = max(0, count)
            streak = data.get("ignored_streak", 0)
            if isinstance(streak, int) and not isinstance(streak, bool):
                self._ignored_streak = max(0, streak)
        except json.JSONDecodeError as exc:
            logging.warning("손상된 발화 상태를 새로 시작합니다: %s", exc)
            self._backup_corrupt_state()
        except (OSError, TypeError, ValueError) as exc:
            logging.warning("발화 상태를 읽지 못했습니다: %s", exc)
            if not isinstance(exc, OSError):
                self._backup_corrupt_state()

    def _backup_corrupt_state(self) -> None:
        if not self._state_path:
            return
        try:
            backup_corrupt_file(self._state_path)
        except OSError as exc:
            logging.warning("손상된 발화 상태 백업 실패: %s", exc)

    def _save(self) -> None:
        if not self._state_path:
            return
        try:
            write_json_atomic(
                self._state_path,
                {
                    "last_delivered": self._last_delivered,
                    "daily_count_date": self._daily_count_date,
                    "daily_count": self._daily_count,
                    "ignored_streak": self._ignored_streak,
                },
                ensure_ascii=False,
                indent=2,
            )
        except (OSError, TypeError, ValueError) as exc:
            logging.warning("발화 상태 저장 실패: %s", exc)


_speech_scheduler: EventSpeechScheduler | None = None
_speech_scheduler_lock = threading.Lock()


def set_speech_scheduler(scheduler: EventSpeechScheduler | None) -> None:
    """앱에서 공유하는 발화 스케줄러를 설정한다."""
    global _speech_scheduler
    with _speech_scheduler_lock:
        _speech_scheduler = scheduler


def get_speech_scheduler() -> EventSpeechScheduler | None:
    """초기화된 발화 스케줄러를 반환한다."""
    return _speech_scheduler

"""즉시 반응 타이머와 도구 의도 판별을 제공한다."""

from __future__ import annotations

import threading
from collections.abc import Callable


class InstantAckTimer:
    """첫 응답 전 제한 시간 뒤에 확인 문구를 한 번 알린다."""

    def __init__(self, callback: Callable[[], None], *, timer_factory=None):
        self._callback = callback
        self._lock = threading.Lock()
        self._finished = False
        self._fired = False
        timer_type = timer_factory or threading.Timer
        self._timer = timer_type(0.7, self._fire)
        self._timer.daemon = True

    def start(self) -> None:
        self._timer.start()

    def first_response(self) -> None:
        self.cancel()

    def cancel(self) -> None:
        with self._lock:
            self._finished = True
        self._timer.cancel()

    def _fire(self) -> None:
        with self._lock:
            if self._finished or self._fired:
                return
            self._fired = True
        self._callback()


def should_acknowledge(tool_intent: dict, skill_context: dict | None = None) -> bool:
    """대화 의도는 제외하고 명시된 도구 작업만 대상으로 삼는다."""
    tool_intent = tool_intent if isinstance(tool_intent, dict) else {}
    skill_context = skill_context if isinstance(skill_context, dict) else {}
    intent = str(tool_intent.get("intent", "conversation") or "conversation")
    if intent in {"automation", "file", "vision", "schedule", "web"}:
        return True
    return bool(
        tool_intent.get("force_tool")
        or tool_intent.get("preferred_tool")
        or skill_context.get("force_web_search")
        or skill_context.get("required_tool_names")
        or skill_context.get("preferred_tool")
        or skill_context.get("escalate_to_agent")
    )

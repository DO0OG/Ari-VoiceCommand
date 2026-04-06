"""작업 유형별 LLM 라우팅."""
from __future__ import annotations

from dataclasses import dataclass
import threading


@dataclass
class RouteResult:
    task_type: str
    role: str


class LLMRouter:
    ROLE_MAP = {
        "simple_chat": "default",
        "complex_plan": "planner",
        "code_gen": "execution",
        "long_analysis": "planner",
    }
    CODE_KEYWORDS = ("코드", "파이썬", "버그", "리팩토링", "테스트", "shell", "cmd")
    PLAN_KEYWORDS = ("계획", "단계", "자동화", "정리", "분석", "보고서", "설계")
    LONG_KEYWORDS = ("비교", "분석", "자세히", "깊게", "길게", "정리해줘")

    def route(self, message: str, context: dict | None = None) -> RouteResult:
        task_type = self._classify_task(message)
        return RouteResult(task_type=task_type, role=self.ROLE_MAP.get(task_type, "default"))

    def _classify_task(self, message: str) -> str:
        text = (message or "").strip().lower()
        if any(keyword in text for keyword in self.CODE_KEYWORDS):
            return "code_gen"
        if any(keyword in text for keyword in self.PLAN_KEYWORDS):
            return "complex_plan"
        if len(text) > 120 or any(keyword in text for keyword in self.LONG_KEYWORDS):
            return "long_analysis"
        return "simple_chat"


_router: LLMRouter | None = None
_router_lock = threading.Lock()


def get_llm_router() -> LLMRouter:
    global _router
    if _router is None:
        with _router_lock:
            if _router is None:
                _router = LLMRouter()
    return _router

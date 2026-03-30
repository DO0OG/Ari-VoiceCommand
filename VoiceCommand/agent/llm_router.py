"""작업 유형별 LLM 라우팅."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RouteResult:
    task_type: str
    provider: str
    model: str


class LLMRouter:
    ROUTE_TABLE = {
        "simple_chat": {"provider": "groq", "model": "llama-3.3-70b-versatile"},
        "complex_plan": {"provider": "groq", "model": "llama-3.3-70b-versatile"},
        "code_gen": {"provider": "groq", "model": "qwen-qwq-32b"},
        "long_analysis": {"provider": "openai", "model": "gpt-4o-mini"},
        "offline": {"provider": "ollama", "model": "llama3.2"},
    }

    CODE_KEYWORDS = ("코드", "파이썬", "버그", "리팩토링", "테스트", "shell", "cmd")
    PLAN_KEYWORDS = ("계획", "단계", "자동화", "정리", "분석", "보고서", "설계")
    LONG_KEYWORDS = ("비교", "분석", "자세히", "깊게", "길게", "정리해줘")

    def route(self, message: str, context: dict | None = None) -> RouteResult:
        task_type = self._classify_task(message)
        route = self.ROUTE_TABLE[task_type]
        return RouteResult(task_type=task_type, provider=route["provider"], model=route["model"])

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


def get_llm_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router

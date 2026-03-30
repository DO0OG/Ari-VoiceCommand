"""구조화된 실패 반성 엔진."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from agent.execution_analysis import classify_failure_message


@dataclass
class ReflectionResult:
    lesson: str
    root_cause: str
    avoid_patterns: List[str] = field(default_factory=list)
    fix_suggestion: str = ""


class ReflectionEngine:
    def reflect(self, goal: str, run_result) -> ReflectionResult:
        failure_messages = []
        for step_result in getattr(run_result, "step_results", []):
            if step_result.exec_result.success:
                continue
            failure_messages.append(step_result.exec_result.error or step_result.exec_result.output or "")

        primary_failure = failure_messages[-1] if failure_messages else ""
        root_cause = classify_failure_message(primary_failure)
        avoid_patterns = []
        if root_cause:
            avoid_patterns.append(root_cause)
        if "timeout" in root_cause.lower():
            avoid_patterns.append("동일한 대기 시간 재시도")
        if "permission" in root_cause.lower():
            avoid_patterns.append("권한 없는 경로 직접 쓰기")

        fix_suggestion = "단계를 더 작게 나누고 이전 실패 패턴을 피해서 다시 계획하세요."
        lesson = primary_failure[:180] if primary_failure else f"{goal[:60]} 작업 실패 패턴을 피하도록 계획을 수정하세요."
        return ReflectionResult(
            lesson=lesson,
            root_cause=root_cause or "unknown",
            avoid_patterns=avoid_patterns,
            fix_suggestion=fix_suggestion,
        )


_engine: ReflectionEngine | None = None


def get_reflection_engine() -> ReflectionEngine:
    global _engine
    if _engine is None:
        _engine = ReflectionEngine()
    return _engine

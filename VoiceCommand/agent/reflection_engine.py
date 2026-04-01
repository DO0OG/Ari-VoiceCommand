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


_FIX_SUGGESTIONS = {
    "timeout": "대기 시간을 늘리거나 비동기 폴링 방식으로 전환하고, 재시도 횟수를 명시하세요.",
    "permission_denied": "관리자 권한 없이 접근 가능한 경로를 먼저 확인하거나, 권한 요청 단계를 선행하세요.",
    "missing_resource": "파일·경로 존재 여부를 사전에 검증하고, 없으면 생성 단계를 먼저 실행하세요.",
    "syntax_error": "코드의 들여쓰기와 따옴표를 재검토하고, 더 단순한 구조로 재작성하세요.",
    "code_generation_error": "사용할 모듈과 함수명을 명확히 지정하고, 동적 import 경로를 확인하세요.",
    "network_error": "요청에 타임아웃과 재시도 로직을 추가하고, 오프라인 대안을 검토하세요.",
    "user_cancelled": "파괴적 작업 전에 사용자에게 미리 알리고, 취소 시 롤백 단계를 포함하세요.",
    "execution_failed": "단계를 더 작게 나누고, 각 단계의 사전 조건을 검증하는 로직을 추가하세요.",
}

_AVOID_PATTERNS: dict = {
    "timeout": ["동일한 대기 시간 단순 재시도", "blocking I/O 루프 없는 대기"],
    "permission_denied": ["권한 없는 시스템 경로 직접 쓰기", "관리자 권한 검증 없이 레지스트리 접근"],
    "missing_resource": ["존재 확인 없이 파일·경로 사용", "상대 경로만으로 파일 탐색"],
    "syntax_error": ["복잡한 중첩 코드 단일 블록 생성", "탭·스페이스 혼합 들여쓰기"],
    "code_generation_error": ["미확인 모듈명 직접 사용", "선택적 패키지 동적 import 없이 참조"],
    "network_error": ["재시도 없는 단일 HTTP 요청", "타임아웃 없는 네트워크 호출"],
    "user_cancelled": ["확인 없이 파괴적 작업 실행"],
    "execution_failed": ["동일 실패 패턴 조건 변경 없이 반복"],
}


class ReflectionEngine:
    def reflect(self, goal: str, run_result) -> ReflectionResult:
        failure_messages: List[str] = []
        for step_result in getattr(run_result, "step_results", []):
            if step_result.exec_result.success:
                continue
            msg = step_result.exec_result.error or step_result.exec_result.output or ""
            if msg:
                failure_messages.append(msg)

        primary_failure = failure_messages[-1] if failure_messages else ""
        root_cause = classify_failure_message(primary_failure) or "execution_failed"

        avoid_patterns = list(_AVOID_PATTERNS.get(root_cause, _AVOID_PATTERNS["execution_failed"]))
        fix_suggestion = _FIX_SUGGESTIONS.get(root_cause, _FIX_SUGGESTIONS["execution_failed"])

        goal_summary = (goal or "")[:60]
        if primary_failure:
            lesson = "[%s] %s: %s" % (root_cause, goal_summary, primary_failure[:120])
        else:
            lesson = "%s 작업 실패. %s" % (goal_summary, fix_suggestion)

        return ReflectionResult(
            lesson=lesson,
            root_cause=root_cause,
            avoid_patterns=avoid_patterns,
            fix_suggestion=fix_suggestion,
        )


_engine: ReflectionEngine | None = None


def get_reflection_engine() -> ReflectionEngine:
    global _engine
    if _engine is None:
        _engine = ReflectionEngine()
    return _engine

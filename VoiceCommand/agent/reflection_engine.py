"""구조화된 실패 반성 엔진."""
from __future__ import annotations

import json
import logging
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
    "missing_module": "필요한 패키지가 없습니다. pip install로 설치 단계를 먼저 실행하거나 표준 라이브러리로 대체하세요.",
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
    "missing_module": ["설치 확인 없이 외부 패키지 직접 import", "표준 라이브러리 대체 없이 선택 패키지 의존"],
    "missing_resource": ["존재 확인 없이 파일·경로 사용", "상대 경로만으로 파일 탐색"],
    "syntax_error": ["복잡한 중첩 코드 단일 블록 생성", "탭·스페이스 혼합 들여쓰기"],
    "code_generation_error": ["미확인 모듈명 직접 사용", "선택적 패키지 동적 import 없이 참조"],
    "network_error": ["재시도 없는 단일 HTTP 요청", "타임아웃 없는 네트워크 호출"],
    "user_cancelled": ["확인 없이 파괴적 작업 실행"],
    "execution_failed": ["동일 실패 패턴 조건 변경 없이 반복"],
}

_REFLECTION_SYSTEM_PROMPT = (
    "당신은 자율 실행 에이전트의 실패를 분석하는 품질 엔진입니다. "
    "반드시 JSON 객체만 반환하고, lesson은 다음 시도에 바로 도움이 되도록 간결하게 작성하세요."
)


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
        fallback_result = self._build_fallback(goal, primary_failure, root_cause)

        try:
            raw = self._call_llm(goal, run_result, root_cause, primary_failure)
            payload = self._parse_json(raw)
        except Exception as exc:
            logging.debug("[ReflectionEngine] LLM 반성 생략: %s", exc)
            payload = {}

        avoid_patterns = self._normalize_patterns(
            payload.get("avoid_patterns") or payload.get("avoid") or fallback_result.avoid_patterns
        )
        fix_suggestion = str(
            payload.get("fix_suggestion") or payload.get("fix") or fallback_result.fix_suggestion
        )[:300]
        lesson = str(payload.get("lesson") or fallback_result.lesson)[:400]
        return ReflectionResult(
            lesson=lesson,
            root_cause=root_cause,
            avoid_patterns=avoid_patterns,
            fix_suggestion=fix_suggestion,
        )

    def _build_fallback(self, goal: str, primary_failure: str, root_cause: str) -> ReflectionResult:
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

    def _call_llm(self, goal: str, run_result, root_cause: str, primary_failure: str) -> str:
        from agent.llm_provider import get_llm_provider
        from agent.strategy_memory import get_strategy_memory

        prior_lessons = get_strategy_memory().get_lessons_by_cause(root_cause, limit=3)
        history_lines = []
        for step_result in getattr(run_result, "step_results", [])[-5:]:
            status = "성공" if step_result.exec_result.success else "실패"
            failure = step_result.exec_result.error or step_result.exec_result.output or ""
            history_lines.append(
                f"- {status} | {getattr(step_result.step, 'description_kr', '')[:80]} | {failure[:160]}"
            )
        prompt = (
            f"목표: {goal}\n"
            f"분류된 실패 원인: {root_cause}\n"
            f"대표 오류: {primary_failure[:200]}\n"
            f"최근 단계 이력:\n{chr(10).join(history_lines) if history_lines else '- 없음'}\n"
            f"과거 동일 원인 교훈:\n{chr(10).join(f'- {item}' for item in prior_lessons) if prior_lessons else '- 없음'}\n\n"
            "다음 JSON 객체만 반환하세요:\n"
            '{"lesson":"핵심 교훈","avoid_patterns":["피해야 할 접근"],"fix_suggestion":"추천 수정 방향"}'
        )
        return get_llm_provider().chat(
            prompt,
            include_context=False,
            system_override=_REFLECTION_SYSTEM_PROMPT,
            save_history=False,
        )

    def _parse_json(self, raw: str) -> dict:
        text = str(raw or "").strip()
        if not text:
            return {}
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return {}

    def _normalize_patterns(self, value) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip()[:120] for item in value if str(item).strip()]
        if isinstance(value, str):
            parts = [item.strip() for item in value.replace("\n", "|").split("|")]
            return [item[:120] for item in parts if item]
        return []


_engine: ReflectionEngine | None = None


def get_reflection_engine() -> ReflectionEngine:
    global _engine
    if _engine is None:
        _engine = ReflectionEngine()
    return _engine

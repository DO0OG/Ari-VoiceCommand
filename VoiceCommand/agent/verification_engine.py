"""
검증 엔진 (Verification Engine)
실행 결과가 목표를 달성했는지 판단합니다.
개발자 목표 전용 사전 검사와 RealVerifier / Planner 폴백을 포함합니다.
"""
import logging
from typing import List, Optional, Tuple

from agent.agent_planner import AgentPlanner
from agent.autonomous_executor import ExecutionResult
from agent.execution_analysis import is_read_only_step_content

logger = logging.getLogger(__name__)

_DEVELOPER_VERIFY_TOKENS = (
    "validate_repo.py",
    "--compile-only",
    "pytest",
    "unittest",
    "tests/test_",
    "[validate]",
)


class VerificationEngine:
    """목표 달성 여부를 판단하는 검증 엔진"""

    def __init__(self, planner: AgentPlanner):
        self.planner = planner

    # ── 공개 메서드 ────────────────────────────────────────────────────────────

    def verify(
        self,
        goal: str,
        step_results: List,
    ) -> Tuple[bool, str]:
        """목표와 단계 결과를 받아 (달성 여부, 한국어 요약) 반환."""
        developer_precheck = self._verify_developer_goal_completion(goal, step_results)
        if developer_precheck is not None:
            return developer_precheck
        try:
            from agent.real_verifier import get_real_verifier
            v = get_real_verifier().verify(goal, step_results)
            return v.verified, v.summary_kr
        except Exception as exc:
            logger.debug(f"[VerificationEngine] RealVerifier 폴백: {exc}")
        if any(not sr.exec_result.success for sr in step_results):
            return False, "일부 단계 실패"
        verdict = self.planner.verify(
            goal, [sr.exec_result for sr in step_results]
        )
        return verdict.get("achieved", False), verdict.get("summary_kr", "검증 실패")

    # ── 내부 메서드 ────────────────────────────────────────────────────────────

    def _verify_developer_goal_completion(
        self,
        goal: str,
        step_results: List,
    ) -> Optional[Tuple[bool, str]]:
        if not self._is_developer_goal(goal):
            return None

        has_code_change = False
        has_validation = False
        scope_violation = self._find_developer_scope_violation(goal, step_results)
        if scope_violation:
            return False, scope_violation

        for sr in step_results:
            step = getattr(sr, "step", None)
            exec_result = getattr(sr, "exec_result", None)
            content = getattr(step, "content", "") or ""
            description = getattr(step, "description_kr", "") or ""
            output = getattr(exec_result, "output", "") or ""
            error = getattr(exec_result, "error", "") or ""
            combined = "\n".join([content, description, output, error]).lower()

            if not is_read_only_step_content(content, description):
                has_code_change = True
            if self._is_valid_developer_validation_signal(combined):
                has_validation = True

        if not has_code_change and not has_validation:
            return (
                False,
                "저장소 분석만 수행됐고 실제 코드 변경과 검증이 확인되지 않았습니다.",
            )
        if not has_code_change:
            return (
                False,
                "저장소 분석은 수행됐지만 실제 코드 변경이 확인되지 않았습니다.",
            )
        if not has_validation:
            return (
                False,
                "코드 변경은 있었지만 validate_repo.py 또는 관련 테스트 검증이 확인되지 않았습니다.",
            )
        return None

    def _find_developer_scope_violation(
        self,
        goal: str,
        step_results: List,
    ) -> str:
        """ExecutionEngine 의 동일 메서드에 위임 — 중복을 피하기 위해 planner만 직접 사용."""
        import json
        import os
        import re

        def _extract_paths(text: str) -> List[str]:
            candidates: List[str] = []
            normalized_repo_root = (
                os.path.abspath(os.getcwd()).replace("\\", "/").lower()
            )

            def add_candidate(value: str) -> None:
                if not value:
                    return
                normalized = (
                    str(value).strip().strip('"').strip("'").replace("\\", "/")
                )
                if not normalized:
                    return
                lowered = normalized.lower().lstrip("./")
                if re.match(r"^[a-z]:/", lowered):
                    repo_prefix = normalized_repo_root + "/"
                    if lowered.startswith(repo_prefix):
                        lowered = lowered[len(repo_prefix):]
                if lowered and lowered not in candidates:
                    candidates.append(lowered)

            def visit(value) -> None:
                if isinstance(value, str):
                    for match in re.findall(
                        r"(?:VoiceCommand|docs|tests|market|supabase|\.github|\.claude|\.idea)"
                        r"[/\\][A-Za-z0-9_./\\-]+",
                        value,
                        flags=re.IGNORECASE,
                    ):
                        add_candidate(match)
                elif isinstance(value, dict):
                    for nested in value.values():
                        visit(nested)
                elif isinstance(value, list):
                    for nested in value:
                        visit(nested)

            try:
                payload = json.loads(text)
            except Exception:
                payload = None
            if payload is not None:
                visit(payload)
            visit(text)
            return candidates

        for sr in step_results:
            step = getattr(sr, "step", None)
            exec_result = getattr(sr, "exec_result", None)
            content = getattr(step, "content", "") or ""
            output = getattr(exec_result, "output", "") or ""
            for path in _extract_paths("\n".join([content, output])):
                if not self.planner.is_allowed_developer_path(
                    path, goal=goal, context=None
                ):
                    return (
                        f"허용 범위를 벗어난 파일/경로가 선택되어 작업을 완료로 볼 수 없습니다: {path}"
                    )
        return ""

    def _is_developer_goal(self, goal: str) -> bool:
        try:
            return bool(
                hasattr(self.planner, "is_developer_goal")
                and self.planner.is_developer_goal(goal)
            )
        except Exception:
            return False

    def _contains_invalid_developer_validation(self, content: str) -> bool:
        normalized = (content or "").lower().replace("\\", "/")
        if "py_compile" in normalized or "&&" in normalized:
            return True
        if (
            "tests/" in normalized
            and "voicecommand/tests/" not in normalized
            and "voicecommand.tests." not in normalized
        ):
            return True
        return False

    def _is_valid_developer_validation_signal(self, combined: str) -> bool:
        normalized = (combined or "").lower().replace("\\", "/")
        if self._contains_invalid_developer_validation(normalized):
            return False
        return any(token in normalized for token in _DEVELOPER_VERIFY_TOKENS)

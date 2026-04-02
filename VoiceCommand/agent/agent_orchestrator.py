"""
에이전트 오케스트레이터 (Agent Orchestrator)
Plan → Execute+Self-Fix → Verify 다층 루프로 목표를 자율적으로 달성합니다.

사용 패턴:
  1. execute_with_self_fix(code, step_type, goal)
     단일 코드 실행 + 자동 수정 (기존 executor 대체)

  2. run(goal)
     복잡한 목표 → 다단계 계획 → 병렬 실행+자동수정 → 코드 기반 검증 → [재계획] 루프
"""
import concurrent.futures
import ast
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, List, Optional, Callable, Dict, Tuple

from agent.agent_planner import AgentPlanner, ActionStep, get_planner
from agent.autonomous_executor import AutonomousExecutor, ExecutionResult, get_executor
from agent.execution_analysis import (
    classify_failure_message,
    extract_artifacts,
    extract_step_targets,
    is_read_only_step_content,
    mutates_runtime_state,
)

logger = logging.getLogger(__name__)

_DEVELOPER_VERIFY_TOKENS = (
    "validate_repo.py",
    "--compile-only",
    "pytest",
    "unittest",
    "tests/test_",
    "[validate]",
)

try:
    from services.dom_analyser import suggest_next_actions
except Exception:
    suggest_next_actions = None

# executor._lock 경합 시 반환되는 오류 문자열 — self-fix 대상에서 제외
_LOCK_CONTENTION_ERRORS = frozenset({
    "이미 다른 코드가 실행 중입니다.",
    "이미 다른 명령이 실행 중입니다.",
})

# import명 → pip 패키지명 매핑 (일치하지 않는 경우)
_IMPORT_TO_PIP: dict = {
    "PIL": "Pillow",
    "cv2": "opencv-python-headless",
    "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4",
    "docx": "python-docx",
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "Crypto": "pycryptodome",
    "gi": "PyGObject",
    "serial": "pyserial",
    "usb": "pyusb",
}

_SAFE_AST_CALLS = {
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
}

_SAFE_AST_METHODS = {
    dict: {"get"},
}

_COMPARE_OPERATORS = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: lambda a, b: a is b,
    ast.IsNot: lambda a, b: a is not b,
}

_UNARY_OPERATORS = {
    ast.Not: lambda value: not value,
}


# ── 데이터 클래스 ──────────────────────────────────────────────────────────────

@dataclass
class StepResult:
    step: ActionStep
    exec_result: ExecutionResult
    attempt: int = 1
    was_fixed: bool = False
    failure_kind: str = ""


@dataclass
class AgentRunResult:
    goal: str
    step_results: List[StepResult] = field(default_factory=list)
    achieved: bool = False
    summary_kr: str = ""
    total_iterations: int = 0

    def all_exec_results(self) -> List[ExecutionResult]:
        return [sr.exec_result for sr in self.step_results]


# ── 오케스트레이터 ─────────────────────────────────────────────────────────────

class AgentOrchestrator:
    """Plan → Execute+Self-Fix → Verify 다층 자율 실행기"""

    MAX_PLAN_ITERATIONS = 4   # 전체 재계획 최대 횟수
    MAX_STEP_RETRIES = 2      # 단계 당 자동 수정 최대 횟수

    def __init__(
        self,
        executor: AutonomousExecutor,
        planner: AgentPlanner,
        tts_func: Optional[Callable] = None,
        progress_callback: Optional[Callable] = None,
        thinking_callback: Optional[Callable] = None,
    ):
        self.executor = executor
        self.planner = planner
        self.tts = tts_func
        self.progress_callback = progress_callback
        self.thinking_callback = thinking_callback
        self._run_lock = threading.Lock()

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def set_progress_callback(self, cb: Optional[Callable]) -> None:
        """진행 이벤트 콜백 설정. UI 대시보드 연결에 사용."""
        self.progress_callback = cb

    def set_thinking_callback(self, cb: Optional[Callable]) -> None:
        """생각 중(Thinking) 상태 콜백 설정. 캐릭터 애니메이션 제어에 사용."""
        self.thinking_callback = cb

    def execute_with_self_fix(self, content: str, step_type: str, goal: str) -> ExecutionResult:
        """단일 단계 실행 + 자동 수정 (단순 도구 호출용)"""
        step = ActionStep(step_id=0, step_type=step_type, content=content, description_kr="단일 명령 실행")
        res, _, _ = self._execute_step_with_retry(step, goal, {})
        return res

    def _emit_progress(self, event_type: str, **kwargs) -> None:
        if self.progress_callback:
            try:
                self.progress_callback(event_type, **kwargs)
            except Exception as e:
                logger.debug(f"[Orchestrator] 진행 콜백 오류: {e}")

    def _set_thinking(self, thinking: bool) -> None:
        if self.thinking_callback:
            try:
                self.thinking_callback(thinking)
            except Exception as e:
                logger.debug(f"[Orchestrator] 생각 콜백 오류: {e}")

    def run(self, goal: str) -> AgentRunResult:
        """복잡한 목표를 다층 루프로 자율 달성."""
        if not self._run_lock.acquire(blocking=False):
            logger.warning("[Orchestrator] 이미 에이전트가 실행 중입니다.")
            return AgentRunResult(goal=goal, summary_kr="다른 작업이 진행 중입니다.")

        start_time = time.time()
        self._set_thinking(True)
        try:
            run_result = self._run_loop(goal)
            duration = int((time.time() - start_time) * 1000)
            self._post_run_update(goal, run_result, duration)
            
            # 실패 시 L4 반성 및 교훈 도출
            lesson = ""
            if not run_result.achieved:
                lesson_data = self._reflect_on_failure(goal, run_result)
                lesson = lesson_data.get("lesson", "")
                if lesson:
                    run_result.summary_kr += f"\n(교훈: {lesson})"

            self._record_strategy(goal, run_result, duration, lesson)
            return run_result
        finally:
            self._set_thinking(False)
            self._run_lock.release()

    def _run_loop(self, goal: str) -> AgentRunResult:
        """실제 Plan-Execute-Verify 루프"""
        run_result = AgentRunResult(goal=goal)
        context: Dict[str, str] = {"goal": goal}
        try:
            from agent.episode_memory import get_episode_memory
            recent_episode_summary = get_episode_memory().get_recent_summary(goal=goal, limit=3)
            if recent_episode_summary:
                context["recent_goal_episodes"] = recent_episode_summary[:600]
        except Exception as exc:
            logger.debug(f"[Orchestrator] episode memory 주입 생략: {exc}")

        if self._should_prefer_template_over_skill(goal):
            logger.info("[Orchestrator] 안정 템플릿 우선 적용: skill 재사용 생략")
        else:
            skill_result = self._run_with_skill_if_available(goal, context)
            if skill_result is not None:
                return skill_result

        for iteration in range(self.MAX_PLAN_ITERATIONS):
            run_result.total_iterations = iteration + 1
            logger.info(f"[Orchestrator] 계획 수립 (반복 {iteration+1}/{self.MAX_PLAN_ITERATIONS})")

            # Layer 1: Plan
            steps = self.planner.decompose(goal, context)
            if not steps:
                run_result.summary_kr = "계획 수립에 실패했습니다."
                break

            self._log_plan(steps)
            self._emit_progress("plan_ready", steps=[asdict(s) for s in steps], iteration=iteration)

            # Layer 2: Execute + Self-Fix
            all_success, step_results = self._execute_plan(steps, context, goal)
            run_result.step_results.extend(step_results)

            if not all_success:
                failed = [sr for sr in step_results if not sr.exec_result.success]
                adaptive_ctx = self._build_adaptive_context(failed)
                context.update(adaptive_ctx)
                reason = adaptive_ctx.get("재계획_이유", "실행 실패")
                self._emit_progress("replan", iteration=iteration, reason=reason)
                self._say("[진지] 접근 방법을 바꿔서 다시 시도합니다.")
                if iteration >= self.MAX_PLAN_ITERATIONS - 1:
                    run_result.summary_kr = f"실행 실패: {reason}"
                continue

            # Layer 3: Verify
            self._emit_progress("verify_start")
            achieved, summary = self._verify(goal, step_results)
            run_result.achieved = achieved
            run_result.summary_kr = summary

            if achieved:
                self._emit_progress("achieved", summary=summary)
                self._say(f"[기쁨] {summary}")
                break
            else:
                context["이전_시도"] = summary
                self._emit_progress("not_achieved", summary=summary, iteration=iteration)
                self._say("[진지] 목표를 아직 달성하지 못했어요. 다시 시도합니다.")
        
        return run_result

    def _should_prefer_template_over_skill(self, goal: str) -> bool:
        try:
            if self._is_developer_goal(goal):
                return True
            template_steps = self.planner._build_template_plan(goal)  # 내부 안정 템플릿 우선
        except Exception as exc:
            logger.debug(f"[Orchestrator] 템플릿 우선 판단 생략: {exc}")
            return False
        return bool(template_steps)

    def _is_developer_goal(self, goal: str) -> bool:
        try:
            return bool(hasattr(self.planner, "is_developer_goal") and self.planner.is_developer_goal(goal))
        except Exception:
            return False

    def _run_with_skill_if_available(self, goal: str, context: Dict[str, str]) -> Optional[AgentRunResult]:
        try:
            from agent.skill_library import get_skill_library
            from agent.agent_planner import ActionStep
            skill = get_skill_library().get_applicable_skill(goal)
            if not skill:
                return None

            # Direction 2: 컴파일된 Python 스킬 우선 실행
            if skill.compiled:
                result = self._run_compiled_skill(skill, goal)
                if result is not None:
                    context["skill_id"] = skill.skill_id
                    return result
                # 컴파일 스킬 실패 → 일반 스텝 실행으로 폴백

            steps = [
                ActionStep(
                    step_id=item.get("step_id", idx),
                    step_type=item.get("step_type", "python"),
                    content=item.get("content", ""),
                    description_kr=item.get("description_kr", f"스킬 단계 {idx+1}"),
                    expected_output=item.get("expected_output", ""),
                    condition=item.get("condition", ""),
                    on_failure=item.get("on_failure", "abort"),
                )
                for idx, item in enumerate(skill.steps)
            ]
            all_success, step_results = self._execute_plan(steps, context, goal)
            result = AgentRunResult(goal=goal, step_results=step_results, total_iterations=1)
            if all_success:
                achieved, summary = self._verify(goal, step_results)
                result.achieved = achieved
                result.summary_kr = summary
                if achieved:
                    context["skill_id"] = skill.skill_id
                    get_skill_library().record_feedback(skill.skill_id, positive=True)
                    return result
            # 실패 시 에러 수집 후 자기수정 트리거
            error = " | ".join(
                (sr.exec_result.error or sr.exec_result.output or "")[:120]
                for sr in step_results if not sr.exec_result.success
            )
            get_skill_library().deprecate_if_failing(skill.skill_id, error=error)
        except Exception as e:
            logger.debug(f"[Orchestrator] skill 실행 생략: {e}")
        return None

    def _run_compiled_skill(self, skill, goal: str) -> Optional[AgentRunResult]:
        """Direction 2: 컴파일된 Python 스킬 실행. 성공 시 AgentRunResult 반환."""
        try:
            from agent.skill_library import get_skill_library
            from agent.skill_optimizer import get_skill_optimizer
            optimizer = get_skill_optimizer()
            success, output = optimizer.run_compiled(skill.skill_id, goal)
            result = AgentRunResult(goal=goal, total_iterations=1)
            if success:
                result.achieved = True
                result.summary_kr = output
                get_skill_library().record_feedback(skill.skill_id, positive=True)
                logger.info(f"[Orchestrator] 컴파일 스킬 실행 성공: {skill.name}")
                return result
            # 실패 → 코드 수정 트리거 후 None 반환 (스텝 폴백)
            logger.info(f"[Orchestrator] 컴파일 스킬 실패, 코드 수정 예약: {output[:100]}")
            get_skill_library().record_feedback(skill.skill_id, positive=False, error=output)
            return None
        except Exception as exc:
            logger.debug(f"[Orchestrator] 컴파일 스킬 실행 오류: {exc}")
            return None

    def _reflect_on_failure(self, goal: str, run_result: AgentRunResult) -> Dict[str, str]:
        """실패한 시나리오에 대해 L4 반성(Post-mortem) 수행"""
        history_lines = []
        for i, sr in enumerate(run_result.step_results):
            status = "✅" if sr.exec_result.success else "❌"
            history_lines.append(f"[{i+1}] {status} {sr.step.description_kr}")
            if not sr.exec_result.success:
                history_lines.append(f"   오류: {(sr.exec_result.error or sr.exec_result.output or '')[:100]}")
        
        history_summary = "\n".join(history_lines)
        return self.planner.reflect(goal, history_summary)

    def _execute_plan(self, steps: List[ActionStep], context: Dict[str, str], goal: str) -> Tuple[bool, List[StepResult]]:
        step_results: List[StepResult] = []
        groups = self._group_by_dependency(steps)

        for group in groups:
            if len(group) == 1 and group[0].step_type == "think":
                step = group[0]
                step_results.append(StepResult(step=step, exec_result=ExecutionResult(success=True, output=step.description_kr)))
                context[f"step_{step.step_id}_output"] = step.description_kr
                continue

            runnable = [s for s in group if not s.condition or self._eval_condition(s.condition, context)]
            if not runnable: continue

            if len(runnable) == 1:
                step = runnable[0]
                self._emit_progress("step_start", step_id=step.step_id, desc=step.description_kr, step_type=step.step_type)
                result, attempt, fixed = self._execute_step_with_retry(step, goal, context)
                group_results = [StepResult(step=step, exec_result=result, attempt=attempt, was_fixed=fixed, failure_kind=self._classify_failure(result))]
            else:
                for s in runnable: self._emit_progress("step_start", step_id=s.step_id, desc=s.description_kr, step_type=s.step_type)
                group_results = self._execute_parallel_group(runnable, context, goal)

            for sr in group_results:
                sr = self._apply_developer_step_guard(goal, sr, context)
                step_results.append(sr)
                self._emit_progress("step_done", step_id=sr.step.step_id, success=sr.exec_result.success, was_fixed=sr.was_fixed, error=(sr.exec_result.error or "")[:100])
                if sr.exec_result.success:
                    if sr.exec_result.output: context[f"step_{sr.step.step_id}_output"] = sr.exec_result.output[:300]
                    self._update_runtime_context(context, sr.exec_result)
                elif sr.step.on_failure == "abort":
                    return False, step_results
        return True, step_results

    def _execute_parallel_group(self, group: List[ActionStep], context: Dict[str, str], goal: str) -> List[StepResult]:
        results = [None] * len(group)
        def run_one(idx, step):
            res, att, fixed = self._execute_step_with_retry(step, goal, context)
            return StepResult(step=step, exec_result=res, attempt=att, was_fixed=fixed, failure_kind=self._classify_failure(res))
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(group)) as pool:
            futures = {pool.submit(run_one, i, s): i for i, s in enumerate(group)}
            for f in concurrent.futures.as_completed(futures):
                idx = futures[f]
                try: results[idx] = f.result()
                except Exception as e:
                    results[idx] = StepResult(step=group[idx], exec_result=ExecutionResult(success=False, error=str(e)), failure_kind="runtime_exception")
        return [r for r in results if r]

    def _execute_step_with_retry(self, step: ActionStep, goal: str, context: Dict[str, str]) -> Tuple[ExecutionResult, int, bool]:
        curr, fixed, res = step, False, ExecutionResult(success=False, error="실행되지 않음")
        for att in range(1, self.MAX_STEP_RETRIES + 2):
            res = self._run_step(curr, context)
            if res.success:
                return res, att, fixed
            if att > self.MAX_STEP_RETRIES:
                break
            err = res.error or res.output or "오류"
            if err in _LOCK_CONTENTION_ERRORS:
                time.sleep(att)
                continue
            # ModuleNotFoundError → pip 자동 설치 후 LLM 수정 없이 재시도
            if "No module named" in err and self._auto_install_if_needed(err):
                logger.info("[Orchestrator] 패키지 설치 후 단계 재실행")
                continue
            self._say("[걱정] 오류 발생, 수정 중입니다. (%d/%d)" % (att, self.MAX_STEP_RETRIES))
            f = self.planner.fix_step(curr, err, goal, context)
            if f and f.content and f.content != curr.content:
                curr, fixed = f, True
            else:
                break
        return res, att, fixed

    # 자동 설치 시 사용자 동의 없이 설치 가능한 안전 패키지 목록
    _AUTO_INSTALL_SAFE = frozenset({
        "pandas", "numpy", "matplotlib", "Pillow", "PIL",
        "requests", "httpx", "beautifulsoup4", "bs4",
        "openpyxl", "python-docx", "docx", "reportlab",
        "scikit-learn", "sklearn", "scipy",
        "pyyaml", "yaml", "python-dotenv", "dotenv",
        "opencv-python-headless", "cv2",
        "tqdm", "colorama", "tabulate", "rich",
    })

    def _auto_install_if_needed(self, error: str) -> bool:
        """ModuleNotFoundError 감지 시 pip install 자동 실행.
        안전 목록 패키지: 자동 설치.
        미확인 패키지: 사용자 동의 후 설치.
        설치 성공 시 True 반환."""
        match = re.search(r"No module named '([^']+)'", error)
        if not match:
            return False
        pkg = match.group(1).split(".")[0]
        pip_pkg = _IMPORT_TO_PIP.get(pkg, pkg)

        # 미확인 패키지 → 사용자 동의 필요
        if pip_pkg not in self._AUTO_INSTALL_SAFE and pkg not in self._AUTO_INSTALL_SAFE:
            self._say("'%s' 패키지 설치가 필요합니다. 허용하시겠습니까?" % pip_pkg)
            logger.info("[Orchestrator] 미확인 패키지 설치 동의 요청: %s", pip_pkg)
            try:
                from agent.safety_checker import SafetyReport, DangerLevel
                from agent.confirmation_manager import get_confirmation_manager
                report = SafetyReport(
                    level=DangerLevel.CAUTION,
                    matched_patterns=["pip install %s" % pip_pkg],
                    summary_kr="'%s' 패키지를 설치합니다. 출처를 확인하세요." % pip_pkg,
                    category="package_install",
                )
                confirmed = get_confirmation_manager().request_confirmation(
                    "pip install %s" % pip_pkg, report, self._say
                )
                if not confirmed:
                    logger.info("[Orchestrator] 패키지 설치 사용자 거부: %s", pip_pkg)
                    return False
            except Exception as exc:
                logger.debug("[Orchestrator] 확인 다이얼로그 생략 (비GUI 환경): %s", exc)
                return False

        # 패키지명이 유효한 PyPI 식별자인지 확인 (command injection 방지)
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", pip_pkg):
            logger.warning("[Orchestrator] 유효하지 않은 패키지명, 설치 거부: %s", pip_pkg)
            return False

        self._say("'%s' 패키지를 자동으로 설치합니다..." % pip_pkg)
        logger.info("[Orchestrator] 자동 pip install: %s", pip_pkg)
        try:
            # pip_pkg는 위에서 정규식으로 검증된 안전한 값입니다.
            result = subprocess.run(  # nosec B603 B607
                [sys.executable, "-m", "pip", "install", pip_pkg, "--quiet"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if result.returncode == 0:
                logger.info("[Orchestrator] 패키지 설치 완료: %s", pip_pkg)
                return True
            logger.warning("[Orchestrator] 패키지 설치 실패: %s | %s", pip_pkg, result.stderr[:200])
        except Exception as exc:
            logger.debug("[Orchestrator] pip install 오류: %s", exc)
        return False

    def _run_step(self, step: ActionStep, context: Dict[str, str]) -> ExecutionResult:
        self._inject_dom_suggestions(step, context, goal_hint=context.get("goal", ""))
        if step.step_type == "python":
            return self.executor.run_python(step.content, extra_globals={"step_outputs": dict(context)})
        return self.executor.run_shell(step.content) if step.step_type == "shell" else ExecutionResult(success=True, output="")

    def _inject_dom_suggestions(self, step: ActionStep, context: Dict[str, str], goal_hint: str = "") -> None:
        content = (getattr(step, "content", "") or "")
        if '"replan_on_dom": true' not in content.lower() and "replan_on_dom=True" not in content and "replan_on_dom" not in content.lower():
            return
        if suggest_next_actions is None:
            return
        try:
            state = self.executor.execution_globals.get("get_browser_state_detailed", lambda: {})()
            dom_state = state.get("dom_analysis") if isinstance(state, dict) else {}
            if not dom_state:
                return
            suggestions = suggest_next_actions(dom_state, goal_hint or context.get("goal", ""))
            context["dom_suggestions"] = json.dumps(suggestions, ensure_ascii=False)
        except Exception as exc:
            logger.debug(f"[Orchestrator] DOM suggestion 주입 생략: {exc}")

    def _verify(self, goal: str, step_results: List[StepResult]) -> Tuple[bool, str]:
        developer_precheck = self._verify_developer_goal_completion(goal, step_results)
        if developer_precheck is not None:
            return developer_precheck
        try:
            from agent.real_verifier import get_real_verifier
            v = get_real_verifier().verify(goal, step_results)
            return v.verified, v.summary_kr
        except Exception as exc:
            logger.debug(f"[Orchestrator] RealVerifier 폴백: {exc}")
        if any(not sr.exec_result.success for sr in step_results): return False, "일부 단계 실패"
        verdict = self.planner.verify(goal, [sr.exec_result for sr in step_results])
        return verdict.get("achieved", False), verdict.get("summary_kr", "검증 실패")

    def _verify_developer_goal_completion(self, goal: str, step_results: List[StepResult]) -> Optional[Tuple[bool, str]]:
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
            return False, "저장소 분석만 수행됐고 실제 코드 변경과 검증이 확인되지 않았습니다."
        if not has_code_change:
            return False, "저장소 분석은 수행됐지만 실제 코드 변경이 확인되지 않았습니다."
        if not has_validation:
            return False, "코드 변경은 있었지만 validate_repo.py 또는 관련 테스트 검증이 확인되지 않았습니다."
        return None

    def _apply_developer_step_guard(self, goal: str, sr: StepResult, context: Dict[str, str]) -> StepResult:
        if not self._is_developer_goal(goal):
            return sr
        exec_result = getattr(sr, "exec_result", None)
        if exec_result is None or not getattr(exec_result, "success", False):
            return sr
        error = self._find_developer_step_guard_error(goal, sr, context)
        if not error:
            return sr
        guarded_result = ExecutionResult(
            success=False,
            output=getattr(exec_result, "output", "") or "",
            error=error,
            duration_ms=getattr(exec_result, "duration_ms", 0),
            code_or_cmd=getattr(exec_result, "code_or_cmd", "") or "",
            state_before=getattr(exec_result, "state_before", None),
            state_after=getattr(exec_result, "state_after", None),
            state_delta=getattr(exec_result, "state_delta", None),
            state_delta_summary=getattr(exec_result, "state_delta_summary", "") or "",
        )
        return StepResult(
            step=sr.step,
            exec_result=guarded_result,
            attempt=sr.attempt,
            was_fixed=sr.was_fixed,
            failure_kind="developer_guard",
        )

    def _find_developer_step_guard_error(self, goal: str, sr: StepResult, context: Dict[str, str]) -> str:
        step = getattr(sr, "step", None)
        exec_result = getattr(sr, "exec_result", None)
        content = getattr(step, "content", "") or ""
        output = getattr(exec_result, "output", "") or ""
        for path in self._extract_developer_result_paths(output):
            if not self.planner.is_allowed_developer_path(path, goal=goal, context=context):
                return f"허용 범위를 벗어난 경로가 선택되어 개발 작업을 중단했습니다: {path}"
        if self._contains_invalid_developer_validation(content):
            return "허용되지 않은 개발 검증 명령이 계획에 포함되어 실행을 중단했습니다."
        return ""

    def _find_developer_scope_violation(self, goal: str, step_results: List[StepResult]) -> str:
        for sr in step_results:
            step = getattr(sr, "step", None)
            exec_result = getattr(sr, "exec_result", None)
            content = getattr(step, "content", "") or ""
            output = getattr(exec_result, "output", "") or ""
            for path in self._extract_developer_result_paths("\n".join([content, output])):
                if not self.planner.is_allowed_developer_path(path, goal=goal, context=None):
                    return f"허용 범위를 벗어난 파일/경로가 선택되어 작업을 완료로 볼 수 없습니다: {path}"
        return ""

    def _extract_developer_result_paths(self, text: str) -> List[str]:
        candidates: List[str] = []
        normalized_repo_root = os.path.abspath(os.getcwd()).replace("\\", "/").lower()

        def add_candidate(value: str) -> None:
            if not value:
                return
            normalized = str(value).strip().strip('"').strip("'").replace("\\", "/")
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
                for match in re.findall(r'(?:VoiceCommand|docs|tests|market|supabase|\.github|\.claude|\.idea)[/\\][A-Za-z0-9_./\\-]+', value, flags=re.IGNORECASE):
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

    def _contains_invalid_developer_validation(self, content: str) -> bool:
        normalized = (content or "").lower().replace("\\", "/")
        if "py_compile" in normalized or "&&" in normalized:
            return True
        if "tests/" in normalized and "voicecommand/tests/" not in normalized and "voicecommand.tests." not in normalized:
            return True
        return False

    def _is_valid_developer_validation_signal(self, combined: str) -> bool:
        normalized = (combined or "").lower().replace("\\", "/")
        if self._contains_invalid_developer_validation(normalized):
            return False
        return any(token in normalized for token in _DEVELOPER_VERIFY_TOKENS)

    def _record_strategy(self, goal: str, run_result: AgentRunResult, duration: int, lesson: str = ""):
        try:
            from agent.strategy_memory import get_strategy_memory
            failed = [sr for sr in run_result.step_results if not sr.exec_result.success]
            fk = failed[-1].failure_kind if failed else ""
            skill_id = ""
            is_dev_goal = self._is_developer_goal(goal)
            if not is_dev_goal:
                try:
                    from agent.skill_library import get_skill_library
                    matched = get_skill_library().get_applicable_skill(goal)
                    skill_id = matched.skill_id if matched and matched.confidence >= 0.45 else ""
                except Exception:
                    skill_id = ""
            get_strategy_memory().record(
                goal=goal,
                steps=[sr.step for sr in run_result.step_results],
                success=run_result.achieved,
                error="" if run_result.achieved else run_result.summary_kr,
                duration_ms=duration,
                failure_kind=fk,
                lesson=lesson,
                skill_id=skill_id,
                user_feedback="positive" if run_result.achieved and not is_dev_goal else "",
                few_shot_eligible=run_result.achieved and len(run_result.step_results) <= 5 and not is_dev_goal,
            )
        except Exception as e: logger.warning(f"[Orchestrator] StrategyMemory 기록 실패: {e}")

    def _post_run_update(self, goal: str, run_result: AgentRunResult, duration_ms: int):
        try:
            from agent.planner_feedback import get_planner_feedback_loop
            get_planner_feedback_loop().record(
                [sr.step for sr in run_result.step_results],
                run_result.achieved,
                duration_ms,
            )
        except Exception as e:
            logger.debug(f"[Orchestrator] planner feedback 업데이트 실패: {e}")
        if not self._is_developer_goal(goal):
            try:
                from agent.skill_library import get_skill_library
                get_skill_library().try_extract_skill(
                    goal,
                    [sr.step for sr in run_result.step_results],
                    run_result.achieved,
                    duration_ms,
                )
            except Exception as e:
                logger.debug(f"[Orchestrator] skill 추출 실패: {e}")
        try:
            from agent.episode_memory import GoalEpisode, get_episode_memory
            target_domains: List[str] = []
            target_windows: List[str] = []
            target_paths: List[str] = []
            state_changes: List[str] = []
            policy_summary = ""
            try:
                policy_summary = str((self.executor.get_runtime_state() or {}).get("execution_policy_summary", "") or "")[:300]
            except Exception:
                policy_summary = ""
            for sr in run_result.step_results:
                targets = extract_step_targets(getattr(sr.step, "content", "") or "")
                target_domains.extend(targets.get("domains", []))
                target_windows.extend(targets.get("windows", []))
                target_paths.extend(targets.get("paths", []))
                summary = str(getattr(sr.exec_result, "state_delta_summary", "") or "").strip()
                if summary:
                    state_changes.append(summary)
            get_episode_memory().record(
                GoalEpisode(
                    goal=goal,
                    achieved=run_result.achieved,
                    summary_kr=run_result.summary_kr,
                    failure_kind=next((sr.failure_kind for sr in run_result.step_results if sr.failure_kind), ""),
                    duration_ms=duration_ms,
                    target_domains=target_domains,
                    target_windows=target_windows,
                    target_paths=target_paths,
                    state_change_summary=" | ".join(state_changes[:3]),
                    policy_summary=policy_summary,
                )
            )
        except Exception as e:
            logger.debug(f"[Orchestrator] episode memory 기록 실패: {e}")
        if not run_result.achieved:
            try:
                from agent.reflection_engine import get_reflection_engine
                reflection = get_reflection_engine().reflect(goal, run_result)
                if reflection.lesson and reflection.lesson not in run_result.summary_kr:
                    run_result.summary_kr = f"{run_result.summary_kr}\n(교훈: {reflection.lesson})".strip()
            except Exception as e:
                logger.debug(f"[Orchestrator] reflection 생성 실패: {e}")

    def _build_adaptive_context(self, failed: List[StepResult]) -> Dict[str, str]:
        kinds = [sr.failure_kind for sr in failed if sr.failure_kind]
        errs = " | ".join([(sr.exec_result.error or sr.exec_result.output or "")[:100] for sr in failed])
        artifacts = extract_artifacts([sr.exec_result.output or "" for sr in failed] + [sr.exec_result.error or "" for sr in failed])
        ctx = {"재계획_이유": f"실행 실패 ({', '.join(set(kinds)) if kinds else '오류'})", "실패_오류": errs[:300]}
        target_hints = {
            "paths": [],
            "domains": [],
            "windows": [],
            "goal_hints": [],
        }
        for sr in failed:
            targets = extract_step_targets(getattr(sr.step, "content", "") or "")
            for key in target_hints:
                target_hints[key].extend(targets.get(key, []))
        state_summaries = [
            str(getattr(sr.exec_result, "state_delta_summary", "") or "").strip()
            for sr in failed
            if str(getattr(sr.exec_result, "state_delta_summary", "") or "").strip()
        ]
        if state_summaries:
            ctx["실패_후_상태변화"] = " | ".join(state_summaries[:3])[:400]
        if artifacts["paths"]:
            ctx["관측_경로"] = ", ".join(artifacts["paths"][:3])
        if artifacts["urls"]:
            ctx["관측_URL"] = ", ".join(artifacts["urls"][:3])
        if target_hints["paths"]:
            ctx["실패_대상_경로"] = ", ".join(list(dict.fromkeys(target_hints["paths"]))[:3])
        if target_hints["domains"]:
            ctx["실패_대상_도메인"] = ", ".join(list(dict.fromkeys(target_hints["domains"]))[:3])
        if target_hints["windows"]:
            ctx["실패_대상_창"] = ", ".join(list(dict.fromkeys(target_hints["windows"]))[:3])
        if target_hints["goal_hints"]:
            ctx["실패_goal_hint"] = ", ".join(list(dict.fromkeys(target_hints["goal_hints"]))[:3])
        try:
            recovery_targets = list(dict.fromkeys(target_hints["paths"]))[:5]
            candidates = self.executor.get_recovery_candidates(recovery_targets)
            if candidates:
                ctx["복구_가능_파일"] = ", ".join(candidate.get("target_path", "") for candidate in candidates[:3] if candidate.get("target_path"))
                ctx["복구_권장"] = "필요 시 get_recovery_candidates(...) 확인 후 restore_last_backup(path) 사용"
            guidance = self.executor.get_recovery_guidance(goal=failed[0].step.description_kr if failed else "", target_paths=recovery_targets)
            if guidance:
                ctx["복구_가이드"] = guidance[:500]
        except Exception as exc:
            logger.debug(f"[Orchestrator] recovery candidate 주입 생략: {exc}")
        return ctx

    def _update_runtime_context(self, context: Dict[str, str], exec_result: ExecutionResult) -> None:
        try:
            runtime_state = self.executor.get_runtime_state()
        except Exception:
            runtime_state = {}
        if runtime_state.get("active_window_title"):
            context["active_window_title"] = str(runtime_state["active_window_title"])[:200]
        if runtime_state.get("open_window_titles"):
            context["open_window_titles"] = ", ".join(runtime_state.get("open_window_titles", [])[:6])[:300]
        browser_state = runtime_state.get("browser_state") or {}
        if browser_state.get("current_url"):
            context["browser_current_url"] = str(browser_state.get("current_url"))[:200]
        if browser_state.get("title"):
            context["browser_title"] = str(browser_state.get("title"))[:200]
        desktop_state = runtime_state.get("desktop_state") or {}
        if desktop_state:
            context["desktop_state_json"] = json.dumps(desktop_state, ensure_ascii=False)[:500]
        learned_strategies = runtime_state.get("learned_strategies") or {}
        if learned_strategies:
            context["learned_strategies_json"] = json.dumps(learned_strategies, ensure_ascii=False)[:500]
        learned_strategy_summary = str(runtime_state.get("learned_strategy_summary", "") or "")
        if learned_strategy_summary:
            context["learned_strategy_summary"] = learned_strategy_summary[:300]
        planning_snapshot_summary = str(runtime_state.get("planning_snapshot_summary", "") or "")
        if planning_snapshot_summary:
            context["planning_snapshot_summary"] = planning_snapshot_summary[:400]
        planning_snapshot = runtime_state.get("planning_snapshot") or {}
        if planning_snapshot:
            context["planning_snapshot_json"] = json.dumps(planning_snapshot, ensure_ascii=False)[:500]
        execution_policy_summary = str(runtime_state.get("execution_policy_summary", "") or "")
        if execution_policy_summary:
            context["execution_policy_summary"] = execution_policy_summary[:400]
        execution_policy = runtime_state.get("execution_policy") or {}
        if execution_policy:
            context["execution_policy_json"] = json.dumps(execution_policy, ensure_ascii=False)[:500]
        last_state_delta_summary = str(runtime_state.get("last_state_delta_summary", "") or "")
        if last_state_delta_summary:
            context["last_state_delta_summary"] = last_state_delta_summary[:300]
        recent_state_transitions = runtime_state.get("recent_state_transitions") or []
        if recent_state_transitions:
            context["recent_state_transitions_json"] = json.dumps(recent_state_transitions, ensure_ascii=False)[:500]
        backup_history = runtime_state.get("backup_history") or []
        if backup_history:
            context["backup_history_json"] = json.dumps(backup_history, ensure_ascii=False)[:500]
        recovery_candidates = runtime_state.get("recovery_candidates") or []
        if recovery_candidates:
            context["recovery_candidates_json"] = json.dumps(recovery_candidates, ensure_ascii=False)[:500]
        recent_goal_episodes = str(runtime_state.get("recent_goal_episodes", "") or "")
        if recent_goal_episodes:
            context["recent_goal_episodes"] = recent_goal_episodes[:600]
        recovery_guidance = str(runtime_state.get("recovery_guidance", "") or "")
        if recovery_guidance:
            context["recovery_guidance"] = recovery_guidance[:500]
        context["last_step_success"] = str(exec_result.success)
        if exec_result.output:
            artifacts = extract_artifacts([exec_result.output])
            if artifacts["paths"]:
                context["last_artifact_paths"] = ", ".join(artifacts["paths"][:3])
            if artifacts["urls"]:
                context["last_artifact_urls"] = ", ".join(artifacts["urls"][:3])
        state_delta_summary = str(getattr(exec_result, "state_delta_summary", "") or "")
        if state_delta_summary:
            context["last_state_change"] = state_delta_summary[:300]
        step_targets = extract_step_targets(str(getattr(exec_result, "code_or_cmd", "") or ""))
        if step_targets["paths"]:
            context["last_target_paths"] = ", ".join(step_targets["paths"][:3])
        if step_targets["domains"]:
            context["last_target_domains"] = ", ".join(step_targets["domains"][:3])
        if step_targets["windows"]:
            context["last_target_windows"] = ", ".join(step_targets["windows"][:3])
        if step_targets["goal_hints"]:
            context["last_goal_hints"] = ", ".join(step_targets["goal_hints"][:3])
        if runtime_state:
            context["runtime_state_json"] = json.dumps(runtime_state, ensure_ascii=False)[:500]

    def _group_by_dependency(self, steps: List[ActionStep]) -> List[List[ActionStep]]:
        """parallel_group 우선, 없으면 기존 의존성 분석으로 실행 레이어 생성."""
        if not steps:
            return []

        explicit_groups = [step for step in steps if getattr(step, "parallel_group", -1) >= 0]
        if explicit_groups:
            # step_id 오름차순으로 순회하면서 sequential은 단독 리스트로,
            # 같은 parallel_group은 첫 등장 시 한 번만 묶어서 추가한다.
            # 이렇게 해야 원래 단계 순서가 보장된다.
            result: List[List[ActionStep]] = []
            seen_groups: set = set()
            for step in sorted(steps, key=lambda s: s.step_id):
                pg = getattr(step, "parallel_group", -1)
                if pg < 0:
                    result.append([step])
                elif pg not in seen_groups:
                    seen_groups.add(pg)
                    group_steps = sorted(
                        [s for s in steps if getattr(s, "parallel_group", -1) == pg],
                        key=lambda s: s.step_id,
                    )
                    result.append(group_steps)
            return result

        graph = {s.step_id: set() for s in steps}
        step_map = {s.step_id: s for s in steps}
        ordered_ids = [s.step_id for s in steps]
        step_positions = {step_id: idx for idx, step_id in enumerate(ordered_ids)}
        target_cache = {
            s.step_id: extract_step_targets((s.content or "") + "\n" + (s.description_kr or ""))
            for s in steps
        }

        for s in steps:
            # 1. 명시적 의존성 (step_X_output 참조)
            refs = re.findall(r"step_(\d+)_output", (s.content or "") + (s.condition or ""))
            for r in refs:
                ref_id = int(r)
                if ref_id in graph:
                    graph[s.step_id].add(ref_id)

            # 2. 암묵적 의존성 (경로/브라우저/GUI 상태 충돌)
            current_targets = target_cache[s.step_id]
            current_read_only = is_read_only_step_content(s.content, s.description_kr)
            current_stateful = mutates_runtime_state(s.content, s.description_kr)
            current_index = step_positions[s.step_id]

            for prev_id in ordered_ids[:current_index]:
                prev_step = step_map[prev_id]
                prev_targets = target_cache[prev_id]
                prev_read_only = is_read_only_step_content(prev_step.content, prev_step.description_kr)
                prev_stateful = mutates_runtime_state(prev_step.content, prev_step.description_kr)

                path_conflict = bool(
                    set(current_targets["paths"]) & set(prev_targets["paths"])
                )
                domain_conflict = bool(
                    set(current_targets["domains"]) & set(prev_targets["domains"])
                )
                window_conflict = bool(
                    set(current_targets.get("windows", [])) & set(prev_targets.get("windows", []))
                )
                goal_hint_conflict = bool(
                    set(current_targets.get("goal_hints", [])) & set(prev_targets.get("goal_hints", []))
                )
                state_conflict = current_stateful and prev_stateful

                if path_conflict or domain_conflict or window_conflict or goal_hint_conflict or state_conflict:
                    graph[s.step_id].add(prev_id)
                    continue

                if not current_read_only and not prev_read_only:
                    graph[s.step_id].add(prev_id)
                    continue

                if current_stateful and not prev_read_only:
                    graph[s.step_id].add(prev_id)

        # 위상 정렬 기반 레이어 분리
        layers, processed = [], set()
        while len(processed) < len(steps):
            current_layer = [s for s in steps if s.step_id not in processed and graph[s.step_id].issubset(processed)]
            if not current_layer: break
            layers.append(current_layer)
            processed.update(s.step_id for s in current_layer)
            
        return layers if layers else [[s] for s in steps] # 실패 시 순차 실행 폴백

    def _eval_condition(self, cond: str, ctx: Dict[str, str]) -> bool:
        try:
            parsed = ast.parse(cond, mode="eval")
            return bool(self._evaluate_condition_node(parsed, {"step_outputs": ctx}))
        except Exception as exc:
            logger.debug(f"[Orchestrator] 조건식 평가 폴백(True): {cond!r} ({exc})")
            return True

    def _evaluate_condition_node(self, node: ast.AST, scope: Dict[str, Any]) -> Any:
        if isinstance(node, ast.Expression):
            return self._evaluate_condition_node(node.body, scope)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in scope:
                return scope[node.id]
            raise ValueError(f"허용되지 않은 이름: {node.id}")
        if isinstance(node, ast.BoolOp):
            values = [bool(self._evaluate_condition_node(value, scope)) for value in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
            raise ValueError("허용되지 않은 BoolOp")
        if isinstance(node, ast.UnaryOp):
            operator = _UNARY_OPERATORS.get(type(node.op))
            if operator is None:
                raise ValueError("허용되지 않은 UnaryOp")
            return operator(self._evaluate_condition_node(node.operand, scope))
        if isinstance(node, ast.Compare):
            left = self._evaluate_condition_node(node.left, scope)
            for operator_node, comparator in zip(node.ops, node.comparators):
                right = self._evaluate_condition_node(comparator, scope)
                operator = _COMPARE_OPERATORS.get(type(operator_node))
                if operator is None or not operator(left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.Subscript):
            target = self._evaluate_condition_node(node.value, scope)
            key_node = node.slice  # Python 3.9+: ast.Index 제거됨, slice가 직접 노드
            key = self._evaluate_condition_node(key_node, scope)
            return target[key]
        if isinstance(node, ast.Call):
            return self._evaluate_condition_call(node, scope)
        if isinstance(node, (ast.List, ast.Tuple)):
            return [self._evaluate_condition_node(item, scope) for item in node.elts]
        raise ValueError(f"지원하지 않는 조건식 노드: {type(node).__name__}")

    def _evaluate_condition_call(self, node: ast.Call, scope: Dict[str, Any]) -> Any:
        if isinstance(node.func, ast.Name):
            func = _SAFE_AST_CALLS.get(node.func.id)
            if func is None:
                raise ValueError(f"허용되지 않은 함수: {node.func.id}")
            args = [self._evaluate_condition_node(arg, scope) for arg in node.args]
            return func(*args)

        if isinstance(node.func, ast.Attribute):
            owner = self._evaluate_condition_node(node.func.value, scope)
            allowed_methods = _SAFE_AST_METHODS.get(type(owner), set())
            if node.func.attr not in allowed_methods:
                raise ValueError(f"허용되지 않은 메서드: {node.func.attr}")
            args = [self._evaluate_condition_node(arg, scope) for arg in node.args]
            return getattr(owner, node.func.attr)(*args)

        raise ValueError("지원하지 않는 호출식")

    def _classify_failure(self, res: ExecutionResult) -> str:
        return classify_failure_message(res.error or res.output or "") if not res.success else ""

    def _say(self, msg: str):
        if self.tts: self.tts(msg)

    def _log_plan(self, steps: List[ActionStep]):
        logger.info(f"[Orchestrator] {len(steps)}단계 계획 수립됨")


_orchestrator: Optional[AgentOrchestrator] = None

def get_orchestrator(tts_func: Optional[Callable] = None, progress_callback: Optional[Callable] = None) -> AgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator(get_executor(tts_func), get_planner(), tts_func, progress_callback)
    else:
        if tts_func: _orchestrator.tts = tts_func; _orchestrator.executor.tts_wrapper = tts_func
        if progress_callback: _orchestrator.progress_callback = progress_callback
    return _orchestrator

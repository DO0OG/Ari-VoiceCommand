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
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Dict, Tuple

from agent_planner import AgentPlanner, ActionStep, get_planner
from autonomous_executor import AutonomousExecutor, ExecutionResult, get_executor

# executor._lock 경합 시 반환되는 오류 문자열 — self-fix 대상에서 제외
_LOCK_CONTENTION_ERRORS = frozenset({
    "이미 다른 코드가 실행 중입니다.",
    "이미 다른 명령이 실행 중입니다.",
})

_SAFE_EVAL_BUILTINS = {
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "any": any,
    "all": all,
}


# ── 데이터 클래스 ──────────────────────────────────────────────────────────────

@dataclass
class StepResult:
    step: ActionStep
    exec_result: ExecutionResult
    attempt: int = 1
    was_fixed: bool = False


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
    ):
        self.executor = executor
        self.planner = planner
        self.tts = tts_func
        self._run_lock = threading.Lock()

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def run(self, goal: str) -> AgentRunResult:
        """
        복잡한 목표를 다층 루프로 자율 달성.

        Layer 1 — Plan:    목표를 단계로 분해 (전략 기억 활용)
        Layer 2 — Execute: 독립 단계 병렬 실행 + 실패 시 LLM 자동 수정 + 재시도
                           on_failure 정책(abort/skip/continue) 및 condition 표현식 적용
        Layer 3 — Verify:  코드 실행 기반 검증 → LLM 텍스트 폴백
                           미달성 → 결과를 컨텍스트에 포함해 재계획
        """
        if not self._run_lock.acquire(blocking=False):
            return AgentRunResult(goal=goal, summary_kr="이미 에이전트가 실행 중입니다.")

        run_result = AgentRunResult(goal=goal)
        context: Dict[str, str] = {}
        start_time = time.time()

        try:
            for iteration in range(self.MAX_PLAN_ITERATIONS):
                run_result.total_iterations = iteration + 1
                logging.info(f"[Orchestrator] 계획 수립 (반복 {iteration+1}/{self.MAX_PLAN_ITERATIONS})")

                # ── Layer 1: Plan ──────────────────────────────────────────
                steps = self.planner.decompose(goal, context)
                if not steps:
                    run_result.summary_kr = "계획 수립에 실패했습니다."
                    break

                self._log_plan(steps)

                # ── Layer 2: Execute + Self-Fix (병렬 + 조건부) ────────────
                all_success, step_results = self._execute_plan(steps, context, goal)
                run_result.step_results.extend(step_results)

                if not all_success:
                    run_result.summary_kr = "실행 중 복구할 수 없는 오류가 발생했습니다."
                    break

                # ── Layer 3: Verify (코드 실행 기반 → LLM 폴백) ───────────
                achieved, summary = self._verify(goal, step_results)
                logging.info(f"[Orchestrator] 검증: achieved={achieved}, summary={summary}")

                if achieved:
                    run_result.achieved = True
                    run_result.summary_kr = summary
                    self._say(f"[기쁨] {summary}")
                    break
                else:
                    # 미달성 → 결과를 컨텍스트로 전달 후 재계획
                    context["이전_시도"] = summary
                    for i, sr in enumerate(step_results):
                        if sr.exec_result.output:
                            context[f"step{i}_output"] = sr.exec_result.output[:200]
                    self._say("[진지] 목표를 아직 달성하지 못했어요. 다시 시도합니다.")
            else:
                run_result.summary_kr = (
                    f"{self.MAX_PLAN_ITERATIONS}번 시도했지만 목표를 달성하지 못했습니다."
                )

        finally:
            self._run_lock.release()
            # 전략 기억 기록 (성공/실패 모두)
            duration_ms = int((time.time() - start_time) * 1000)
            self._record_strategy(goal, run_result, duration_ms)

        return run_result

    def execute_with_self_fix(
        self,
        code: str,
        step_type: str,
        goal: str,
    ) -> ExecutionResult:
        """
        단일 코드/명령 실행 + 자동 수정 루프.
        run() 없이 _handle_python/_handle_shell에서 직접 호출.
        실패하면 LLM이 코드를 수정하고 최대 MAX_STEP_RETRIES번 재시도.
        """
        step = ActionStep(
            step_id=0,
            step_type=step_type,
            content=code,
            description_kr="요청된 코드 실행",
        )
        result, attempt, was_fixed = self._execute_step_with_retry(step, goal, {})
        if was_fixed and result.success:
            logging.info(f"[Orchestrator] 자동 수정 성공 (시도 {attempt}회)")
        return result

    # ── 내부: 실행 계층 ────────────────────────────────────────────────────────

    def _execute_plan(
        self,
        steps: List[ActionStep],
        context: Dict[str, str],
        goal: str,
    ) -> Tuple[bool, List[StepResult]]:
        """
        단계 목록 실행.
        - 독립 단계는 병렬 그룹으로 묶어 동시 실행
        - 조건 표현식 평가로 건너뜀 처리
        - on_failure 정책(abort/skip/continue) 적용
        반환: (성공 여부, StepResult 목록)
        """
        step_results: List[StepResult] = []
        groups = self._group_by_dependency(steps)

        for group in groups:
            # think 단계: 실행 없이 컨텍스트 기록 (항상 단독 그룹)
            if len(group) == 1 and group[0].step_type == "think":
                step = group[0]
                logging.info(f"[Orchestrator] think: {step.description_kr}")
                step_results.append(StepResult(
                    step=step,
                    exec_result=ExecutionResult(success=True, output=step.description_kr),
                ))
                context[f"step_{step.step_id}_output"] = step.description_kr
                continue

            # 조건 평가 — 미충족 단계는 건너뜀으로 기록
            runnable: List[ActionStep] = []
            for step in group:
                if step.condition and not self._eval_condition(step.condition, context):
                    logging.info(
                        f"[Orchestrator] 단계 {step.step_id} 조건 미충족, 건너뜀: {step.condition!r}"
                    )
                    step_results.append(StepResult(
                        step=step,
                        exec_result=ExecutionResult(success=True, output="조건 미충족으로 건너뜀"),
                        attempt=0,
                    ))
                else:
                    runnable.append(step)

            if not runnable:
                continue

            # 병렬 실행 (단독 단계면 직접 호출로 오버헤드 최소화)
            if len(runnable) == 1:
                step = runnable[0]
                self._say(f"[진지] {step.description_kr}")
                result, attempt, was_fixed = self._execute_step_with_retry(step, goal, context)
                group_results = [StepResult(
                    step=step, exec_result=result, attempt=attempt, was_fixed=was_fixed,
                )]
            else:
                group_results = self._execute_parallel_group(runnable, context, goal)

            # on_failure 정책 적용
            for sr in group_results:
                step_results.append(sr)
                if sr.exec_result.success:
                    if sr.exec_result.output:
                        context[f"step_{sr.step.step_id}_output"] = sr.exec_result.output[:300]
                else:
                    policy = sr.step.on_failure
                    logging.warning(
                        f"[Orchestrator] 단계 {sr.step.step_id} 최종 실패 "
                        f"(on_failure={policy}): "
                        f"{(sr.exec_result.error or sr.exec_result.output or '')[:80]}"
                    )
                    if policy == "abort":
                        return False, step_results
                    # "skip" / "continue": 계속 실행

        return True, step_results

    def _execute_parallel_group(
        self,
        group: List[ActionStep],
        context: Dict[str, str],
        goal: str,
    ) -> List[StepResult]:
        """그룹 내 단계들을 ThreadPoolExecutor로 병렬 실행."""
        results: List[Optional[StepResult]] = [None] * len(group)

        def run_one(idx: int, step: ActionStep) -> StepResult:
            result, attempt, was_fixed = self._execute_step_with_retry(step, goal, context)
            return StepResult(step=step, exec_result=result, attempt=attempt, was_fixed=was_fixed)

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(group)) as pool:
            futures = {pool.submit(run_one, i, step): i for i, step in enumerate(group)}
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    step = group[idx]
                    logging.error(f"[Orchestrator] 병렬 단계 예외 (step {step.step_id}): {e}")
                    results[idx] = StepResult(
                        step=step,
                        exec_result=ExecutionResult(
                            success=False, error=str(e), code_or_cmd=step.content
                        ),
                    )

        return [r for r in results if r is not None]

    def _execute_step_with_retry(
        self,
        step: ActionStep,
        goal: str,
        context: Dict[str, str],
    ) -> Tuple[ExecutionResult, int, bool]:
        """
        실행 → 실패 시 LLM 코드 수정 → 재시도.
        락 경합 시: self-fix 없이 지수 백오프 후 재시도.
        반환: (ExecutionResult, 총 시도 횟수, 수정 여부)
        """
        current_step = step
        was_fixed = False
        exec_result = ExecutionResult(success=False, error="실행되지 않음")

        for attempt in range(1, self.MAX_STEP_RETRIES + 2):  # 최초 1 + 재시도
            exec_result = self._run_step(current_step, context)

            if exec_result.success:
                if was_fixed:
                    self._say("[기쁨] 자동 수정 후 성공했어요.")
                return exec_result, attempt, was_fixed

            # 마지막 시도였으면 포기
            if attempt > self.MAX_STEP_RETRIES:
                break

            error_msg = exec_result.error or exec_result.output or "알 수 없는 오류"

            # 락 경합: 코드 수정 없이 지수 백오프 대기 후 재시도
            if error_msg in _LOCK_CONTENTION_ERRORS:
                wait = attempt  # 1초, 2초, ...
                logging.warning(f"[Orchestrator] 실행기 잠김, {wait}초 대기 후 재시도")
                time.sleep(wait)
                continue

            logging.info(
                f"[Orchestrator] 단계 {step.step_id} 실패 (시도 {attempt}), "
                f"자동 수정 중... 오류: {error_msg[:80]}"
            )
            self._say(f"[걱정] 오류 발생, 자동으로 수정 중입니다. ({attempt}/{self.MAX_STEP_RETRIES})")

            fixed = self.planner.fix_step(current_step, error_msg, goal, context)
            if fixed and fixed.content and fixed.content != current_step.content:
                current_step = fixed
                was_fixed = True
                logging.info(f"[Orchestrator] 수정된 코드:\n{fixed.content[:200]}")
            else:
                logging.warning("[Orchestrator] LLM이 유효한 수정안을 제공하지 않음, 재시도 중단")
                break

        return exec_result, attempt, was_fixed

    def _run_step(self, step: ActionStep, context: Dict[str, str]) -> ExecutionResult:
        """단계 타입에 따라 executor 호출, 컨텍스트를 전역으로 주입"""
        if step.step_type == "python":
            if context:
                self.executor.execution_globals["step_outputs"] = dict(context)
            return self.executor.run_python(step.content)
        elif step.step_type == "shell":
            return self.executor.run_shell(step.content)
        else:
            return ExecutionResult(success=True, output="")

    # ── 내부: 검증 & 기억 ──────────────────────────────────────────────────────

    def _verify(self, goal: str, step_results: List[StepResult]) -> Tuple[bool, str]:
        """
        Layer 3 검증:
        1. RealVerifier — 검증 코드를 실제 실행하여 판단
        2. 폴백 — LLM 텍스트 기반 판단 (불확실, 보수적으로 처리)
        """
        try:
            from real_verifier import get_real_verifier
            vr = get_real_verifier()
            vresult = vr.verify(goal, step_results)
            return vresult.verified, vresult.summary_kr
        except Exception as e:
            logging.warning(f"[Orchestrator] RealVerifier 실패, LLM 텍스트 폴백: {e}")
            self._say("[걱정] 실제 상태 검증에 실패했어요. 실행 로그만으로 판단합니다.")

        # 폴백: 실패한 단계가 하나라도 있으면 미달성으로 처리
        failed = [sr for sr in step_results if not sr.exec_result.success]
        if failed:
            return False, f"{len(failed)}개 단계가 실패했습니다."

        exec_results = [sr.exec_result for sr in step_results]
        verdict = self.planner.verify(goal, exec_results)
        return verdict.get("achieved", False), verdict.get("summary_kr", "검증 실패")

    def _record_strategy(self, goal: str, run_result: AgentRunResult, duration_ms: int):
        """전략 기억에 실행 결과 기록 (실패 무시)"""
        try:
            from strategy_memory import get_strategy_memory
            steps = [sr.step for sr in run_result.step_results]
            error = "" if run_result.achieved else run_result.summary_kr
            get_strategy_memory().record(
                goal=goal,
                steps=steps,
                success=run_result.achieved,
                error=error,
                duration_ms=duration_ms,
            )
        except Exception as e:
            logging.warning(f"[Orchestrator] StrategyMemory 기록 실패: {e}")

    # ── 내부: 계획 유틸 ────────────────────────────────────────────────────────

    def _group_by_dependency(self, steps: List[ActionStep]) -> List[List[ActionStep]]:
        """
        모든 단계를 순차적으로 실행합니다.
        다단계 목표는 이전 단계 결과에 의존하므로 병렬 실행은 안전하지 않습니다.
        각 단계가 완료된 후 결과가 context에 반영되어야 다음 단계가 올바르게 실행됩니다.
        """
        return [[step] for step in steps]

    def _eval_condition(self, condition: str, context: Dict[str, str]) -> bool:
        """
        step.condition Python 표현식 평가.
        step_outputs 딕셔너리로 컨텍스트에 접근 가능.
        평가 실패 시 True(실행) 반환.
        """
        if not condition:
            return True
        try:
            step_outputs = dict(context)
            return bool(eval(  # noqa: S307
                condition,
                {"__builtins__": _SAFE_EVAL_BUILTINS, "step_outputs": step_outputs},
            ))
        except Exception as e:
            logging.warning(f"[Orchestrator] 조건 평가 실패 (True로 처리): {condition!r} → {e}")
            return True

    # ── 유틸 ──────────────────────────────────────────────────────────────────

    def _say(self, message: str):
        if self.tts and message:
            try:
                self.tts(message)
            except Exception:
                pass

    def _log_plan(self, steps: List[ActionStep]):
        logging.info(f"[Orchestrator] {len(steps)}단계 계획:")
        for s in steps:
            cond = f" [조건: {s.condition}]" if s.condition else ""
            logging.info(f"  [{s.step_id}] ({s.step_type}) {s.description_kr}{cond}")


# ── 싱글톤 ─────────────────────────────────────────────────────────────────────

_orchestrator: Optional[AgentOrchestrator] = None


def get_orchestrator(tts_func: Optional[Callable] = None) -> AgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        executor = get_executor(tts_func)
        planner = get_planner()
        _orchestrator = AgentOrchestrator(executor, planner, tts_func)
    else:
        if tts_func:
            _orchestrator.tts = tts_func
            _orchestrator.executor.tts_wrapper = tts_func
    return _orchestrator

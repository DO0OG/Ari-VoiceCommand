"""
에이전트 오케스트레이터 (Agent Orchestrator)
Plan → Execute+Self-Fix → Verify 다층 루프로 목표를 자율적으로 달성합니다.

사용 패턴:
  1. execute_with_self_fix(code, step_type, goal)
     단일 코드 실행 + 자동 수정 (기존 executor 대체)

  2. run(goal)
     복잡한 목표 → 다단계 계획 → 병렬 실행+자동수정 → 코드 기반 검증 → [재계획] 루프
"""
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional

from agent.agent_planner import AgentPlanner, ActionStep, get_planner
from agent.autonomous_executor import AutonomousExecutor, ExecutionResult, get_executor
from agent.execution_engine import ExecutionEngine, StepResult  # StepResult는 여기서 정의
from agent.verification_engine import VerificationEngine
from agent.learning_engine import LearningEngine

logger = logging.getLogger(__name__)

# StepResult를 execution_engine에서 임포트하여 re-export합니다.
# 기존 코드의 `from agent.agent_orchestrator import StepResult` 는 계속 동작합니다.
__all__ = ["AgentOrchestrator", "AgentRunResult", "StepResult", "get_orchestrator"]


# ── 데이터 클래스 ──────────────────────────────────────────────────────────────

@dataclass
class AgentRunResult:
    goal: str
    step_results: List[StepResult] = field(default_factory=list)
    achieved: bool = False
    summary_kr: str = ""
    total_iterations: int = 0
    learning_components: Dict[str, bool] = field(default_factory=dict)

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
        self._context_lock = threading.Lock()

        self._exec = ExecutionEngine(
            executor=executor,
            planner=planner,
            tts_func=tts_func,
            progress_callback=progress_callback,
            context_lock=self._context_lock,
        )
        self._verify_engine = VerificationEngine(planner=planner)
        self._learn = LearningEngine(
            is_developer_goal_fn=self._is_developer_goal,
            tts_func=tts_func,
            executor=executor,
        )

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def set_progress_callback(self, cb: Optional[Callable]) -> None:
        """진행 이벤트 콜백 설정. UI 대시보드 연결에 사용."""
        self.progress_callback = cb
        self._exec.progress_callback = cb

    def set_thinking_callback(self, cb: Optional[Callable]) -> None:
        """생각 중(Thinking) 상태 콜백 설정. 캐릭터 애니메이션 제어에 사용."""
        self.thinking_callback = cb

    def execute_with_self_fix(
        self,
        content: str,
        step_type: str,
        goal: str,
    ) -> ExecutionResult:
        """단일 단계 실행 + 자동 수정 (단순 도구 호출용)"""
        step = ActionStep(
            step_id=0,
            step_type=step_type,
            content=content,
            description_kr="단일 명령 실행",
        )
        res, _, _ = self._exec.execute_step_with_retry(step, goal, {})
        return res

    def run(self, goal: str) -> AgentRunResult:
        """복잡한 목표를 다층 루프로 자율 달성."""
        self._learn.wait_for_background_thread()
        if not self._run_lock.acquire(blocking=False):
            logger.warning("[Orchestrator] 이미 에이전트가 실행 중입니다.")
            return AgentRunResult(goal=goal, summary_kr="다른 작업이 진행 중입니다.")

        start_time = time.time()
        self._set_thinking(True)
        try:
            run_result = self._run_loop(goal)
            lesson = ""
            reflection = None
            if not run_result.achieved:
                reflection = self._learn.reflect_on_failure(goal, run_result)
                run_result.learning_components["ReflectionEngine"] = True
                lesson = getattr(reflection, "lesson", "") or ""
                if lesson:
                    run_result.summary_kr += f"\n(교훈: {lesson})"

            duration = int((time.time() - start_time) * 1000)
            self._learn.schedule_post_run_update(goal, run_result, duration)
            self._learn.record_learning_metrics(run_result)
            self._record_strategy(
                goal,
                run_result,
                duration,
                lesson=lesson,
                failure_kind_override=getattr(reflection, "root_cause", ""),
            )
            return run_result
        finally:
            self._set_thinking(False)
            self._run_lock.release()

    # ── 내부 루프 ─────────────────────────────────────────────────────────────

    def _run_loop(self, goal: str) -> AgentRunResult:
        """실제 Plan-Execute-Verify 루프"""
        run_result = AgentRunResult(goal=goal)
        context: Dict[str, str] = {"goal": goal}
        learning_components: Dict[str, bool] = {}

        try:
            from agent.episode_memory import get_episode_memory
            recent_episode_summary = get_episode_memory().get_recent_summary(
                goal=goal, limit=3
            )
            if recent_episode_summary:
                with self._context_lock:
                    context["recent_goal_episodes"] = recent_episode_summary[:600]
                learning_components["EpisodeMemory"] = True
        except Exception as exc:
            logger.debug("[Orchestrator] episode memory 주입 생략: %s", exc)

        try:
            from agent.goal_predictor import get_goal_predictor
            prediction = get_goal_predictor().warn_if_high_risk(goal)
            if prediction.warning_kr:
                learning_components["GoalPredictor"] = True
                with self._context_lock:
                    context["goal_risk_warning"] = prediction.warning_kr[:300]
                    if prediction.risk_factors:
                        context["goal_risk_factors"] = (
                            " | ".join(prediction.risk_factors[:3])[:300]
                        )
                self._emit_progress(
                    "risk_warning",
                    warning=prediction.warning_kr,
                    sample_size=prediction.sample_size,
                    success_rate=prediction.estimated_success_rate,
                )
                self._say(f"[진지] {prediction.warning_kr}")
        except Exception as exc:
            logger.debug("[Orchestrator] goal predictor 주입 생략: %s", exc)

        if self._should_prefer_template_over_skill(goal):
            logger.info("[Orchestrator] 안정 템플릿 우선 적용: skill 재사용 생략")
        else:
            skill_result = self._run_with_skill_if_available(
                goal, context, learning_components
            )
            if skill_result is not None:
                self._merge_learning_components(
                    skill_result.learning_components, learning_components
                )
                return skill_result

        for iteration in range(self.MAX_PLAN_ITERATIONS):
            run_result.total_iterations = iteration + 1
            logger.info(
                f"[Orchestrator] 계획 수립 (반복 {iteration+1}/{self.MAX_PLAN_ITERATIONS})"
            )

            # Layer 1: Plan
            steps = self.planner.decompose(goal, context)
            self._merge_learning_components(
                learning_components, self.planner.get_last_learning_signals()
            )
            if not steps:
                run_result.summary_kr = "계획 수립에 실패했습니다."
                break

            self._log_plan(steps)
            self._emit_progress(
                "plan_ready", steps=[asdict(s) for s in steps], iteration=iteration
            )

            # Layer 2: Execute + Self-Fix
            all_success, step_results = self._exec.execute_plan(
                steps, context, goal
            )
            run_result.step_results.extend(step_results)

            if not all_success:
                failed = [
                    sr for sr in step_results if not sr.exec_result.success
                ]
                adaptive_ctx = self._exec._build_adaptive_context(failed)
                with self._context_lock:
                    context.update(adaptive_ctx)
                reason = adaptive_ctx.get("재계획_이유", "실행 실패")
                self._emit_progress("replan", iteration=iteration, reason=reason)
                self._say("[진지] 접근 방법을 바꿔서 다시 시도합니다.")
                if iteration >= self.MAX_PLAN_ITERATIONS - 1:
                    run_result.summary_kr = f"실행 실패: {reason}"
                continue

            # Layer 3: Verify
            self._emit_progress("verify_start")
            achieved, summary = self._verify_engine.verify(goal, step_results)
            run_result.achieved = achieved
            run_result.summary_kr = summary

            if achieved:
                self._emit_progress("achieved", summary=summary)
                self._say(f"[기쁨] {summary}")
                break
            else:
                with self._context_lock:
                    context["이전_시도"] = summary
                self._emit_progress(
                    "not_achieved", summary=summary, iteration=iteration
                )
                self._say("[진지] 목표를 아직 달성하지 못했어요. 다시 시도합니다.")

        run_result.learning_components = learning_components
        return run_result

    # ── 스킬 실행 ─────────────────────────────────────────────────────────────

    def _should_prefer_template_over_skill(self, goal: str) -> bool:
        try:
            if self._is_developer_goal(goal):
                return True
            template_steps = self.planner._build_template_plan(goal)
        except Exception as exc:
            logger.debug("[Orchestrator] 템플릿 우선 판단 생략: %s", exc)
            return False
        return bool(template_steps)

    def _is_developer_goal(self, goal: str) -> bool:
        try:
            return bool(
                hasattr(self.planner, "is_developer_goal")
                and self.planner.is_developer_goal(goal)
            )
        except Exception:
            return False

    def _run_with_skill_if_available(
        self,
        goal: str,
        context: Dict[str, str],
        learning_components: Dict[str, bool],
    ) -> Optional[AgentRunResult]:
        try:
            from agent.skill_library import get_skill_library
            skill = get_skill_library().get_applicable_skill(goal)
            if not skill:
                return None
            learning_components["SkillLibrary"] = True

            # Direction 2: 컴파일된 Python 스킬 우선 실행
            if skill.compiled:
                result = self._run_compiled_skill(skill, goal)
                if result is not None:
                    with self._context_lock:
                        context["skill_id"] = skill.skill_id
                    result.learning_components["SkillLibrary"] = True
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
            all_success, step_results = self._exec.execute_plan(
                steps, context, goal
            )
            result = AgentRunResult(
                goal=goal, step_results=step_results, total_iterations=1
            )
            result.learning_components["SkillLibrary"] = True
            if all_success:
                achieved, summary = self._verify_engine.verify(goal, step_results)
                result.achieved = achieved
                result.summary_kr = summary
                if achieved:
                    with self._context_lock:
                        context["skill_id"] = skill.skill_id
                    get_skill_library().record_feedback(skill.skill_id, positive=True)
                    return result
            # 실패 시 에러 수집 후 자기수정 트리거
            error = " | ".join(
                (sr.exec_result.error or sr.exec_result.output or "")[:120]
                for sr in step_results
                if not sr.exec_result.success
            )
            get_skill_library().deprecate_if_failing(skill.skill_id, error=error)
        except Exception as e:
            logger.debug("[Orchestrator] skill 실행 생략: %s", e)
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
                logger.info("[Orchestrator] 컴파일 스킬 실행 성공: %s", skill.name)
                return result
            # 실패 → 코드 수정 트리거 후 None 반환 (스텝 폴백)
            logger.info(
                f"[Orchestrator] 컴파일 스킬 실패, 코드 수정 예약: {output[:100]}"
            )
            get_skill_library().record_feedback(
                skill.skill_id, positive=False, error=output
            )
            return None
        except Exception as exc:
            logger.debug("[Orchestrator] 컴파일 스킬 실행 오류: %s", exc)
            return None

    # ── 유틸리티 ──────────────────────────────────────────────────────────────

    def _merge_learning_components(
        self,
        target: Dict[str, bool],
        updates: Optional[Dict[str, bool]],
    ) -> None:
        for name, activated in dict(updates or {}).items():
            if activated:
                target[name] = True

    def _emit_progress(self, event_type: str, **kwargs) -> None:
        if self.progress_callback:
            try:
                self.progress_callback(event_type, **kwargs)
            except Exception as e:
                logger.debug("[Orchestrator] 진행 콜백 오류: %s", e)

    def _set_thinking(self, thinking: bool) -> None:
        if self.thinking_callback:
            try:
                self.thinking_callback(thinking)
            except Exception as e:
                logger.debug("[Orchestrator] 생각 콜백 오류: %s", e)

    def _say(self, msg: str) -> None:
        if self.tts:
            self.tts(msg)

    def _log_plan(self, steps: List[ActionStep]) -> None:
        logger.info("[Orchestrator] %d단계 계획 수립됨", len(steps))

    # ── 엔진 위임 proxy (테스트·외부 호환) ──────────────────────────────────────

    def _eval_condition(self, condition: str, context: dict) -> bool:
        return self._exec._eval_condition(condition, context)

    def _group_by_dependency(self, steps):
        return self._exec._group_by_dependency(steps)

    def _build_adaptive_context(self, failed_steps) -> dict:
        return self._exec._build_adaptive_context(failed_steps)

    def _execute_step_with_retry(self, step, goal: str, context: dict):
        return self._exec._execute_step_with_retry(step, goal, context)

    def _post_run_update(self, goal: str, run_result, duration_ms: int):
        return self._learn._post_run_update(goal, run_result, duration_ms)

    def _verify(self, goal: str, step_results) -> tuple:
        return self._verify_engine.verify(goal, step_results)

    def _update_runtime_context(self, context: dict, exec_result) -> None:
        return self._exec._update_runtime_context(context, exec_result)

    def _execute_plan(self, steps, context: dict, goal: str) -> tuple:
        return self._exec.execute_plan(steps, context, goal)

    def _record_strategy(self, goal: str, run_result, duration_ms: int, **kwargs) -> None:
        return self._learn.record_strategy(goal, run_result, duration_ms, **kwargs)


# ── 싱글턴 팩토리 ──────────────────────────────────────────────────────────────

_orchestrator: Optional[AgentOrchestrator] = None


def get_orchestrator(
    tts_func: Optional[Callable] = None,
    progress_callback: Optional[Callable] = None,
) -> AgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator(
            get_executor(tts_func), get_planner(), tts_func, progress_callback
        )
    else:
        if tts_func:
            _orchestrator.tts = tts_func
            _orchestrator.executor.tts_wrapper = tts_func
            _orchestrator._exec.tts = tts_func
            _orchestrator._learn.tts = tts_func
        if progress_callback:
            _orchestrator.progress_callback = progress_callback
            _orchestrator._exec.progress_callback = progress_callback
    return _orchestrator

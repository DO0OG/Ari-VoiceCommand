"""
에이전트 오케스트레이터 (Agent Orchestrator)
Plan → Execute+Self-Fix → Verify 다층 루프로 목표를 자율적으로 달성한다.

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
from i18n.translator import _

logger = logging.getLogger(__name__)

# StepResult를 execution_engine에서 임포트하여 re-export한다.
# 기존 코드의 `from agent.agent_orchestrator import StepResult` 는 계속 동작한다.
__all__ = ["AgentOrchestrator", "AgentRunResult", "StepResult", "get_orchestrator"]


# ── 데이터 클래스 ──────────────────────────────────────────────────────────────

@dataclass
class AgentRunResult:
    goal: str
    step_results: List[StepResult] = field(default_factory=list)
    achieved: bool = False
    summary: str = ""
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
            return AgentRunResult(goal=goal, summary=_("다른 작업이 진행 중입니다."))

        start_time = time.time()
        self._set_thinking(True)
        try:
            shared_context = self._build_shared_context(goal)
            run_result = self._run_loop(goal, shared_context=shared_context)
            lesson = ""
            reflection = None
            if not run_result.achieved:
                reflection = self._learn.reflect_on_failure(goal, run_result)
                run_result.learning_components["ReflectionEngine"] = True
                lesson = getattr(reflection, "lesson", "") or ""
                if lesson:
                    run_result.summary += _("\n(교훈: {lesson})").format(lesson=lesson)
                    retry_context = {
                        "reflection_insight": lesson,
                        "avoid_patterns": " | ".join(
                            getattr(reflection, "avoid_patterns", [])[:3]
                        ),
                    }
                    retry_result = self._run_loop(
                        goal,
                        reflection_context=retry_context,
                        shared_context=shared_context,
                    )
                    if retry_result.achieved:
                        retry_result.learning_components["ReflectionEngine"] = True
                        run_result = retry_result
            else:
                self._learn.schedule_reflection(
                    goal,
                    run_result,
                    callback=lambda reflection_result: self._learn.record_reflection_lesson(
                        goal,
                        reflection_result,
                    ),
                )

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

    def _run_loop(
        self,
        goal: str,
        reflection_context: Optional[Dict[str, str]] = None,
        shared_context: Optional[Dict[str, str]] = None,
    ) -> AgentRunResult:
        """실제 Plan-Execute-Verify 루프"""
        run_result = AgentRunResult(goal=goal)
        context: Dict[str, str] = {"goal": goal}
        learning_components: Dict[str, bool] = {}

        if shared_context and shared_context.get("recent_goal_episodes"):
            learning_components["EpisodeMemory"] = True
        if shared_context and shared_context.get("goal_risk_warning"):
            learning_components["GoalPredictor"] = True

        context_init: Dict[str, str] = {}
        if shared_context:
            context_init.update({
                str(key): str(value)
                for key, value in shared_context.items()
                if value
            })
        if reflection_context:
            context_init.update({
                str(key): str(value)
                for key, value in reflection_context.items()
                if value
            })
        if context_init:
            with self._context_lock:
                context.update(context_init)

        if self._should_prefer_template_over_skill(goal):
            logger.info("[Orchestrator] 안정 템플릿 우선 적용: skill 재사용 생략")
        else:
            skill_result = self._run_with_skill_if_available(
                goal, context, learning_components
            )
            if skill_result is not None:
                self._merge_learning_components(learning_components, skill_result.learning_components)
                skill_result.learning_components = learning_components
                return skill_result

        difficulty = self._estimate_goal_difficulty(goal)
        max_iterations = max(2, min(2 + round(difficulty * 4), 6))
        logger.info("[Orchestrator] 목표 난이도 %.2f → 최대 %d회 반복", difficulty, max_iterations)
        replan_reasons: list[str] = []

        for iteration in range(max_iterations):
            run_result.total_iterations = iteration + 1
            logger.info(
                f"[Orchestrator] 계획 수립 (반복 {iteration+1}/{max_iterations})"
            )

            # Layer 1: Plan
            timeout_hint = context.pop("이전_단계_타임아웃", "")
            if timeout_hint:
                with self._context_lock:
                    context["재계획_힌트"] = (
                        f"{context.get('재계획_힌트', '')} {timeout_hint}"
                    ).strip()
            steps = self.planner.decompose(goal, context)
            self._merge_learning_components(
                learning_components, self.planner.get_last_learning_signals()
            )
            if not steps:
                run_result.summary = "계획 수립에 실패했습니다."
                break
            prevalidation_issues = self._prevalidate_steps(steps)
            if prevalidation_issues:
                reason = " | ".join(prevalidation_issues[:3])
                logger.warning("[Orchestrator] 사전 검증 실패, 재계획: %s", reason)
                with self._context_lock:
                    context["이전_시도"] = reason
                self._emit_progress(
                    "replan",
                    iteration=iteration,
                    reason=reason,
                )
                reason_sig = reason[:80]
                if reason_sig in replan_reasons:
                    logger.info("[Orchestrator] 동일 재계획 이유 반복, 루프 조기 종료: %s", reason_sig)
                    run_result.summary = _("반복 실패 패턴 감지: {reason}", reason=reason)
                    break
                replan_reasons.append(reason_sig)
                if iteration >= max_iterations - 1:
                    run_result.summary = f"사전 검증 실패: {reason}"
                continue

            self._log_plan(steps)
            self._emit_progress(
                "plan_ready", steps=[asdict(s) for s in steps], iteration=iteration
            )

            # Layer 2: Execute + Self-Fix
            all_success, step_results = self._execute_plan(
                steps, context, goal
            )
            run_result.step_results.extend(step_results)

            if not all_success:
                failed = [
                    sr for sr in step_results if not sr.exec_result.success
                ]
                adaptive_ctx = self._build_adaptive_context(failed)
                with self._context_lock:
                    context.update(adaptive_ctx)
                reason = adaptive_ctx.get("재계획_이유", "실행 실패")
                self._emit_progress("replan", iteration=iteration, reason=reason)
                self._say("[진지] 접근 방법을 바꿔서 다시 시도합니다.")
                reason_sig = reason[:80]
                if reason_sig in replan_reasons:
                    logger.info("[Orchestrator] 동일 재계획 이유 반복, 루프 조기 종료: %s", reason_sig)
                    run_result.summary = _("반복 실패 패턴 감지: {reason}", reason=reason)
                    break
                replan_reasons.append(reason_sig)
                if iteration >= max_iterations - 1:
                    run_result.summary = f"실행 실패: {reason}"
                continue

            # Layer 3: Verify
            self._emit_progress("verify_start")
            achieved, summary = self._verify_engine.verify(goal, step_results)
            run_result.achieved = achieved
            run_result.summary = summary

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
                reason_sig = summary[:80]
                if reason_sig in replan_reasons:
                    logger.info("[Orchestrator] 동일 재계획 이유 반복, 루프 조기 종료: %s", reason_sig)
                    run_result.summary = _("반복 실패 패턴 감지: {reason}", reason=summary)
                    break
                replan_reasons.append(reason_sig)

        run_result.learning_components = learning_components
        return run_result

    def _build_shared_context(self, goal: str) -> Dict[str, str]:
        """루프 진입 전 1회만 실행해야 하는 고비용 검색을 수행한다."""
        from agent.learning_metrics import get_learning_metrics

        metrics = get_learning_metrics()
        additions: Dict[str, str] = {}
        should_activate = getattr(metrics, "should_activate", lambda *args, **kwargs: True)

        if should_activate("EpisodeMemory"):
            try:
                from agent.episode_memory import get_episode_memory

                summary = get_episode_memory().get_recent_summary(goal=goal, limit=3)
                if summary:
                    additions["recent_goal_episodes"] = summary[:600]
            except Exception as exc:
                logger.debug("[Orchestrator] episode memory 생략: %s", exc)

        if should_activate("GoalPredictor"):
            try:
                from agent.goal_predictor import get_goal_predictor

                prediction = get_goal_predictor().warn_if_high_risk(goal)
                if prediction.warning:
                    additions["goal_risk_warning"] = prediction.warning[:300]
                    if prediction.risk_factors:
                        additions["goal_risk_factors"] = (
                            " | ".join(prediction.risk_factors[:3])[:300]
                        )
                    self._emit_progress(
                        "risk_warning",
                        warning=prediction.warning,
                        sample_size=prediction.sample_size,
                        success_rate=prediction.estimated_success_rate,
                    )
                    self._say(f"[진지] {prediction.warning}")
            except Exception as exc:
                logger.debug("[Orchestrator] goal predictor 생략: %s", exc)

        return additions

    def _estimate_goal_difficulty(self, goal: str) -> float:
        """목표의 예상 복잡도를 0.0~1.0으로 반환한다."""
        from i18n.translator import get_language

        connectors_by_language: dict[str, list[str]] = {
            "ko": ["그리고", "다음에", "이후에", "후에", "그 다음", "마지막으로"],
            "en": ["and then", "next", "after that", "then", "finally"],
            "ja": ["そして", "次に", "その後", "最後に"],
        }
        connectors = connectors_by_language.get(get_language(), connectors_by_language["ko"])
        normalized_goal = str(goal or "")

        score = min(sum(1 for connector in connectors if connector in normalized_goal) * 0.15, 0.45)

        try:
            from agent.tag_keywords import TAG_KEYWORDS

            matched_domains = sum(
                1
                for keywords in TAG_KEYWORDS.values()
                if any(keyword.lower() in normalized_goal.lower() for keyword in keywords)
            )
            if matched_domains >= 3:
                score += 0.3
            elif matched_domains >= 2:
                score += 0.15
        except Exception:
            pass

        try:
            from agent.strategy_memory import get_strategy_memory

            similar = get_strategy_memory().search_similar_records(goal, limit=3)
            if similar:
                avg_steps = sum(len(record.steps_desc or []) for record in similar) / len(similar)
                if avg_steps > 5:
                    score += 0.25
        except Exception:
            pass

        return min(score, 1.0)

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
                    optional=bool(item.get("optional", False)),
                )
                for idx, item in enumerate(skill.steps)
            ]
            all_success, step_results = self._execute_plan(
                steps, context, goal
            )
            result = AgentRunResult(
                goal=goal, step_results=step_results, total_iterations=1
            )
            result.learning_components["SkillLibrary"] = True
            if all_success:
                achieved, summary = self._verify_engine.verify(goal, step_results)
                result.achieved = achieved
                result.summary = summary
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
                result.summary = output
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

    def _prevalidate_steps(self, steps: List[ActionStep]) -> List[str]:
        issues: List[str] = []
        for step in steps:
            if step.step_type == "shell" and not step.content.strip():
                issues.append(f"빈 shell 명령 감지: {step.step_id}")
                continue
            if step.step_type != "python" or not step.content.strip():
                continue
            try:
                from agent.safety_checker import DangerLevel, get_safety_checker

                report = get_safety_checker().check_python(step.content)
                if report.level == DangerLevel.DANGEROUS:
                    issues.append(f"위험 코드 감지: {step.step_id}")
            except Exception as exc:
                logger.debug("[Orchestrator] 사전 검증 생략(step=%s): %s", step.step_id, exc)
        return issues

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
        return self._exec.execute_plan(steps, context, goal, step_runner=self._execute_step_with_retry)

    def _record_strategy(self, goal: str, run_result, duration_ms: int, **kwargs) -> None:
        return self._learn.record_strategy(goal, run_result, duration_ms, **kwargs)


# ── 싱글턴 팩토리 ──────────────────────────────────────────────────────────────

_orchestrator: Optional[AgentOrchestrator] = None
_orchestrator_lock = threading.Lock()


def get_orchestrator(
    tts_func: Optional[Callable] = None,
    progress_callback: Optional[Callable] = None,
) -> AgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        with _orchestrator_lock:
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

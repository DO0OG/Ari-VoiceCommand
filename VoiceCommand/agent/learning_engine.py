"""
학습 엔진 (Learning Engine)
실행 결과를 전략 메모리·에피소드 메모리·학습 지표에 기록하고,
플래너 피드백 루프 업데이트와 실패 반성(Reflection)을 담당합니다.
"""
import logging
import threading
from typing import Callable, Dict, List, Optional

from agent.execution_analysis import extract_step_targets

logger = logging.getLogger(__name__)


class LearningEngine:
    """학습·기록·반성 담당 엔진"""

    def __init__(
        self,
        is_developer_goal_fn: Callable[[str], bool],
        tts_func: Optional[Callable] = None,
        background_updates_enabled: bool = True,
        executor=None,
    ):
        self._is_developer_goal = is_developer_goal_fn
        self.tts = tts_func
        self._background_updates_enabled = background_updates_enabled
        self._post_run_thread: Optional[threading.Thread] = None
        self._executor = executor  # policy_summary 조회용 (선택적)

    # ── 공개 메서드 ────────────────────────────────────────────────────────────

    def wait_for_background_thread(self) -> None:
        """이전 백그라운드 스레드가 살아있으면 종료를 기다립니다."""
        if self._post_run_thread is not None and self._post_run_thread.is_alive():
            self._post_run_thread.join(timeout=5.0)

    def schedule_post_run_update(
        self,
        goal: str,
        run_result,
        duration_ms: int,
    ) -> None:
        """플래너 피드백·스킬 추출·에피소드 기록을 백그라운드(또는 인라인)로 실행."""
        policy_summary = self._get_policy_summary()
        if not self._background_updates_enabled:
            self._post_run_update(goal, run_result, duration_ms, policy_summary)
            return
        t = threading.Thread(
            target=self._post_run_update_safe,
            args=(goal, run_result, duration_ms, policy_summary),
            daemon=True,
            name="AriPostRunUpdate",
        )
        self._post_run_thread = t
        t.start()

    def _get_policy_summary(self) -> str:
        """executor로부터 현재 execution_policy_summary를 조회합니다."""
        if self._executor is None:
            return ""
        try:
            return str(
                (self._executor.get_runtime_state() or {}).get(
                    "execution_policy_summary", ""
                ) or ""
            )[:300]
        except Exception:
            return ""

    def record_learning_metrics(self, run_result) -> None:
        """각 학습 컴포넌트의 활성화 여부·성공 여부를 metrics에 기록합니다."""
        try:
            from agent.learning_metrics import get_learning_metrics
            metrics = get_learning_metrics()
            component_names = (
                "GoalPredictor",
                "StrategyMemory",
                "EpisodeMemory",
                "FewShot",
                "PlannerFeedback",
                "SkillLibrary",
                "ReflectionEngine",
            )
            usage = dict(run_result.learning_components or {})
            for name in component_names:
                metrics.record(
                    name,
                    activated=bool(usage.get(name, False)),
                    success=bool(run_result.achieved),
                )
        except Exception as exc:
            logger.debug("[LearningEngine] learning metrics 기록 실패: %s", exc)

    def record_strategy(
        self,
        goal: str,
        run_result,
        duration: int,
        lesson: str = "",
        failure_kind_override: str = "",
    ) -> None:
        """StrategyMemory에 이번 실행 결과를 기록합니다."""
        try:
            from agent.strategy_memory import get_strategy_memory
            failed = [
                sr for sr in run_result.step_results
                if not sr.exec_result.success
            ]
            fk = failure_kind_override or (
                failed[-1].failure_kind if failed else ""
            )
            skill_id = ""
            is_dev_goal = self._is_developer_goal(goal)
            if not is_dev_goal:
                try:
                    from agent.skill_library import get_skill_library
                    matched = get_skill_library().get_applicable_skill(goal)
                    skill_id = (
                        matched.skill_id
                        if matched and matched.confidence >= 0.45
                        else ""
                    )
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
                few_shot_eligible=(
                    run_result.achieved
                    and len(run_result.step_results) <= 5
                    and not is_dev_goal
                ),
            )
        except Exception as e:
            logger.warning("[LearningEngine] StrategyMemory 기록 실패: %s", e)

    def reflect_on_failure(self, goal: str, run_result):
        """실패한 시나리오에 대해 ReflectionEngine 단일 경로로 반성 수행."""
        from agent.reflection_engine import get_reflection_engine
        return get_reflection_engine().reflect(goal, run_result)

    # ── 내부 메서드 ────────────────────────────────────────────────────────────

    def _post_run_update_safe(
        self,
        goal: str,
        run_result,
        duration_ms: int,
        policy_summary: str = "",
    ) -> None:
        try:
            self._post_run_update(goal, run_result, duration_ms, policy_summary)
        except Exception as exc:
            logger.debug(
                "[LearningEngine] background post-run update 실패: %s", exc
            )

    def _post_run_update(
        self,
        goal: str,
        run_result,
        duration_ms: int,
        policy_summary: str = "",
    ) -> None:
        # 1. 플래너 피드백 기록
        try:
            from agent.planner_feedback import get_planner_feedback_loop
            feedback_loop = get_planner_feedback_loop()
            steps = [sr.step for sr in run_result.step_results]
            feedback_loop.record(
                steps,
                run_result.achieved,
                duration_ms,
                tags=feedback_loop.infer_tags(goal=goal, steps=steps),
            )
        except Exception as e:
            logger.debug("[LearningEngine] planner feedback 업데이트 실패: %s", e)

        # 2. 스킬 추출 (개발자 목표 제외)
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
                logger.debug("[LearningEngine] skill 추출 실패: %s", e)

        # 3. 에피소드 메모리 기록
        try:
            from agent.episode_memory import GoalEpisode, get_episode_memory
            target_domains: List[str] = []
            target_windows: List[str] = []
            target_paths: List[str] = []
            state_changes: List[str] = []
            for sr in run_result.step_results:
                targets = extract_step_targets(
                    getattr(sr.step, "content", "") or ""
                )
                target_domains.extend(targets.get("domains", []))
                target_windows.extend(targets.get("windows", []))
                target_paths.extend(targets.get("paths", []))
                summary = str(
                    getattr(sr.exec_result, "state_delta_summary", "") or ""
                ).strip()
                if summary:
                    state_changes.append(summary)
            mem = get_episode_memory()
            mem.record(
                GoalEpisode(
                    goal=goal,
                    achieved=run_result.achieved,
                    summary_kr=run_result.summary_kr,
                    failure_kind=next(
                        (
                            sr.failure_kind
                            for sr in run_result.step_results
                            if sr.failure_kind
                        ),
                        "",
                    ),
                    duration_ms=duration_ms,
                    target_domains=target_domains,
                    target_windows=target_windows,
                    target_paths=target_paths,
                    state_change_summary=" | ".join(state_changes[:3]),
                    policy_summary=policy_summary,
                )
            )
            try:
                mem.prune_old_failures(max_age_days=30)
            except Exception as prune_exc:
                logger.debug(
                    "[LearningEngine] episode prune 실패: %s", prune_exc
                )
        except Exception as e:
            logger.debug("[LearningEngine] episode memory 기록 실패: %s", e)

"""
실행 엔진 (Execution Engine)
단계 실행, 병렬/순차 그룹핑, 조건 평가, 자동 수정, pip 설치,
런타임 컨텍스트 갱신, 개발자 가드를 담당합니다.
"""
import concurrent.futures
import json
import logging
import os
import re
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from dataclasses import dataclass

from agent.agent_planner import AgentPlanner, ActionStep
from agent.condition_evaluator import evaluate_condition
from agent.autonomous_executor import AutonomousExecutor, ExecutionResult
from agent.execution_analysis import (
    classify_failure_message,
    extract_artifacts,
    extract_step_targets,
    is_read_only_step_content,
    mutates_runtime_state,
)

logger = logging.getLogger(__name__)


# ── 데이터 클래스 ──────────────────────────────────────────────────────────────
# StepResult를 execution_engine에 정의하여 agent_orchestrator와의 순환 임포트를 방지합니다.

@dataclass
class StepResult:
    step: ActionStep
    exec_result: ExecutionResult
    attempt: int = 1
    was_fixed: bool = False
    failure_kind: str = ""

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

# ── 데이터 클래스 (순환 임포트 방지를 위해 여기서 재임포트하지 않고 인라인 사용) ──


class ExecutionEngine:
    """단계 실행·그룹핑·자동 수정·컨텍스트 갱신 담당"""

    MAX_STEP_RETRIES = 2  # 단계 당 자동 수정 최대 횟수

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

    def __init__(
        self,
        executor: AutonomousExecutor,
        planner: AgentPlanner,
        tts_func: Optional[Callable] = None,
        progress_callback: Optional[Callable] = None,
        context_lock: Optional[threading.Lock] = None,
    ):
        self.executor = executor
        self.planner = planner
        self.tts = tts_func
        self.progress_callback = progress_callback
        self._context_lock = context_lock or threading.Lock()

    # ── 공개 메서드 ────────────────────────────────────────────────────────────

    def execute_plan(
        self,
        steps: List[ActionStep],
        context: Dict[str, str],
        goal: str,
        step_runner=None,
    ) -> Tuple[bool, List]:
        """ActionStep 목록을 실행하고 (전체 성공 여부, StepResult 목록) 반환."""
        runner = step_runner or self._execute_step_with_retry
        step_results: List[StepResult] = []
        groups = self._group_by_dependency(steps)

        for group in groups:
            if len(group) == 1 and group[0].step_type == "think":
                step = group[0]
                step_results.append(
                    StepResult(
                        step=step,
                        exec_result=ExecutionResult(success=True, output=step.description_kr),
                    )
                )
                with self._context_lock:
                    context[f"step_{step.step_id}_output"] = step.description_kr
                continue

            runnable = [
                s for s in group
                if not s.condition or self._eval_condition(s.condition, context)
            ]
            if not runnable:
                continue

            if len(runnable) == 1:
                step = runnable[0]
                self._emit_progress(
                    "step_start",
                    step_id=step.step_id,
                    desc=step.description_kr,
                    step_type=step.step_type,
                )
                result, attempt, fixed = runner(step, goal, context)
                group_results = [
                    StepResult(
                        step=step,
                        exec_result=result,
                        attempt=attempt,
                        was_fixed=fixed,
                        failure_kind=self._classify_failure(result),
                    )
                ]
            else:
                for s in runnable:
                    self._emit_progress(
                        "step_start",
                        step_id=s.step_id,
                        desc=s.description_kr,
                        step_type=s.step_type,
                    )
                group_results = self._execute_parallel_group(runnable, context, goal, runner)

            for sr in group_results:
                sr = self._apply_developer_step_guard(goal, sr, context)
                step_results.append(sr)
                self._emit_progress(
                    "step_done",
                    step_id=sr.step.step_id,
                    success=sr.exec_result.success,
                    was_fixed=sr.was_fixed,
                    error=(sr.exec_result.error or "")[:100],
                )
                if sr.exec_result.success:
                    if sr.exec_result.output:
                        _out_limit = 2000 if self._is_developer_goal(goal) else 300
                        with self._context_lock:
                            context[f"step_{sr.step.step_id}_output"] = (
                                sr.exec_result.output[:_out_limit]
                            )
                    self._update_runtime_context(context, sr.exec_result)
                elif sr.step.on_failure == "abort":
                    return False, step_results

        return True, step_results

    def execute_step_with_retry(
        self,
        step: ActionStep,
        goal: str,
        context: Dict[str, str],
    ) -> Tuple[ExecutionResult, int, bool]:
        """공개 래퍼 — 단일 단계 실행 + 자동 수정."""
        return self._execute_step_with_retry(step, goal, context)

    # ── 내부 메서드 ────────────────────────────────────────────────────────────

    def _execute_step_with_retry(
        self,
        step: ActionStep,
        goal: str,
        context: Dict[str, str],
    ) -> Tuple[ExecutionResult, int, bool]:
        curr, fixed = step, False
        res = ExecutionResult(success=False, error="실행되지 않음")
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
                logger.info("[ExecutionEngine] 패키지 설치 후 단계 재실행")
                continue
            self._say("[걱정] 오류 발생, 수정 중입니다. (%d/%d)" % (att, self.MAX_STEP_RETRIES))
            f = self.planner.fix_step(curr, err, goal, context)
            if f and f.content and f.content != curr.content:
                curr, fixed = f, True
            else:
                break
        self._auto_restore_failed_writes(curr, res)
        return res, att, fixed

    def _auto_restore_failed_writes(
        self,
        step: ActionStep,
        exec_result: ExecutionResult,
    ) -> None:
        if exec_result.success:
            return
        restore = getattr(self.executor, "restore_last_backup", None)
        if not callable(restore):
            return
        targets = []
        for target in getattr(step, "writes", None) or []:
            if target and target not in targets:
                targets.append(target)
        if not targets:
            return
        restored_targets = []
        for target in targets:
            try:
                restore(target)
                restored_targets.append(target)
            except Exception as exc:
                logger.warning(
                    "[ExecutionEngine] 자동 복구 실패 (%s): %s",
                    target,
                    exc,
                )
        if restored_targets:
            logger.info(
                "[ExecutionEngine] 파일 작업 실패 — 백업 자동 복구: %s",
                ", ".join(restored_targets),
            )
            note = "자동 복구: " + ", ".join(restored_targets)
            exec_result.output = f"{exec_result.output}\n{note}".strip()

    def _execute_parallel_group(
        self,
        group: List[ActionStep],
        context: Dict[str, str],
        goal: str,
        step_runner=None,
    ) -> List:
        runner = step_runner or self._execute_step_with_retry
        results = [None] * len(group)

        def run_one(idx, step):
            res, att, fixed = runner(step, goal, context)
            return StepResult(
                step=step,
                exec_result=res,
                attempt=att,
                was_fixed=fixed,
                failure_kind=self._classify_failure(res),
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(group)) as pool:
            futures = {pool.submit(run_one, i, s): i for i, s in enumerate(group)}
            for f in concurrent.futures.as_completed(futures):
                idx = futures[f]
                try:
                    results[idx] = f.result()
                except Exception as e:
                    results[idx] = StepResult(
                        step=group[idx],
                        exec_result=ExecutionResult(success=False, error=str(e)),
                        failure_kind="runtime_exception",
                    )
        return [r for r in results if r]

    def _run_step(self, step: ActionStep, context: Dict[str, str]) -> ExecutionResult:
        self._inject_dom_suggestions(step, context, goal_hint=context.get("goal", ""))
        if step.step_type == "python":
            return self.executor.run_python(
                step.content,
                extra_globals={"step_outputs": dict(context)},
            )
        if step.step_type == "shell":
            return self.executor.run_shell(step.content)
        return ExecutionResult(success=True, output="")

    def _inject_dom_suggestions(
        self,
        step: ActionStep,
        context: Dict[str, str],
        goal_hint: str = "",
    ) -> None:
        content = getattr(step, "content", "") or ""
        if (
            '"replan_on_dom": true' not in content.lower()
            and "replan_on_dom=True" not in content
            and "replan_on_dom" not in content.lower()
        ):
            return
        if suggest_next_actions is None:
            return
        try:
            state = self.executor.execution_globals.get(
                "get_browser_state_detailed", lambda: {}
            )()
            dom_state = state.get("dom_analysis") if isinstance(state, dict) else {}
            if not dom_state:
                return
            suggestions = suggest_next_actions(
                dom_state, goal_hint or context.get("goal", "")
            )
            with self._context_lock:
                context["dom_suggestions"] = json.dumps(suggestions, ensure_ascii=False)
        except Exception as exc:
            logger.debug("[ExecutionEngine] DOM suggestion 주입 생략: %s", exc)

    def _run_pip_install(self, pip_pkg: str) -> bool:
        try:
            from pip._internal.cli.main import main as pip_main
        except Exception as exc:
            logger.debug("[ExecutionEngine] pip 모듈 import 실패: %s", exc)
            return False
        try:
            exit_code = pip_main(["install", pip_pkg, "--quiet"])
        except Exception as exc:
            logger.debug("[ExecutionEngine] pip install 오류: %s", exc)
            return False
        return int(exit_code or 0) == 0

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
            logger.info("[ExecutionEngine] 미확인 패키지 설치 동의 요청: %s", pip_pkg)
            try:
                from agent.safety_checker import SafetyReport, DangerLevel
                from agent.confirmation_manager import get_confirmation_manager
                report = SafetyReport(
                    level=DangerLevel.CAUTION,
                    matched_patterns=["pip install %s" % pip_pkg],
                    summary=(
                        "'%s' 패키지를 설치합니다. 출처를 확인하세요." % pip_pkg
                    ),
                    category="package_install",
                )
                confirmed = get_confirmation_manager().request_confirmation(
                    "pip install %s" % pip_pkg, report, self._say
                )
                if not confirmed:
                    logger.info("[ExecutionEngine] 패키지 설치 사용자 거부: %s", pip_pkg)
                    return False
            except Exception as exc:
                logger.debug(
                    "[ExecutionEngine] 확인 다이얼로그 생략 (비GUI 환경): %s", exc
                )
                return False

        # 패키지명이 유효한 PyPI 식별자인지 확인 (command injection 방지)
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", pip_pkg):
            logger.warning(
                "[ExecutionEngine] 유효하지 않은 패키지명, 설치 거부: %s", pip_pkg
            )
            return False

        self._say("'%s' 패키지를 자동으로 설치합니다..." % pip_pkg)
        logger.info("[ExecutionEngine] 자동 pip install: %s", pip_pkg)
        if self._run_pip_install(pip_pkg):
            logger.info("[ExecutionEngine] 패키지 설치 완료: %s", pip_pkg)
            return True
        logger.warning("[ExecutionEngine] 패키지 설치 실패: %s", pip_pkg)
        return False

    def _group_by_dependency(self, steps: List[ActionStep]) -> List[List[ActionStep]]:
        """parallel_group 우선, 없으면 기존 의존성 분석으로 실행 레이어 생성."""
        if not steps:
            return []

        explicit_groups = [
            step for step in steps if getattr(step, "parallel_group", -1) >= 0
        ]
        if explicit_groups:
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
            s.step_id: extract_step_targets(
                (s.content or "") + "\n" + (s.description_kr or "")
            )
            for s in steps
        }

        for s in steps:
            # 1. 명시적 의존성 (step_X_output 참조)
            refs = re.findall(
                r"step_(\d+)_output", (s.content or "") + (s.condition or "")
            )
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
                prev_read_only = is_read_only_step_content(
                    prev_step.content, prev_step.description_kr
                )
                prev_stateful = mutates_runtime_state(
                    prev_step.content, prev_step.description_kr
                )

                path_conflict = bool(
                    set(current_targets["paths"]) & set(prev_targets["paths"])
                )
                domain_conflict = bool(
                    set(current_targets["domains"]) & set(prev_targets["domains"])
                )
                window_conflict = bool(
                    set(current_targets.get("windows", []))
                    & set(prev_targets.get("windows", []))
                )
                goal_hint_conflict = bool(
                    set(current_targets.get("goal_hints", []))
                    & set(prev_targets.get("goal_hints", []))
                )
                state_conflict = current_stateful and prev_stateful

                if (
                    path_conflict
                    or domain_conflict
                    or window_conflict
                    or goal_hint_conflict
                    or state_conflict
                ):
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
            current_layer = [
                s for s in steps
                if s.step_id not in processed
                and graph[s.step_id].issubset(processed)
            ]
            if not current_layer:
                break
            layers.append(current_layer)
            processed.update(s.step_id for s in current_layer)

        return layers if layers else [[s] for s in steps]  # 실패 시 순차 실행 폴백

    def _eval_condition(self, cond: str, ctx: Dict[str, str]) -> bool:
        try:
            return evaluate_condition(cond, ctx)
        except Exception as exc:
            logger.debug(
                f"[ExecutionEngine] 조건식 평가 실패(False): {cond!r} ({exc})"
            )
            return False

    def _classify_failure(self, res: ExecutionResult) -> str:
        if res.success:
            return ""
        return classify_failure_message(res.error or res.output or "")

    def _update_runtime_context(
        self,
        context: Dict[str, str],
        exec_result: ExecutionResult,
    ) -> None:
        try:
            runtime_state = self.executor.get_runtime_state()
        except Exception:
            runtime_state = {}
        with self._context_lock:
            if runtime_state.get("active_window_title"):
                context["active_window_title"] = str(
                    runtime_state["active_window_title"]
                )[:200]
            if runtime_state.get("open_window_titles"):
                context["open_window_titles"] = ", ".join(
                    runtime_state.get("open_window_titles", [])[:6]
                )[:300]
            browser_state = runtime_state.get("browser_state") or {}
            if browser_state.get("current_url"):
                context["browser_current_url"] = str(
                    browser_state.get("current_url")
                )[:200]
            if browser_state.get("title"):
                context["browser_title"] = str(browser_state.get("title"))[:200]
            desktop_state = runtime_state.get("desktop_state") or {}
            if desktop_state:
                context["desktop_state_json"] = json.dumps(
                    desktop_state, ensure_ascii=False
                )[:500]
            learned_strategies = runtime_state.get("learned_strategies") or {}
            if learned_strategies:
                context["learned_strategies_json"] = json.dumps(
                    learned_strategies, ensure_ascii=False
                )[:500]
            learned_strategy_summary = str(
                runtime_state.get("learned_strategy_summary", "") or ""
            )
            if learned_strategy_summary:
                context["learned_strategy_summary"] = learned_strategy_summary[:300]
            planning_snapshot_summary = str(
                runtime_state.get("planning_snapshot_summary", "") or ""
            )
            if planning_snapshot_summary:
                context["planning_snapshot_summary"] = planning_snapshot_summary[:400]
            planning_snapshot = runtime_state.get("planning_snapshot") or {}
            if planning_snapshot:
                context["planning_snapshot_json"] = json.dumps(
                    planning_snapshot, ensure_ascii=False
                )[:500]
            execution_policy_summary = str(
                runtime_state.get("execution_policy_summary", "") or ""
            )
            if execution_policy_summary:
                context["execution_policy_summary"] = execution_policy_summary[:400]
            execution_policy = runtime_state.get("execution_policy") or {}
            if execution_policy:
                context["execution_policy_json"] = json.dumps(
                    execution_policy, ensure_ascii=False
                )[:500]
            last_state_delta_summary = str(
                runtime_state.get("last_state_delta_summary", "") or ""
            )
            if last_state_delta_summary:
                context["last_state_delta_summary"] = last_state_delta_summary[:300]
            recent_state_transitions = (
                runtime_state.get("recent_state_transitions") or []
            )
            if recent_state_transitions:
                context["recent_state_transitions_json"] = json.dumps(
                    recent_state_transitions, ensure_ascii=False
                )[:500]
            backup_history = runtime_state.get("backup_history") or []
            if backup_history:
                context["backup_history_json"] = json.dumps(
                    backup_history, ensure_ascii=False
                )[:500]
            recovery_candidates = runtime_state.get("recovery_candidates") or []
            if recovery_candidates:
                context["recovery_candidates_json"] = json.dumps(
                    recovery_candidates, ensure_ascii=False
                )[:500]
            recent_goal_episodes = str(
                runtime_state.get("recent_goal_episodes", "") or ""
            )
            if recent_goal_episodes:
                context["recent_goal_episodes"] = recent_goal_episodes[:600]
            recovery_guidance = str(
                runtime_state.get("recovery_guidance", "") or ""
            )
            if recovery_guidance:
                context["recovery_guidance"] = recovery_guidance[:500]
            context["last_step_success"] = str(exec_result.success)
            if exec_result.output:
                artifacts = extract_artifacts([exec_result.output])
                if artifacts["paths"]:
                    context["last_artifact_paths"] = ", ".join(
                        artifacts["paths"][:3]
                    )
                if artifacts["urls"]:
                    context["last_artifact_urls"] = ", ".join(
                        artifacts["urls"][:3]
                    )
            state_delta_summary = str(
                getattr(exec_result, "state_delta_summary", "") or ""
            )
            if state_delta_summary:
                context["last_state_change"] = state_delta_summary[:300]
            step_targets = extract_step_targets(
                str(getattr(exec_result, "code_or_cmd", "") or "")
            )
            if step_targets["paths"]:
                context["last_target_paths"] = ", ".join(step_targets["paths"][:3])
            if step_targets["domains"]:
                context["last_target_domains"] = ", ".join(
                    step_targets["domains"][:3]
                )
            if step_targets["windows"]:
                context["last_target_windows"] = ", ".join(
                    step_targets["windows"][:3]
                )
            if step_targets["goal_hints"]:
                context["last_goal_hints"] = ", ".join(step_targets["goal_hints"][:3])
            if runtime_state:
                context["runtime_state_json"] = json.dumps(
                    runtime_state, ensure_ascii=False
                )[:500]

    def _build_adaptive_context(self, failed: List) -> Dict[str, str]:
        kinds = [sr.failure_kind for sr in failed if sr.failure_kind]
        errs = " | ".join(
            [
                (sr.exec_result.error or sr.exec_result.output or "")[:100]
                for sr in failed
            ]
        )
        artifacts = extract_artifacts(
            [sr.exec_result.output or "" for sr in failed]
            + [sr.exec_result.error or "" for sr in failed]
        )
        ctx = {
            "재계획_이유": (
                f"실행 실패 ({', '.join(set(kinds)) if kinds else '오류'})"
            ),
            "실패_오류": errs[:300],
        }
        target_hints: Dict[str, List] = {
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
            ctx["실패_대상_경로"] = ", ".join(
                list(dict.fromkeys(target_hints["paths"]))[:3]
            )
        if target_hints["domains"]:
            ctx["실패_대상_도메인"] = ", ".join(
                list(dict.fromkeys(target_hints["domains"]))[:3]
            )
        if target_hints["windows"]:
            ctx["실패_대상_창"] = ", ".join(
                list(dict.fromkeys(target_hints["windows"]))[:3]
            )
        if target_hints["goal_hints"]:
            ctx["실패_goal_hint"] = ", ".join(
                list(dict.fromkeys(target_hints["goal_hints"]))[:3]
            )
        try:
            recovery_targets = list(dict.fromkeys(target_hints["paths"]))[:5]
            candidates = self.executor.get_recovery_candidates(recovery_targets)
            if candidates:
                ctx["복구_가능_파일"] = ", ".join(
                    candidate.get("target_path", "")
                    for candidate in candidates[:3]
                    if candidate.get("target_path")
                )
                ctx["복구_권장"] = (
                    "필요 시 get_recovery_candidates(...) 확인 후 restore_last_backup(path) 사용"
                )
            guidance = self.executor.get_recovery_guidance(
                goal=failed[0].step.description_kr if failed else "",
                target_paths=recovery_targets,
            )
            if guidance:
                ctx["복구_가이드"] = guidance[:500]
        except Exception as exc:
            logger.debug("[ExecutionEngine] recovery candidate 주입 생략: %s", exc)
        return ctx

    # ── 개발자 가드 ────────────────────────────────────────────────────────────

    def _is_developer_goal(self, goal: str) -> bool:
        try:
            return bool(
                hasattr(self.planner, "is_developer_goal")
                and self.planner.is_developer_goal(goal)
            )
        except Exception:
            return False

    def _apply_developer_step_guard(
        self,
        goal: str,
        sr,
        context: Dict[str, str],
    ):
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

    def _find_developer_step_guard_error(
        self,
        goal: str,
        sr,
        context: Dict[str, str],
    ) -> str:
        step = getattr(sr, "step", None)
        exec_result = getattr(sr, "exec_result", None)
        content = getattr(step, "content", "") or ""
        output = getattr(exec_result, "output", "") or ""
        for path in self._extract_developer_result_paths(output):
            if not self.planner.is_allowed_developer_path(
                path, goal=goal, context=context
            ):
                return (
                    f"허용 범위를 벗어난 경로가 선택되어 개발 작업을 중단했습니다: {path}"
                )
        if self._contains_invalid_developer_validation(content):
            return "허용되지 않은 개발 검증 명령이 계획에 포함되어 실행을 중단했습니다."
        return ""

    def _find_developer_scope_violation(
        self,
        goal: str,
        step_results: List,
    ) -> str:
        for sr in step_results:
            step = getattr(sr, "step", None)
            exec_result = getattr(sr, "exec_result", None)
            content = getattr(step, "content", "") or ""
            output = getattr(exec_result, "output", "") or ""
            for path in self._extract_developer_result_paths(
                "\n".join([content, output])
            ):
                if not self.planner.is_allowed_developer_path(
                    path, goal=goal, context=None
                ):
                    return (
                        f"허용 범위를 벗어난 파일/경로가 선택되어 작업을 완료로 볼 수 없습니다: {path}"
                    )
        return ""

    def _extract_developer_result_paths(self, text: str) -> List[str]:
        candidates: List[str] = []
        normalized_repo_root = (
            os.path.abspath(os.getcwd()).replace("\\", "/").lower()
        )

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

    # ── 유틸리티 ───────────────────────────────────────────────────────────────

    def _emit_progress(self, event_type: str, **kwargs) -> None:
        if self.progress_callback:
            try:
                self.progress_callback(event_type, **kwargs)
            except Exception as e:
                logger.debug("[ExecutionEngine] 진행 콜백 오류: %s", e)

    def _say(self, msg: str) -> None:
        if self.tts:
            self.tts(msg)

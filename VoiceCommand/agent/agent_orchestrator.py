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
import re
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

try:
    from services.dom_analyser import suggest_next_actions
except Exception:
    suggest_next_actions = None

# executor._lock 경합 시 반환되는 오류 문자열 — self-fix 대상에서 제외
_LOCK_CONTENTION_ERRORS = frozenset({
    "이미 다른 코드가 실행 중입니다.",
    "이미 다른 명령이 실행 중입니다.",
})

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
            if res.success: return res, att, fixed
            if att > self.MAX_STEP_RETRIES: break
            err = res.error or res.output or "오류"
            if err in _LOCK_CONTENTION_ERRORS: time.sleep(att); continue
            self._say(f"[걱정] 오류 발생, 수정 중입니다. ({att}/{self.MAX_STEP_RETRIES})")
            f = self.planner.fix_step(curr, err, goal, context)
            if f and f.content and f.content != curr.content: curr, fixed = f, True
            else: break
        return res, att, fixed

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
        try:
            from agent.real_verifier import get_real_verifier
            v = get_real_verifier().verify(goal, step_results)
            return v.verified, v.summary_kr
        except Exception as exc:
            logger.debug(f"[Orchestrator] RealVerifier 폴백: {exc}")
        if any(not sr.exec_result.success for sr in step_results): return False, "일부 단계 실패"
        verdict = self.planner.verify(goal, [sr.exec_result for sr in step_results])
        return verdict.get("achieved", False), verdict.get("summary_kr", "검증 실패")

    def _record_strategy(self, goal: str, run_result: AgentRunResult, duration: int, lesson: str = ""):
        try:
            from agent.strategy_memory import get_strategy_memory
            failed = [sr for sr in run_result.step_results if not sr.exec_result.success]
            fk = failed[-1].failure_kind if failed else ""
            get_strategy_memory().record(goal=goal, steps=[sr.step for sr in run_result.step_results], success=run_result.achieved, error="" if run_result.achieved else run_result.summary_kr, duration_ms=duration, failure_kind=fk, lesson=lesson)
        except Exception as e: logger.warning(f"[Orchestrator] StrategyMemory 기록 실패: {e}")

    def _build_adaptive_context(self, failed: List[StepResult]) -> Dict[str, str]:
        kinds = [sr.failure_kind for sr in failed if sr.failure_kind]
        errs = " | ".join([(sr.exec_result.error or sr.exec_result.output or "")[:100] for sr in failed])
        artifacts = extract_artifacts([sr.exec_result.output or "" for sr in failed] + [sr.exec_result.error or "" for sr in failed])
        ctx = {"재계획_이유": f"실행 실패 ({', '.join(set(kinds)) if kinds else '오류'})", "실패_오류": errs[:300]}
        if artifacts["paths"]:
            ctx["관측_경로"] = ", ".join(artifacts["paths"][:3])
        if artifacts["urls"]:
            ctx["관측_URL"] = ", ".join(artifacts["urls"][:3])
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
        context["last_step_success"] = str(exec_result.success)
        if exec_result.output:
            artifacts = extract_artifacts([exec_result.output])
            if artifacts["paths"]:
                context["last_artifact_paths"] = ", ".join(artifacts["paths"][:3])
            if artifacts["urls"]:
                context["last_artifact_urls"] = ", ".join(artifacts["urls"][:3])
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
            key_node = node.slice.value if isinstance(node.slice, ast.Index) else node.slice
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

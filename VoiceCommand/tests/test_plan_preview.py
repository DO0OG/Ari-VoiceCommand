import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from agent.agent_orchestrator import (
    AgentOrchestrator,
    ExecutionResult,
    StepResult,
    _plan_approval_active,
    plan_approval_scope,
)
from agent.planner.action_step import ActionStep


class _FakePlanner:
    """계획 생성기를 대신한다. decompose 를 부를 때마다 미리 정한 계획을 차례로 돌려준다."""

    def __init__(self, plans):
        self.plans = list(plans)
        self.calls = 0

    def decompose(self, goal, context, component_trials=None):
        plan = self.plans[min(self.calls, len(self.plans) - 1)]
        self.calls += 1
        return list(plan)

    def get_last_learning_signals(self):
        return {}

    def _build_template_plan(self, goal):
        return []

    def is_developer_goal(self, goal):
        return False


def _step(step_id, content, reads=(), writes=()):
    return ActionStep(
        step_id=step_id,
        step_type="python",
        content=content,
        description_kr=f"단계 {step_id}",
        reads=list(reads),
        writes=list(writes),
    )


class PlanPreviewTests(unittest.TestCase):
    def _orchestrator(self, plans, verify=((True, "완료"),)):
        self.events = []
        orchestrator = AgentOrchestrator(MagicMock(), _FakePlanner(plans))
        orchestrator.set_progress_callback(lambda event, **kw: self.events.append(event))
        orchestrator._estimate_goal_difficulty = lambda goal: 0.0
        orchestrator._should_prefer_template_over_skill = lambda goal: True
        orchestrator._verify_engine = MagicMock()
        orchestrator._verify_engine.verify.side_effect = list(verify)
        orchestrator._learn = MagicMock()

        def fake_execute(steps, context, goal):
            self.events.append("exec")
            return True, [
                StepResult(step=s, exec_result=ExecutionResult(success=True, output="ok")) for s in steps
            ]

        orchestrator._execute_plan = fake_execute
        return orchestrator

    def _approver(self, answers):
        shown = []

        def approve(steps, iteration):
            self.events.append("approve")
            shown.append(steps)
            return answers[min(len(shown) - 1, len(answers) - 1)]

        return approve, shown

    def test_plan_preview_waits_for_approval_before_any_step(self):
        orchestrator = self._orchestrator([[_step(1, "print(1)", reads=["a.txt"], writes=["b.txt"])]])
        approve, shown = self._approver([True])
        with plan_approval_scope(approve):
            result = orchestrator._run_loop("목표", shared_context={})
        self.assertEqual(self.events[:4], ["plan_ready", "approve", "exec", "verify_start"])
        self.assertTrue(result.achieved)
        self.assertEqual(shown[0][0]["reads"], ["a.txt"])
        self.assertEqual(shown[0][0]["writes"], ["b.txt"])

    def test_replan_requires_new_approval(self):
        orchestrator = self._orchestrator(
            [[_step(1, "print(1)")], [_step(1, "print(2)", writes=["c.txt"])]],
            verify=((False, "미달성"), (True, "완료")),
        )
        approve, shown = self._approver([True])
        with plan_approval_scope(approve):
            orchestrator._run_loop("목표", shared_context={})
        self.assertEqual(len(shown), 2)
        self.assertEqual(shown[1][0]["writes"], ["c.txt"])
        self.assertEqual(self.events.count("exec"), 2)

    def test_same_plan_after_replan_is_not_asked_again(self):
        orchestrator = self._orchestrator(
            [[_step(1, "print(1)")]],
            verify=((False, "미달성"), (True, "완료")),
        )
        approve, shown = self._approver([True])
        with plan_approval_scope(approve):
            orchestrator._run_loop("목표", shared_context={})
        self.assertEqual(len(shown), 1)
        self.assertEqual(self.events.count("exec"), 2)

    def test_cancel_runs_no_step_and_ends(self):
        orchestrator = self._orchestrator([[_step(1, "print(1)")]])
        approve, shown = self._approver([False])
        with plan_approval_scope(approve):
            result = orchestrator._run_loop("목표", shared_context={})
        self.assertEqual(self.events.count("exec"), 0)
        self.assertEqual(len(shown), 1)
        self.assertTrue(result.plan_declined)
        self.assertFalse(result.achieved)
        self.assertIn("plan_declined", self.events)

    def test_approver_error_counts_as_cancel(self):
        orchestrator = self._orchestrator([[_step(1, "print(1)")]])

        def broken(steps, iteration):
            raise RuntimeError("화면 없음")

        with plan_approval_scope(broken):
            result = orchestrator._run_loop("목표", shared_context={})
        self.assertEqual(self.events.count("exec"), 0)
        self.assertTrue(result.plan_declined)

    def test_run_skips_reflection_and_learning_when_declined(self):
        orchestrator = self._orchestrator([[_step(1, "print(1)")]])
        orchestrator._build_shared_context = lambda goal, trials=None: {}
        approve, _shown = self._approver([False])
        with plan_approval_scope(approve):
            result = orchestrator.run("목표")
        self.assertTrue(result.plan_declined)
        orchestrator._learn.reflect_on_failure.assert_not_called()
        orchestrator._learn.schedule_post_run_update.assert_not_called()
        self.assertEqual(self.events.count("exec"), 0)

    def test_without_scope_runs_like_before(self):
        orchestrator = self._orchestrator([[_step(1, "print(1)")]])
        result = orchestrator._run_loop("목표", shared_context={})
        self.assertEqual(self.events[:3], ["plan_ready", "exec", "verify_start"])
        self.assertTrue(result.achieved)
        self.assertFalse(result.plan_declined)

    def test_scope_is_not_visible_to_other_threads(self):
        seen = []
        with plan_approval_scope(lambda steps, iteration: True):
            worker = threading.Thread(target=lambda: seen.append(_plan_approval_active()))
            worker.start()
            worker.join()
            self.assertTrue(_plan_approval_active())
        self.assertEqual(seen, [False])
        self.assertFalse(_plan_approval_active())

    def test_run_extends_deadline_by_approval_wait_before_retry_decision(self):
        orchestrator = self._orchestrator(
            [[_step(1, "print(1)")]], verify=((False, "미달성"), (False, "미달성"))
        )
        orchestrator._build_shared_context = lambda goal, trials=None: {}
        orchestrator._record_strategy = MagicMock()
        orchestrator._emit_plugin_event = MagicMock()
        orchestrator._should_activate_component = lambda *args, **kwargs: False
        seen = []
        orchestrator._is_timeout_exceeded = lambda deadline: seen.append(deadline) or False
        clock = [1000.0]

        def slow_approve(steps, iteration):
            clock[0] += 100.0  # 사용자가 100초 뒤에 승인한 것으로 본다
            return True

        with patch("agent.agent_orchestrator.time", SimpleNamespace(time=lambda: clock[0])):
            with plan_approval_scope(slow_approve):
                result = orchestrator.run("목표", timeout=10)
        self.assertEqual(result.plan_wait_seconds, 100.0)
        self.assertEqual(seen[0], 1010.0)  # 처음 제한 시각
        self.assertEqual(seen[-1], 1110.0)  # 반성·재시도 판정에는 기다린 시간만큼 늘어난 시각을 쓴다


class CompiledSkillPreviewTests(unittest.TestCase):
    def _setup(self):
        self.events = []
        orchestrator = AgentOrchestrator(MagicMock(), _FakePlanner([[]]))
        orchestrator._verify_engine = MagicMock()
        orchestrator._verify_engine.verify.return_value = (True, "완료")

        def fake_execute(steps, context, goal):
            self.events.append("exec")
            return True, [
                StepResult(step=s, exec_result=ExecutionResult(success=True, output="ok")) for s in steps
            ]

        orchestrator._execute_plan = fake_execute
        skill = SimpleNamespace(
            skill_id="skill_1",
            name="보고서",
            compiled=True,
            steps=[{"step_id": 0, "step_type": "python", "content": "print(1)", "description_kr": "보고서 작성"}],
        )
        library = MagicMock()
        library.get_applicable_skill.return_value = skill
        optimizer = MagicMock()
        optimizer.run_compiled.side_effect = lambda skill_id, goal: (self.events.append("compiled"), (True, "out"))[1]
        optimizer.load_compiled.return_value = "code"
        patches = (
            patch("agent.skill_library.get_skill_library", return_value=library),
            patch("agent.skill_optimizer.get_skill_optimizer", return_value=optimizer),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        return orchestrator

    def test_compiled_skill_does_not_run_before_approval(self):
        orchestrator = self._setup()
        asked = []

        def approve(steps, iteration):
            self.events.append("approve")
            asked.append(steps)
            return False

        with plan_approval_scope(approve):
            result = orchestrator._run_with_skill_if_available("목표", {}, {}, None, set())
        self.assertTrue(result.plan_declined)
        self.assertEqual(self.events, ["approve"])
        self.assertEqual(asked[0][0]["description_kr"], "보고서 작성")

    def test_approved_skill_runs_the_displayed_steps_instead_of_compiled_code(self):
        orchestrator = self._setup()
        with plan_approval_scope(lambda steps, iteration: True):
            result = orchestrator._run_with_skill_if_available("목표", {}, {}, None, set())
        self.assertTrue(result.achieved)
        self.assertEqual(self.events, ["exec"])

    def test_compiled_skill_runs_first_when_option_is_off(self):
        orchestrator = self._setup()
        result = orchestrator._run_with_skill_if_available("목표", {}, {}, None, set())
        self.assertTrue(result.achieved)
        self.assertEqual(self.events, ["compiled"])

    def test_skill_path_reports_approval_wait_for_deadline(self):
        orchestrator = self._setup()
        clock = [1000.0]

        def slow_approve(steps, iteration):
            clock[0] += 100.0
            return True

        wait = [0.0]
        with patch("agent.agent_orchestrator.time", SimpleNamespace(time=lambda: clock[0])):
            with plan_approval_scope(slow_approve):
                orchestrator._run_with_skill_if_available("목표", {}, {}, None, set(), wait)
        self.assertEqual(wait, [100.0])


class PlanPreviewThreadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_option_off_opens_no_scope(self):
        from ui.text_interface import TextInterfaceThread

        thread = TextInterfaceThread(None, "질문")
        with patch("core.config_manager.ConfigManager.get", return_value=False):
            with thread._plan_approval_scope():
                self.assertFalse(_plan_approval_active())

    def test_option_on_opens_scope(self):
        from ui.text_interface import TextInterfaceThread

        thread = TextInterfaceThread(None, "질문")
        with patch("core.config_manager.ConfigManager.get", return_value=True):
            with thread._plan_approval_scope():
                self.assertTrue(_plan_approval_active())
        self.assertFalse(_plan_approval_active())

    def test_request_times_out_as_cancel(self):
        from ui import text_interface

        thread = text_interface.TextInterfaceThread(None, "질문")
        emitted = []
        thread.progress_event.connect(lambda event, payload: emitted.append(event))
        with patch.object(text_interface, "PLAN_APPROVAL_TIMEOUT_SECONDS", 0.05):
            self.assertFalse(thread._request_plan_approval([{"step_id": 1}], 0))
        self.assertEqual(emitted, ["plan_approval_request"])

    def test_request_follows_user_decision(self):
        from ui.text_interface import TextInterfaceThread

        for decision in (True, False):
            thread = TextInterfaceThread(None, "질문")
            timer = threading.Timer(0.05, thread.resolve_plan_approval, args=(decision,))
            timer.start()
            self.assertIs(thread._request_plan_approval([{"step_id": 1}], 0), decision)
            timer.join()

    def test_concurrent_requests_are_asked_one_at_a_time(self):
        from ui.text_interface import TextInterfaceThread

        thread = TextInterfaceThread(None, "질문")
        emitted = []
        # 작업 스레드에서 보낸 신호를 이벤트 루프 없이 바로 받으려고 직접 연결한다.
        thread.progress_event.connect(
            lambda event, payload: emitted.append(payload["iteration"]), Qt.DirectConnection
        )
        results = {}

        def ask(number):
            results[number] = thread._request_plan_approval([{"step_id": 1}], number)

        def wait_until(condition):
            limit = time.time() + 5
            while not condition() and time.time() < limit:
                time.sleep(0.01)

        first = threading.Thread(target=ask, args=(1,))
        first.start()
        wait_until(lambda: emitted == [1])
        second = threading.Thread(target=ask, args=(2,))
        second.start()
        time.sleep(0.1)
        self.assertEqual(emitted, [1])  # 첫 요청이 끝나기 전에는 둘째를 보여 주지 않는다
        thread.resolve_plan_approval(True)
        first.join(5)
        wait_until(lambda: emitted == [1, 2])
        thread.resolve_plan_approval(False)
        second.join(5)
        self.assertEqual(results, {1: True, 2: False})

    def test_declined_run_is_reported_without_failure_wording(self):
        from commands.ai_command import AICommand
        from agent.agent_orchestrator import AgentRunResult

        run = AgentRunResult(goal="g", summary="승인 안 됨", total_iterations=1, plan_declined=True)
        fake_self = SimpleNamespace(_extract_saved_path_from_agent_run=lambda result: "")
        self.assertEqual(AICommand._agent_run_to_korean(fake_self, run), "승인 안 됨")


if __name__ == "__main__":
    unittest.main()

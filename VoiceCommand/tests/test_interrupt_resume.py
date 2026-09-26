import unittest
from types import SimpleNamespace
from dataclasses import asdict
from unittest.mock import Mock, patch
import threading
from concurrent.futures import TimeoutError as FuturesTimeoutError

from agent.agent_orchestrator import AgentOrchestrator, StepResult
from agent.agent_planner import ActionStep
from agent.autonomous_executor import ExecutionResult
from i18n.translator import _


class _NoopExecutor:
    def cancel_running_processes(self):
        self.cancelled = True


class InterruptResumeTests(unittest.TestCase):
    def _orchestrator(self):
        planner = Mock()
        planner.get_last_learning_signals.return_value = {}
        orchestrator = AgentOrchestrator(_NoopExecutor(), planner)
        orchestrator._learn = Mock()
        orchestrator._verify_engine = Mock()
        orchestrator._verify_engine.verify.return_value = (True, "done")
        orchestrator._build_shared_context = Mock(return_value={})
        orchestrator._should_prefer_template_over_skill = Mock(return_value=True)
        orchestrator._estimate_goal_difficulty = Mock(return_value=0)
        orchestrator._prevalidate_steps = Mock(return_value=[])
        orchestrator._emit_plugin_event = Mock()
        return orchestrator

    def test_resume_restores_saved_plan_and_context_without_repeating_completed_step(self):
        orchestrator = self._orchestrator()
        first = ActionStep(1, "python", "first()", "first", parallel_group=0)
        second = ActionStep(2, "python", "second(step_1_output)", "second")
        completed = StepResult(first, ExecutionResult(success=True, output="saved-output"))
        orchestrator._last_checkpoint = {
            "goal": "task", "iteration": 1, "steps": [asdict(first), asdict(second)],
            "step_results": [asdict(completed)],
            "context": {"step_1_output": "saved-output", "window_title": "saved-window"},
        }

        def execute(steps, context, goal):
            self.assertEqual([s.step_id for s in steps], [2])
            self.assertEqual(context["step_1_output"], "saved-output")
            self.assertEqual(context["window_title"], "saved-window")
            return True, [StepResult(second, ExecutionResult(success=True, output="done"))]

        orchestrator._execute_plan = Mock(side_effect=execute)
        result = orchestrator.resume()
        self.assertTrue(result.achieved)
        orchestrator.planner.decompose.assert_not_called()
        orchestrator._build_shared_context.assert_not_called()
        self.assertEqual([sr.step.step_id for sr in orchestrator._verify_engine.verify.call_args.args[1]], [1, 2])
        self.assertIsNone(orchestrator._last_checkpoint)

    def test_interrupt_during_plan_execution_skips_recovery_and_resumes_remaining_steps(self):
        orchestrator = self._orchestrator()
        first = ActionStep(1, "python", "first()", "first")
        second = ActionStep(2, "python", "second()", "second")
        orchestrator.planner.decompose.return_value = [first, second]
        calls = []

        def runner(step, goal, context):
            calls.append(step.step_id)
            if step.step_id == 1:
                orchestrator.interrupt()
            return ExecutionResult(success=True, output=str(step.step_id)), 1, False

        orchestrator._execute_step_with_retry = runner
        result = orchestrator.run("task")
        self.assertFalse(result.achieved)
        self.assertEqual(calls, [1])
        orchestrator._learn.reflect_on_failure.assert_not_called()
        orchestrator._learn.schedule_reflection.assert_not_called()
        orchestrator._verify_engine.verify.assert_not_called()
        result = orchestrator.resume()
        self.assertTrue(result.achieved)
        self.assertEqual(calls, [1, 2])
        self.assertEqual(orchestrator.planner.decompose.call_count, 1)

    def test_unverifiable_success_is_not_replanned_and_keeps_output(self):
        orchestrator = self._orchestrator()
        step = ActionStep(1, "python", "print(apps())", "앱 목록")
        orchestrator.planner.decompose.return_value = [step]
        orchestrator._verify_engine.verify.return_value = (False, _("요청한 결과를 실제 상태로 검증하지 못했습니다."))
        orchestrator._execute_plan = Mock(
            return_value=(True, [StepResult(step, ExecutionResult(success=True, output="Chrome, Code"))])
        )

        result = orchestrator.run("실행 중인 앱 알려줘")

        self.assertFalse(result.achieved)
        self.assertIn("Chrome, Code", result.summary)
        orchestrator.planner.decompose.assert_called_once()
        orchestrator._execute_plan.assert_called_once()
        orchestrator._learn.reflect_on_failure.assert_not_called()

    def test_reflection_retry_keeps_output_when_only_verification_is_unavailable(self):
        from agent import agent_orchestrator as module

        orchestrator = self._orchestrator()
        orchestrator._learn.reflect_on_failure.return_value = SimpleNamespace(lesson="경로 확인", avoid_patterns=[])
        retried = module.AgentRunResult(
            goal="task", achieved=False, summary="검증 불가 Chrome, Code", verification_unavailable=True
        )
        orchestrator._run_loop = Mock(side_effect=[module.AgentRunResult(goal="task", summary="실패"), retried])

        result = orchestrator.run("task")

        self.assertEqual(orchestrator._run_loop.call_count, 2)
        self.assertTrue(result.verification_unavailable)
        self.assertIn("Chrome, Code", result.summary)

    def test_subagent_timeout_interrupts_only_the_running_child(self):
        from agent import agent_orchestrator as module

        started = threading.Event()

        def child_run(child, goal, timeout=None):
            started.set()
            child._interrupt_requested.wait(5)
            return module.AgentRunResult(goal=goal, achieved=False, summary="stopped")

        class _TimeoutPool:
            def submit(self, fn):
                self.thread = threading.Thread(target=fn)
                self.thread.start()
                started.wait(5)
                future = Mock()
                future.result.side_effect = FuturesTimeoutError()
                return future

        orchestrator = AgentOrchestrator(_NoopExecutor(), Mock())
        orchestrator._subagent_pool = pool = _TimeoutPool()
        with patch.object(module, "AutonomousExecutor", lambda tts=None: _NoopExecutor()), \
             patch.object(module, "get_planner", lambda: Mock()), \
             patch.object(AgentOrchestrator, "run", child_run):
            result = orchestrator.spawn_subagent("child", timeout=1)
            pool.thread.join(2)

        self.assertFalse(result.achieved)
        self.assertFalse(pool.thread.is_alive())
        self.assertFalse(orchestrator._interrupt_requested.is_set())

    def test_parent_cancellation_is_not_cleared_by_child_run(self):
        event = threading.Event()
        event.set()
        orchestrator = AgentOrchestrator(_NoopExecutor(), Mock(), cancel_event=event)
        orchestrator._learn = Mock()
        with patch.object(orchestrator, "_build_shared_context") as build:
            result = orchestrator.run("task")
        self.assertFalse(result.achieved)
        self.assertTrue(event.is_set())
        build.assert_not_called()
        orchestrator.planner.decompose.assert_not_called()

    def test_interrupt_requests_executor_cancel(self):
        executor = _NoopExecutor()
        orchestrator = AgentOrchestrator(
            executor,
            planner=SimpleNamespace(),
            tts_func=None,
        )

        orchestrator.interrupt()

        self.assertTrue(orchestrator._interrupt_requested.is_set())
        self.assertTrue(executor.cancelled)

    def test_resume_without_checkpoint_reports_no_work(self):
        orchestrator = AgentOrchestrator(
            _NoopExecutor(),
            planner=SimpleNamespace(),
            tts_func=None,
        )

        result = orchestrator.resume()

        self.assertFalse(result.achieved)
        self.assertIn("재개", result.summary)


if __name__ == "__main__":
    unittest.main()

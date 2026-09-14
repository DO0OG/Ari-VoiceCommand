import unittest
from types import SimpleNamespace
from dataclasses import asdict
from unittest.mock import Mock, patch
import threading

from agent.agent_orchestrator import AgentOrchestrator, StepResult
from agent.agent_planner import ActionStep
from agent.autonomous_executor import ExecutionResult


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

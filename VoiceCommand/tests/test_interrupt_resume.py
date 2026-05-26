import unittest
from types import SimpleNamespace

from agent.agent_orchestrator import AgentOrchestrator


class _NoopExecutor:
    def cancel_running_processes(self):
        self.cancelled = True


class InterruptResumeTests(unittest.TestCase):
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

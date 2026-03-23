import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.agent_orchestrator import AgentOrchestrator
from agent.agent_planner import AgentPlanner
from agent.autonomous_executor import AutonomousExecutor
from agent.strategy_memory import StrategyMemory


class DummyLLMProvider:
    client = None
    provider = "openai"
    model = "dummy"


class AgentIntegrationTests(unittest.TestCase):
    def _execute_template_steps(self, goal: str, desktop_path: str):
        planner = AgentPlanner(DummyLLMProvider())
        executor = AutonomousExecutor()
        executor.execution_globals["desktop_path"] = desktop_path
        orchestrator = AgentOrchestrator(executor, planner)
        steps = planner.decompose(goal, {})
        context = {}
        results = []
        for step in steps:
            if step.condition and not orchestrator._eval_condition(step.condition, context):
                continue
            result = executor.run_python(step.content, extra_globals={"step_outputs": dict(context)})
            self.assertTrue(result.success, msg=result.error or result.output)
            context[f"step_{step.step_id}_output"] = result.output[:300]
            results.append(result)
        return steps, results, context

    def test_create_folder_template_executes_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            goal = "바탕화면에 samplefolder 폴더 만들어줘"
            steps, results, _ = self._execute_template_steps(goal, tmp)
            self.assertEqual(len(steps), 1)
            self.assertEqual(len(results), 1)
            self.assertTrue(os.path.isdir(os.path.join(tmp, "samplefolder")))

    def test_directory_listing_template_saves_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = os.path.join(tmp, "source")
            os.makedirs(source_dir, exist_ok=True)
            with open(os.path.join(source_dir, "alpha.txt"), "w", encoding="utf-8") as handle:
                handle.write("hello")

            goal = rf"{source_dir} 폴더 목록 저장해줘"
            _, _, context = self._execute_template_steps(goal, tmp)
            saved_path = context.get("step_1_output", "").strip()
            self.assertTrue(saved_path)
            self.assertTrue(os.path.exists(saved_path))

    def test_strategy_memory_uses_token_similarity(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = StrategyMemory(filepath=os.path.join(tmp, "strategy.json"))
            mem.record("회의록 요약 작성", [], True, duration_ms=100)
            mem.record("브라우저 자동 로그인", [], False, error="timeout", failure_kind="timeout")
            context = mem.get_relevant_context("회의록 작성")
            self.assertIn("회의록 요약 작성", context)


if __name__ == "__main__":
    unittest.main()

import os
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

class DummyLLMProvider:
    client = None
    provider = "openai"
    model = "dummy"

class DummyExecutor:
    def __init__(self, tts_wrapper=None):
        self.tts_wrapper = tts_wrapper

    def run_python(self, code, extra_globals=None):
        from agent.autonomous_executor import ExecutionResult
        return ExecutionResult(success=True, output=f"dummy python result for {code}")

    def run_shell(self, command, timeout=30):
        from agent.autonomous_executor import ExecutionResult
        return ExecutionResult(success=True, output=f"dummy shell result for {command}")

class DummyPlanner:
    def decompose(self, goal, context=None):
        from agent.agent_planner import ActionStep
        return [ActionStep(step_id=1, step_type="shell", content="echo dummy", description_kr="Dummy Step")]
        
    def verify(self, goal, exec_results):
        return {"achieved": True, "summary": "Dummy verified"}

class DummyConfigManager:
    @staticmethod
    def load_settings():
        return {}
        
    @staticmethod
    def save_settings(settings):
        pass

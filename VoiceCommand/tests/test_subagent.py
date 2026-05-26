from agent.agent_orchestrator import AgentRunResult


def test_spawn_subagent_returns_child_result(monkeypatch):
    from agent import agent_orchestrator as module

    class DummyFuture:
        def result(self, timeout=None):
            return AgentRunResult(goal="child", achieved=True, summary="ok")

    class DummyPool:
        def submit(self, fn):
            return DummyFuture()

    class DummyExecutor:
        def __init__(self, tts=None):
            pass

    class DummyPlanner:
        pass

    monkeypatch.setattr(module, "AutonomousExecutor", DummyExecutor)
    monkeypatch.setattr(module, "get_planner", lambda: DummyPlanner())
    orchestrator = module.AgentOrchestrator(DummyExecutor(), DummyPlanner())
    orchestrator._subagent_pool = DummyPool()
    result = orchestrator.spawn_subagent("child", context={"a": "b"}, timeout=1)
    assert result.achieved is True
    assert result.summary == "ok"

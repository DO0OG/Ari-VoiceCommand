from dataclasses import dataclass

from agent.agent_planner import ActionStep
from agent.autonomous_executor import ExecutionResult


@dataclass
class StepResult:
    step: ActionStep
    exec_result: ExecutionResult
    attempt: int = 1
    was_fixed: bool = False
    failure_kind: str = ""


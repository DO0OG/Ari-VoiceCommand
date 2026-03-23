"""
개발/CI 공용 검증 스크립트.
문법 검사, 유닛 테스트, 템플릿 플래너 스모크 테스트를 한 번에 수행합니다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent

COMPILE_TARGETS = [
    "Main.py",
    "build_exe.py",
    "agent/execution_analysis.py",
    "agent/agent_orchestrator.py",
    "agent/agent_planner.py",
    "agent/autonomous_executor.py",
    "agent/real_verifier.py",
    "agent/strategy_memory.py",
    "memory/user_context.py",
    "memory/memory_manager.py",
    "memory/conversation_history.py",
    "commands/ai_command.py",
]

TEMPLATE_SMOKE = r"""
from agent.agent_planner import AgentPlanner
from agent.llm_provider import LLMProvider

planner = AgentPlanner(LLMProvider(api_key=""))
samples = [
    "바탕화면에 샘플 폴더 만들어줘",
    "시스템 정보 수집해서 md로 저장해줘",
    r"C:\Users\runneradmin\Desktop 폴더 목록 저장해줘",
    "https://example.com 열어줘",
]

for sample in samples:
    steps = planner._build_template_plan(sample)
    if not steps:
        raise SystemExit(f"Template plan missing: {sample}")

print("template routing ok")
"""


def run(command: list[str], description: str) -> None:
    print(f"[validate] {description}", flush=True)
    subprocess.run(command, cwd=HERE, check=True)


def main() -> int:
    compile_targets = [str(HERE / path) for path in COMPILE_TARGETS]
    run([sys.executable, "-m", "py_compile", *compile_targets], "compile critical modules")
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], "unit tests")
    run([sys.executable, "-c", TEMPLATE_SMOKE], "template planner smoke test")
    print("[validate] all checks passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

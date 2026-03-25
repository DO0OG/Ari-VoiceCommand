"""
개발/CI 공용 검증 스크립트.
문법 검사, 유닛 테스트, 템플릿 플래너 스모크 테스트를 한 번에 수행합니다.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent

COMPILE_TARGETS = [
    "Main.py",
    "build_exe.py",
    "core/plugin_loader.py",
    "agent/execution_analysis.py",
    "agent/agent_orchestrator.py",
    "agent/agent_planner.py",
    "agent/autonomous_executor.py",
    "agent/file_tools.py",
    "agent/scheduler.py",
    "agent/proactive_scheduler.py",
    "agent/real_verifier.py",
    "agent/safety_checker.py",
    "agent/strategy_memory.py",
    "services/web_tools.py",
    "core/config_manager.py",
    "memory/user_context.py",
    "memory/memory_manager.py",
    "memory/conversation_history.py",
    "commands/ai_command.py",
    "core/threads.py",
    "tts/cosyvoice_tts.py",
    "tts/cosyvoice_utils.py",
    "tts/cosyvoice_worker.py",
    "tts/fish_tts_ws.py",
    "tts/tts_factory.py",
    "ui/theme.py",
    "ui/theme_runtime.py",
    "ui/common.py",
    "ui/settings_dialog.py",
    "ui/text_interface.py",
    "ui/memory_panel.py",
    "ui/scheduler_panel.py",
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
    "https://example.com 에서 파일 다운로드해서 저장해줘",
    '메모장 열고 "테스트 메모" 입력해줘',
    "크롬으로 https://example.com 열어줘",
    "VSCode 열어줘",
    "계산기 실행해줘",
    r"C:\Users\runneradmin\Desktop\alpha.txt 파일 이름을 beta.txt로 변경해줘",
    r"C:\Users\runneradmin\Desktop\logs\ari.log 로그 리포트 저장해줘",
]

for sample in samples:
    steps = planner._build_template_plan(sample)
    if not steps:
        raise SystemExit(f"Template plan missing: {sample}")

print("template routing ok")
"""


def run(command: list[str], description: str) -> float:
    print(f"[validate] {description}", flush=True)
    start = time.perf_counter()
    subprocess.run(command, cwd=HERE, check=True)
    elapsed = time.perf_counter() - start
    print(f"[validate] {description} completed in {elapsed:.2f}s", flush=True)
    return elapsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ari 저장소 검증 스크립트")
    parser.add_argument("--compile-only", action="store_true", help="문법 검사만 실행")
    parser.add_argument("--tests-only", action="store_true", help="유닛 테스트만 실행")
    parser.add_argument("--smoke-only", action="store_true", help="템플릿 스모크 테스트만 실행")
    parser.add_argument("--no-smoke", action="store_true", help="템플릿 스모크 테스트 생략")
    parser.add_argument("--list", action="store_true", help="검증 항목만 출력하고 종료")
    parser.add_argument("--json", action="store_true", help="검증 계획을 JSON으로 출력")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected_modes = sum([args.compile_only, args.tests_only, args.smoke_only])
    if selected_modes > 1:
        raise SystemExit("compile/tests/smoke 전용 옵션은 하나만 사용할 수 있습니다.")
    if args.list and args.json:
        raise SystemExit("--list 와 --json 은 함께 사용할 수 없습니다.")
    payload = {
        "compile_targets": COMPILE_TARGETS,
        "unit_tests": 'tests/test_*.py',
        "smoke_tests": "template planner routing",
    }
    if args.list:
        print("[validate] compile targets:")
        for path in COMPILE_TARGETS:
            print(f"  - {path}")
        print("[validate] unit tests: tests/test_*.py")
        print("[validate] smoke tests: template planner routing")
        return 0
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    compile_targets = [str(HERE / path) for path in COMPILE_TARGETS]
    if args.compile_only:
        run([sys.executable, "-m", "py_compile", *compile_targets], "compile critical modules")
        print("[validate] compile-only checks passed", flush=True)
        return 0

    if args.tests_only:
        run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], "unit tests")
        print("[validate] tests-only checks passed", flush=True)
        return 0

    if args.smoke_only:
        run([sys.executable, "-c", TEMPLATE_SMOKE], "template planner smoke test")
        print("[validate] smoke-only checks passed", flush=True)
        return 0

    timings = {}
    timings["compile"] = run([sys.executable, "-m", "py_compile", *compile_targets], "compile critical modules")
    timings["tests"] = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], "unit tests")
    if not args.no_smoke:
        timings["smoke"] = run([sys.executable, "-c", TEMPLATE_SMOKE], "template planner smoke test")
    total = sum(timings.values())
    print(f"[validate] summary: {json.dumps({k: round(v, 2) for k, v in timings.items()}, ensure_ascii=False)}", flush=True)
    print(f"[validate] total: {total:.2f}s", flush=True)
    print("[validate] all checks passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

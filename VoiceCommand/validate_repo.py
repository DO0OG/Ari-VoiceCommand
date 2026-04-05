"""
개발/CI 공용 검증 스크립트.
문법 검사, 유닛 테스트, 템플릿 플래너 스모크 테스트를 한 번에 수행합니다.
"""
from __future__ import annotations

import argparse
import json
import os
import py_compile
import runpy
import tempfile
import time
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent

COMPILE_TARGETS = [
    "Main.py",
    "build_exe.py",
    "core/plugin_loader.py",
    "core/settings_schema.py",
    "agent/execution_analysis.py",
    "agent/agent_orchestrator.py",
    "agent/agent_planner.py",
    "agent/autonomous_executor.py",
    "agent/condition_evaluator.py",
    "agent/episode_memory.py",
    "agent/file_tools.py",
    "agent/goal_predictor.py",
    "agent/learning_metrics.py",
    "agent/llm_provider.py",
    "agent/tool_schemas.py",
    "agent/planner_feedback.py",
    "agent/proactive_scheduler.py",
    "agent/real_verifier.py",
    "agent/reflection_engine.py",
    "agent/response_cache.py",
    "agent/regression_guard.py",
    "agent/safety_checker.py",
    "agent/skill_library.py",
    "agent/skill_optimizer.py",
    "agent/strategy_memory.py",
    "agent/weekly_report.py",
    "services/web_tools.py",
    "core/config_manager.py",
    "core/marketplace_client.py",
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
import os
from pathlib import Path
from agent.agent_planner import AgentPlanner
from agent.llm_provider import LLMProvider

planner = AgentPlanner(LLMProvider(api_key=""))
desktop_path = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
desktop_str = str(desktop_path)
samples = [
    "바탕화면에 샘플 폴더 만들어줘",
    "시스템 정보 수집해서 md로 저장해줘",
    f"{desktop_str} 폴더 목록 저장해줘",
    "https://example.com 열어줘",
    "https://example.com 에서 파일 다운로드해서 저장해줘",
    '메모장 열고 "테스트 메모" 입력해줘',
    "크롬으로 https://example.com 열어줘",
    "VSCode 열어줘",
    "계산기 실행해줘",
    os.path.join(desktop_str, "alpha.txt") + " 파일 이름을 beta.txt로 변경해줘",
    os.path.join(desktop_str, "logs", "ari.log") + " 로그 리포트 저장해줘",
]

for sample in samples:
    steps = planner._build_template_plan(sample)
    if not steps:
        raise SystemExit(f"Template plan missing: {sample}")

print("template routing ok")
"""

CLEAN_ENV_SMOKE = r"""
import json
import os
import tempfile
import threading
from pathlib import Path

from agent.learning_metrics import LearningMetrics
from agent.proactive_scheduler import ProactiveScheduler
from core.config_manager import ConfigManager
from core.resource_manager import ResourceManager
from agent import proactive_scheduler as proactive_scheduler_module


def _reset_runtime_state():
    ResourceManager.reset_cache()
    ConfigManager._cached_settings = None
    proactive_scheduler_module._SCHEDULE_FILE = ""
    proactive_scheduler_module._SCHEDULE_RUN_LOG_FILE = ""


original_env = os.environ.get("ARI_APP_DATA_DIR")
original_project_root = ResourceManager._project_root

try:
    template_path = Path.cwd() / "ari_settings.template.json"
    if not template_path.exists():
        raise SystemExit("settings template missing from repo root")

    with tempfile.TemporaryDirectory(prefix="ari_clean_env_") as clean_root:
        runtime_root = os.path.join(clean_root, "runtime")
        os.environ["ARI_APP_DATA_DIR"] = runtime_root
        ResourceManager._project_root = staticmethod(lambda: clean_root)
        _reset_runtime_state()

        defaults = ConfigManager.load_settings()
        if defaults.get("llm_router_enabled") is not True:
            raise SystemExit("default settings not loaded in clean env")

        metrics = LearningMetrics()
        metrics.record("SkillLibrary", activated=True, success=True)
        if not os.path.exists(os.path.join(runtime_root, "learning_metrics.json")):
            raise SystemExit("learning metrics not stored in runtime dir")

        proactive_scheduler_module._SCHEDULE_FILE = proactive_scheduler_module._init_schedule_file()
        proactive_scheduler_module._SCHEDULE_RUN_LOG_FILE = proactive_scheduler_module._init_schedule_log_file()
        scheduler = ProactiveScheduler.__new__(ProactiveScheduler)
        scheduler._tasks = {}
        scheduler._lock = threading.Lock()
        scheduler._run_log_lock = threading.Lock()
        scheduler._save()
        if proactive_scheduler_module._SCHEDULE_FILE != os.path.join(runtime_root, "scheduled_tasks.json"):
            raise SystemExit("scheduler file not isolated in runtime dir")

    with tempfile.TemporaryDirectory(prefix="ari_legacy_env_") as legacy_root:
        runtime_root = os.path.join(legacy_root, ".ari_runtime")
        with open(os.path.join(legacy_root, "ari_settings.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "llm_provider": "gemini",
                    "llm_router_enabled": False,
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
        with open(os.path.join(legacy_root, "scheduled_tasks.json"), "w", encoding="utf-8") as handle:
            json.dump(
                [
                    {
                        "task_id": "legacy-task",
                        "goal": "정리",
                        "schedule_expr": "매일 9시 0",
                        "next_run": "2026-04-01T09:00:00",
                    }
                ],
                handle,
                ensure_ascii=False,
                indent=2,
            )

        os.environ["ARI_APP_DATA_DIR"] = runtime_root
        ResourceManager._project_root = staticmethod(lambda: legacy_root)
        _reset_runtime_state()

        migrated = ConfigManager.load_settings()
        if migrated.get("llm_provider") != "gemini":
            raise SystemExit("legacy settings were not migrated")
        proactive_scheduler_module._SCHEDULE_FILE = proactive_scheduler_module._init_schedule_file()
        proactive_scheduler_module._SCHEDULE_RUN_LOG_FILE = proactive_scheduler_module._init_schedule_log_file()
        scheduler = ProactiveScheduler.__new__(ProactiveScheduler)
        scheduler._tasks = {}
        scheduler._load()
        if "legacy-task" not in scheduler._tasks:
            raise SystemExit("legacy scheduled tasks were not migrated")
        if not os.path.exists(os.path.join(legacy_root, "ari_settings.json")):
            raise SystemExit("legacy settings template should be preserved")
        if os.path.exists(os.path.join(legacy_root, "scheduled_tasks.json")):
            raise SystemExit("legacy scheduled tasks should be cleaned after migration")
finally:
    ResourceManager._project_root = original_project_root
    if original_env is None:
        os.environ.pop("ARI_APP_DATA_DIR", None)
    else:
        os.environ["ARI_APP_DATA_DIR"] = original_env
    _reset_runtime_state()

print("clean environment runtime ok")
"""

MARKETPLACE_CONTRACT_SMOKE = r"""
from pathlib import Path

repo_root = Path.cwd().parent
required = {
    "python_client": repo_root / "VoiceCommand" / "core" / "marketplace_client.py",
    "integration_client": repo_root / "market" / "ari_integration" / "core" / "marketplace_client.py",
    "install_function": repo_root / "market" / "supabase" / "functions" / "install-plugin" / "index.ts",
    "get_function": repo_root / "market" / "supabase" / "functions" / "get-plugin" / "index.ts",
    "status_function": repo_root / "market" / "supabase" / "functions" / "plugin-status" / "index.ts",
    "upload_function": repo_root / "market" / "supabase" / "functions" / "upload-plugin" / "index.ts",
    "finalize_script": repo_root / "market" / "marketplace" / "scripts" / "finalize.py",
    "sql_init": repo_root / "market" / "supabase" / "migrations" / "001_init.sql",
    "sql_patch": repo_root / "market" / "supabase" / "migrations" / "002_add_plugin_sha256.sql",
    "install_sync_sql": repo_root / "market" / "supabase" / "migrations" / "003_record_plugin_install.sql",
    "web_types": repo_root / "market" / "web" / "src" / "lib" / "types.ts",
}

texts = {name: path.read_text(encoding="utf-8") for name, path in required.items()}
if "sha256" not in texts["python_client"] or "sha256" not in texts["integration_client"]:
    raise SystemExit("python marketplace client does not enforce sha256")
if ".select(\"id, name, entry, release_url, sha256, install_count\")" not in texts["install_function"]:
    raise SystemExit("install-plugin function missing sha256 select")
if "record_plugin_install" not in texts["install_function"]:
    raise SystemExit("install-plugin function missing DB sync RPC")
if "sha256: plugin.sha256" not in texts["install_function"]:
    raise SystemExit("install-plugin function missing sha256 response")
if "sha256," not in texts["upload_function"]:
    raise SystemExit("upload-plugin function missing sha256 persistence")
if "plugin zip must be 5MB or smaller" not in texts["upload_function"]:
    raise SystemExit("upload-plugin function missing max size validation")
if "sha256," not in texts["get_function"]:
    raise SystemExit("get-plugin function missing sha256 projection")
if "review_report" not in texts["status_function"]:
    raise SystemExit("plugin-status function missing review report projection")
if "sha256" not in texts["finalize_script"]:
    raise SystemExit("finalize script missing sha256 propagation")
if "sha256 text" not in texts["sql_init"] and "add column if not exists sha256 text" not in texts["sql_patch"]:
    raise SystemExit("sql migration missing sha256 column")
if "record_plugin_install" not in texts["install_sync_sql"]:
    raise SystemExit("sql migration missing install sync function")
if "sha256?: string" not in texts["web_types"]:
    raise SystemExit("web types missing sha256 field")

print("marketplace sha256 contract ok")
"""


def _run_compile(paths: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="ari_compile_check_") as temp_dir:
        temp_root = Path(temp_dir)
        for path in paths:
            source_path = Path(path).resolve()
            try:
                relative_path = source_path.relative_to(HERE)
            except ValueError:
                relative_path = Path(source_path.name)
            target_path = temp_root / relative_path.with_suffix(".pyc")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            py_compile.compile(str(source_path), cfile=str(target_path), doraise=True)


def _run_tests() -> None:
    suite = unittest.defaultTestLoader.discover(str(HERE / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def _run_smoke() -> None:
    previous_cwd = os.getcwd()
    try:
        os.chdir(HERE)
        smoke_scripts = (
            ("template planner routing", TEMPLATE_SMOKE),
            ("clean environment runtime", CLEAN_ENV_SMOKE),
            ("marketplace sha256 contract", MARKETPLACE_CONTRACT_SMOKE),
        )
        for _, script in smoke_scripts:
            with tempfile.NamedTemporaryFile("w", suffix="_smoke.py", encoding="utf-8", delete=False) as temp_file:
                temp_file.write(script)
                temp_path = temp_file.name
            try:
                runpy.run_path(temp_path, run_name="__main__")
            finally:
                os.remove(temp_path)
    finally:
        os.chdir(previous_cwd)


def run(action, description: str) -> float:
    print(f"[validate] {description}", flush=True)
    start = time.perf_counter()
    action()
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
        "unit_tests": "tests/test_*.py",
        "smoke_tests": [
            "template planner routing",
            "clean environment runtime",
            "marketplace sha256 contract",
        ],
    }
    if args.list:
        print("[validate] compile targets:")
        for path in COMPILE_TARGETS:
            print(f"  - {path}")
        print("[validate] unit tests: tests/test_*.py")
        print("[validate] smoke tests:")
        for item in payload["smoke_tests"]:
            print(f"  - {item}")
        return 0
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    compile_paths = [HERE / path for path in COMPILE_TARGETS]
    missing_targets = [str(path.relative_to(HERE)) for path in compile_paths if not path.exists()]
    if missing_targets:
        print(
            f"[validate] skipping missing compile targets: {json.dumps(missing_targets, ensure_ascii=False)}",
            flush=True,
        )
    compile_targets = [str(path) for path in compile_paths if path.exists()]

    if args.compile_only:
        run(lambda: _run_compile(compile_targets), "compile critical modules")
        print("[validate] compile-only checks passed", flush=True)
        return 0

    if args.tests_only:
        run(_run_tests, "unit tests")
        print("[validate] tests-only checks passed", flush=True)
        return 0

    if args.smoke_only:
        run(_run_smoke, "template planner smoke test")
        print("[validate] smoke-only checks passed", flush=True)
        return 0

    timings = {}
    timings["compile"] = run(lambda: _run_compile(compile_targets), "compile critical modules")
    timings["tests"] = run(_run_tests, "unit tests")
    if not args.no_smoke:
        timings["smoke"] = run(_run_smoke, "smoke checks")
    total = sum(timings.values())
    print(f"[validate] summary: {json.dumps({k: round(v, 2) for k, v in timings.items()}, ensure_ascii=False)}", flush=True)
    print(f"[validate] total: {total:.2f}s", flush=True)
    print("[validate] all checks passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

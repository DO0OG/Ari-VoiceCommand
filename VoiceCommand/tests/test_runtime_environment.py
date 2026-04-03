import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.config_manager import ConfigManager
from core.resource_manager import ResourceManager
from agent.proactive_scheduler import ProactiveScheduler
from agent import proactive_scheduler as proactive_scheduler_module


class RuntimeEnvironmentTests(unittest.TestCase):
    def tearDown(self):
        ResourceManager.reset_cache()
        ConfigManager._cached_settings = None
        proactive_scheduler_module._SCHEDULE_FILE = ""
        proactive_scheduler_module._SCHEDULE_RUN_LOG_FILE = ""

    def test_dev_runtime_defaults_to_hidden_runtime_directory(self):
        original_env = os.environ.pop("ARI_APP_DATA_DIR", None)
        try:
            with tempfile.TemporaryDirectory() as project_root:
                with patch.object(ResourceManager, "_project_root", return_value=project_root):
                    ResourceManager.reset_cache()
                    runtime_dir = ResourceManager.get_app_data_dir()
                self.assertEqual(runtime_dir, os.path.join(project_root, ".ari_runtime"))
                self.assertTrue(os.path.isdir(runtime_dir))
        finally:
            if original_env is not None:
                os.environ["ARI_APP_DATA_DIR"] = original_env

    def test_legacy_settings_and_scheduler_state_migrate_into_runtime_dir(self):
        original_env = os.environ.get("ARI_APP_DATA_DIR")
        try:
            with tempfile.TemporaryDirectory() as project_root:
                runtime_dir = os.path.join(project_root, ".ari_runtime")
                with open(os.path.join(project_root, "ari_settings.json"), "w", encoding="utf-8") as handle:
                    json.dump({"llm_provider": "gemini", "llm_router_enabled": False}, handle, ensure_ascii=False)
                with open(os.path.join(project_root, "scheduled_tasks.json"), "w", encoding="utf-8") as handle:
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
                    )

                os.environ["ARI_APP_DATA_DIR"] = runtime_dir
                with patch.object(ResourceManager, "_project_root", return_value=project_root):
                    ResourceManager.reset_cache()
                    ConfigManager._cached_settings = None
                    settings = ConfigManager.load_settings()
                    self.assertEqual(settings["llm_provider"], "gemini")
                    self.assertTrue(os.path.exists(os.path.join(runtime_dir, "ari_settings.json")))

                    proactive_scheduler_module._SCHEDULE_FILE = proactive_scheduler_module._init_schedule_file()
                    proactive_scheduler_module._SCHEDULE_RUN_LOG_FILE = proactive_scheduler_module._init_schedule_log_file()
                    scheduler = ProactiveScheduler.__new__(ProactiveScheduler)
                    scheduler._tasks = {}
                    scheduler._load()
                    self.assertIn("legacy-task", scheduler._tasks)
        finally:
            if original_env is None:
                os.environ.pop("ARI_APP_DATA_DIR", None)
            else:
                os.environ["ARI_APP_DATA_DIR"] = original_env


if __name__ == "__main__":
    unittest.main()

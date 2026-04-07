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
from core.settings_schema import DEFAULT_SETTINGS
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
                logs_dir = os.path.join(project_root, "logs")
                core_logs_dir = os.path.join(project_root, "core", "logs")
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
                os.makedirs(logs_dir, exist_ok=True)
                os.makedirs(core_logs_dir, exist_ok=True)
                with open(os.path.join(logs_dir, "legacy.log"), "w", encoding="utf-8") as handle:
                    handle.write("legacy root log")
                with open(os.path.join(core_logs_dir, "legacy_core.log"), "w", encoding="utf-8") as handle:
                    handle.write("legacy core log")

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
                    self.assertTrue(os.path.exists(os.path.join(runtime_dir, "logs", "legacy.log")))
                    self.assertTrue(os.path.exists(os.path.join(runtime_dir, "logs", "legacy_core.log")))
                    self.assertTrue(os.path.exists(os.path.join(project_root, "ari_settings.json")))
                    self.assertFalse(os.path.exists(os.path.join(project_root, "scheduled_tasks.json")))
                    self.assertFalse(os.path.exists(logs_dir))
                    self.assertFalse(os.path.exists(core_logs_dir))
        finally:
            if original_env is None:
                os.environ.pop("ARI_APP_DATA_DIR", None)
            else:
                os.environ["ARI_APP_DATA_DIR"] = original_env

    def test_load_settings_returns_defensive_copy(self):
        original_env = os.environ.get("ARI_APP_DATA_DIR")
        try:
            with tempfile.TemporaryDirectory() as project_root:
                runtime_dir = os.path.join(project_root, ".ari_runtime")
                os.environ["ARI_APP_DATA_DIR"] = runtime_dir
                with patch.object(ResourceManager, "_project_root", return_value=project_root):
                    ResourceManager.reset_cache()
                    ConfigManager._cached_settings = None

                    first = ConfigManager.load_settings()
                    first["llm_provider"] = "tampered"

                    second = ConfigManager.load_settings()
                    self.assertNotEqual(second["llm_provider"], "tampered")
        finally:
            if original_env is None:
                os.environ.pop("ARI_APP_DATA_DIR", None)
            else:
                os.environ["ARI_APP_DATA_DIR"] = original_env

    def test_default_settings_enable_router_and_weekly_report(self):
        self.assertTrue(DEFAULT_SETTINGS["llm_router_enabled"])
        self.assertTrue(DEFAULT_SETTINGS["weekly_report_enabled"])

    def test_save_settings_restores_defaults_for_type_mismatches(self):
        original_env = os.environ.get("ARI_APP_DATA_DIR")
        try:
            with tempfile.TemporaryDirectory() as project_root:
                runtime_dir = os.path.join(project_root, ".ari_runtime")
                os.environ["ARI_APP_DATA_DIR"] = runtime_dir
                with patch.object(ResourceManager, "_project_root", return_value=project_root):
                    ResourceManager.reset_cache()
                    ConfigManager._cached_settings = None

                    saved = ConfigManager.save_settings(
                        {
                            "llm_provider": "openai",
                            "weekly_report_enabled": "yes",
                            "stt_energy_threshold": True,
                        }
                    )
                    settings = ConfigManager.load_settings()

                self.assertTrue(saved)
                self.assertEqual(settings["llm_provider"], "openai")
                self.assertTrue(settings["weekly_report_enabled"])
                self.assertEqual(settings["stt_energy_threshold"], 300)
        finally:
            if original_env is None:
                os.environ.pop("ARI_APP_DATA_DIR", None)
            else:
                os.environ["ARI_APP_DATA_DIR"] = original_env

    def test_save_settings_preserves_unknown_custom_keys(self):
        original_env = os.environ.get("ARI_APP_DATA_DIR")
        try:
            with tempfile.TemporaryDirectory() as project_root:
                runtime_dir = os.path.join(project_root, ".ari_runtime")
                os.environ["ARI_APP_DATA_DIR"] = runtime_dir
                with patch.object(ResourceManager, "_project_root", return_value=project_root):
                    ResourceManager.reset_cache()
                    ConfigManager._cached_settings = None

                    saved = ConfigManager.save_settings(
                        {
                            "llm_provider": "groq",
                            "custom_flag": {"enabled": True},
                        }
                    )
                    settings = ConfigManager.load_settings()

                self.assertTrue(saved)
                self.assertEqual(settings["llm_provider"], "groq")
                self.assertEqual(settings["custom_flag"], {"enabled": True})
        finally:
            if original_env is None:
                os.environ.pop("ARI_APP_DATA_DIR", None)
            else:
                os.environ["ARI_APP_DATA_DIR"] = original_env

    def test_missing_runtime_settings_bootstrap_from_template(self):
        original_env = os.environ.get("ARI_APP_DATA_DIR")
        try:
            with tempfile.TemporaryDirectory() as project_root:
                runtime_dir = os.path.join(project_root, ".ari_runtime")
                os.environ["ARI_APP_DATA_DIR"] = runtime_dir
                template_path = os.path.join(project_root, "ari_settings.template.json")
                with open(template_path, "w", encoding="utf-8") as handle:
                    json.dump({"llm_provider": "openai", "weekly_report_enabled": True}, handle, ensure_ascii=False)

                with patch.object(ResourceManager, "_project_root", return_value=project_root):
                    ResourceManager.reset_cache()
                    ConfigManager._cached_settings = None
                    settings = ConfigManager.load_settings()

                self.assertEqual(settings["llm_provider"], "openai")
                self.assertTrue(settings["weekly_report_enabled"])
                self.assertTrue(os.path.exists(os.path.join(runtime_dir, "ari_settings.json")))
        finally:
            if original_env is None:
                os.environ.pop("ARI_APP_DATA_DIR", None)
            else:
                os.environ["ARI_APP_DATA_DIR"] = original_env


if __name__ == "__main__":
    unittest.main()

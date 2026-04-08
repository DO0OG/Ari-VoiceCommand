import json
import os
import subprocess  # nosec B404 - 고정된 검증 스크립트만 실행
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


import validate_repo


VOICECOMMAND_ROOT = str(Path(__file__).resolve().parent.parent)


class ValidateRepoTests(unittest.TestCase):
    def test_json_plan_output(self):
        result = subprocess.run(
            [sys.executable, os.path.join(VOICECOMMAND_ROOT, "validate_repo.py"), "--json"],
            # nosec B603 - 입력값이 테스트 코드 내부 고정값임
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
        self.assertIn("compile_targets", payload)
        self.assertIn("agent/execution_analysis.py", payload["compile_targets"])
        self.assertIn("agent/assistant_text_utils.py", payload["compile_targets"])
        self.assertIn("agent/automation_helpers.py", payload["compile_targets"])
        self.assertIn("agent/automation_plan_utils.py", payload["compile_targets"])
        self.assertIn("agent/confirmation_manager.py", payload["compile_targets"])
        self.assertIn("agent/dag_builder.py", payload["compile_targets"])
        self.assertIn("agent/embedder.py", payload["compile_targets"])
        self.assertIn("agent/execution_engine.py", payload["compile_targets"])
        self.assertIn("agent/few_shot_injector.py", payload["compile_targets"])
        self.assertIn("agent/learning_engine.py", payload["compile_targets"])
        self.assertIn("agent/safety_checker.py", payload["compile_targets"])
        self.assertIn("agent/llm_router.py", payload["compile_targets"])
        self.assertIn("agent/ocr_helper.py", payload["compile_targets"])
        self.assertIn("agent/planner_json_utils.py", payload["compile_targets"])
        self.assertIn("agent/verification_engine.py", payload["compile_targets"])
        self.assertIn("core/plugin_sandbox.py", payload["compile_targets"])
        self.assertIn("core/plugin_watcher.py", payload["compile_targets"])
        self.assertIn("core/resource_manager.py", payload["compile_targets"])
        self.assertIn("core/stt_provider.py", payload["compile_targets"])
        self.assertIn("core/VoiceCommand.py", payload["compile_targets"])
        self.assertIn("memory/memory_consolidator.py", payload["compile_targets"])
        self.assertIn("memory/memory_index.py", payload["compile_targets"])
        self.assertIn("memory/trust_engine.py", payload["compile_targets"])
        self.assertIn("memory/user_profile_engine.py", payload["compile_targets"])
        self.assertIn("services/dom_analyser.py", payload["compile_targets"])
        self.assertIn("services/timer_manager.py", payload["compile_targets"])
        self.assertIn("services/web_tools.py", payload["compile_targets"])
        self.assertIn("services/weather_service.py", payload["compile_targets"])
        self.assertIn("tts/tts_base.py", payload["compile_targets"])
        self.assertIn("tts/tts_edge.py", payload["compile_targets"])
        self.assertIn("tts/tts_elevenlabs.py", payload["compile_targets"])
        self.assertIn("tts/tts_openai.py", payload["compile_targets"])
        self.assertIn("ui/character_widget.py", payload["compile_targets"])
        self.assertIn("ui/theme.py", payload["compile_targets"])
        self.assertIn("ui/theme_editor.py", payload["compile_targets"])
        self.assertIn("ui/theme_runtime.py", payload["compile_targets"])
        self.assertIn("ui/settings_llm_page.py", payload["compile_targets"])
        self.assertIn("ui/settings_plugin_page.py", payload["compile_targets"])
        self.assertIn("ui/settings_tts_page.py", payload["compile_targets"])
        self.assertIn("ui/scheduled_tasks_dialog.py", payload["compile_targets"])
        self.assertIn("ui/speech_bubble.py", payload["compile_targets"])
        self.assertIn("ui/stt_settings_dialog.py", payload["compile_targets"])
        self.assertIn("ui/local_installers.py", payload["compile_targets"])
        self.assertIn("ui/marketplace_browser.py", payload["compile_targets"])
        self.assertIn("ui/tray_icon.py", payload["compile_targets"])
        self.assertEqual(payload["unit_tests"], "tests/test_*.py")

    def test_run_compile_writes_pyc_to_temp_location(self):
        source = os.path.join(VOICECOMMAND_ROOT, "agent", "execution_analysis.py")
        captured = {}

        def fake_compile(path, cfile=None, doraise=False):
            captured["path"] = path
            captured["cfile"] = cfile
            captured["doraise"] = doraise

        with patch("validate_repo.py_compile.compile", side_effect=fake_compile):
            validate_repo._run_compile([source])

        self.assertEqual(os.path.normpath(captured["path"]), os.path.normpath(source))
        self.assertTrue(captured["cfile"])
        self.assertNotIn("__pycache__", captured["cfile"])
        self.assertTrue(captured["cfile"].endswith(".pyc"))
        self.assertTrue(captured["doraise"])


if __name__ == "__main__":
    unittest.main()

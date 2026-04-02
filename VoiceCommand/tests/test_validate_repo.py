import json
import os
import subprocess  # nosec B404 - 고정된 검증 스크립트만 실행
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import validate_repo


class ValidateRepoTests(unittest.TestCase):
    def test_json_plan_output(self):
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, "validate_repo.py"), "--json"],
            # nosec B603 - 입력값이 테스트 코드 내부 고정값임
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
        self.assertIn("compile_targets", payload)
        self.assertIn("agent/execution_analysis.py", payload["compile_targets"])
        self.assertIn("agent/safety_checker.py", payload["compile_targets"])
        self.assertIn("services/web_tools.py", payload["compile_targets"])
        self.assertIn("ui/theme.py", payload["compile_targets"])
        self.assertIn("ui/theme_runtime.py", payload["compile_targets"])
        self.assertEqual(payload["unit_tests"], "tests/test_*.py")

    def test_run_compile_writes_pyc_to_temp_location(self):
        source = os.path.join(ROOT, "agent", "execution_analysis.py")
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

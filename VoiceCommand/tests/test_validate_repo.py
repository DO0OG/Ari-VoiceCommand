import json
import os
import subprocess  # nosec B404 - 고정된 검증 스크립트만 실행
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))


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


if __name__ == "__main__":
    unittest.main()

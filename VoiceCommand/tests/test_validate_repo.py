import json
import os
import subprocess
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))


class ValidateRepoTests(unittest.TestCase):
    def test_json_plan_output(self):
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, "validate_repo.py"), "--json"],
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

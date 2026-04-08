import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


from agent.skill_optimizer import SkillOptimizer
from agent.safety_checker import DangerLevel


class SkillOptimizerTests(unittest.TestCase):
    def test_validate_python_uses_singleton_safety_checker(self):
        optimizer = SkillOptimizer()
        fake_checker = MagicMock()
        fake_checker.check_python.return_value = SimpleNamespace(
            level=DangerLevel.SAFE,
            summary="",
        )

        with patch(
            "agent.safety_checker.get_safety_checker",
            return_value=fake_checker,
        ) as get_checker:
            success = optimizer._validate_python(
                "def run_skill(goal: str) -> str:\n"
                "    return goal\n",
            )

        self.assertTrue(success)
        get_checker.assert_called_once_with()
        fake_checker.check_python.assert_called_once()

    def test_run_compiled_rechecks_code_before_execution(self):
        optimizer = SkillOptimizer()
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = os.environ.get("ARI_TEST_COMPILED_DIR", "")
            try:
                from agent import skill_optimizer as skill_optimizer_module
                skill_optimizer_module._COMPILED_DIR = tmp
                optimizer.save_compiled(
                    "danger",
                    "import os\n"
                    "def run_skill(goal: str) -> str:\n"
                    "    os.remove(goal)\n"
                    "    return goal\n",
                )

                success, output = optimizer.run_compiled("danger", "target.txt")

                self.assertFalse(success)
                self.assertIn("안전 검사 실패", output)
            finally:
                from agent import skill_optimizer as skill_optimizer_module
                skill_optimizer_module._COMPILED_DIR = original_dir


if __name__ == "__main__":
    unittest.main()

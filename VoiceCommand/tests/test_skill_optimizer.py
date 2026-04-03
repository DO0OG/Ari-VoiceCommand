import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.skill_optimizer import SkillOptimizer


class SkillOptimizerTests(unittest.TestCase):
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

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from agent.autonomous_executor import AutonomousExecutor
from agent.execution_engine import ExecutionEngine
from core import script_worker

MAIN_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Main.py")


def _bundled_style_command(script_path: str) -> list[str]:
    """배포 실행 파일 대신 개발용 Main.py에 같은 숨은 인자를 넘겨 배포판 경로를 흉내 낸다."""
    return [sys.executable, MAIN_PY, script_worker.SCRIPT_WORKER_ARGUMENT, script_path]


class PythonScriptCommandTests(unittest.TestCase):
    def test_development_uses_current_interpreter(self):
        with patch.object(script_worker, "is_bundled", return_value=False):
            self.assertEqual(script_worker.python_script_command("run.py"), [sys.executable, "run.py"])

    def test_bundle_reenters_real_executable_with_hidden_argument(self):
        with patch.object(script_worker, "is_bundled", return_value=True), \
                patch.object(script_worker, "bundled_executable_path", return_value=r"C:\Ari\Ari.exe"):
            command = script_worker.python_script_command("run.py")
        self.assertEqual(command, [r"C:\Ari\Ari.exe", "--ari-run-python-script", "run.py"])

    def test_dispatch_ignores_other_arguments(self):
        self.assertIsNone(script_worker.dispatch_script_command(["Ari.exe"]))
        self.assertIsNone(script_worker.dispatch_script_command(["Ari.exe", "--decision-self-test", "x"]))


class BundledPythonExecutionTests(unittest.TestCase):
    def _run(self, code: str):
        executor = AutonomousExecutor()
        with patch("agent.autonomous_executor.python_script_command", side_effect=_bundled_style_command):
            return executor._do_run_python(code)

    def test_runner_script_runs_through_hidden_worker_argument(self):
        result = self._run('print("안녕 " + str(1 + 1))')
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.output, "안녕 2")

    def test_script_error_is_reported_as_failure(self):
        result = self._run('raise ValueError("boom")')
        self.assertFalse(result.success)
        self.assertIn("ValueError", result.error)


class BundledPipInstallTests(unittest.TestCase):
    def test_missing_module_is_not_installed_in_bundle(self):
        engine = ExecutionEngine.__new__(ExecutionEngine)
        engine._say = MagicMock()
        engine._run_pip_install = MagicMock(return_value=True)
        with patch("agent.execution_engine.is_bundled", return_value=True):
            installed = engine._auto_install_if_needed("ModuleNotFoundError: No module named 'yaml'")
        self.assertFalse(installed)
        engine._run_pip_install.assert_not_called()
        engine._say.assert_called_once()
        self.assertIn("pyyaml", engine._say.call_args.args[0])


if __name__ == "__main__":
    unittest.main()

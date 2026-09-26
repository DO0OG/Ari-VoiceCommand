import os
import sys
import unittest
from unittest.mock import patch

from core import core_manager, resource_manager
from tts import cosyvoice_tts


def _nuitka():
    """Nuitka 배포판처럼 sys.frozen 없이 __compiled__만 있는 상태를 흉내 낸다."""
    return patch.dict(resource_manager.__dict__, {"__compiled__": object()})


class BundleDetectionTests(unittest.TestCase):
    def test_nuitka_bundle_is_detected_without_sys_frozen(self):
        self.assertFalse(getattr(sys, "frozen", False))
        with _nuitka():
            self.assertTrue(resource_manager.is_bundled())

    def test_file_watcher_is_skipped_in_nuitka_bundle(self):
        with _nuitka(), patch.object(core_manager, "Observer") as observer:
            self.assertIsNone(core_manager.start_file_watcher())
        observer.assert_not_called()

    def test_restart_relaunches_real_executable_in_bundle(self):
        with _nuitka(), \
                patch.object(core_manager, "bundled_executable_path", return_value=r"C:\Ari\Ari.exe"), \
                patch.object(sys, "argv", [r"C:\Ari\Main.py", "--flag"]):
            self.assertEqual(core_manager._restart_command(), (r"C:\Ari\Ari.exe", ["--flag"]))

    def test_restart_uses_interpreter_and_script_in_development(self):
        with patch.object(sys, "argv", ["Main.py", "--flag"]):
            executable, args = core_manager._restart_command()
        self.assertEqual(executable, sys.executable)
        self.assertEqual(args, [os.path.abspath("Main.py"), "--flag"])

    def test_cosyvoice_worker_is_next_to_nuitka_executable(self):
        fake_python = os.path.join("C:\\", "Program Files", "Ari", "python.exe")
        with _nuitka(), patch.object(sys, "executable", fake_python):
            path = cosyvoice_tts._get_worker_script()
        self.assertEqual(path, os.path.join(os.path.dirname(os.path.abspath(fake_python)), "cosyvoice_worker.py"))

    def test_cosyvoice_worker_keeps_pyinstaller_meipass(self):
        with patch.object(sys, "frozen", True, create=True), \
                patch.object(sys, "_MEIPASS", "bundle_root", create=True):
            path = cosyvoice_tts._get_worker_script()
        self.assertEqual(path, os.path.join("bundle_root", "cosyvoice_worker.py"))


if __name__ == "__main__":
    unittest.main()

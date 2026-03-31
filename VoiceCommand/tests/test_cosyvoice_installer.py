import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import cosyvoice_installer


class CosyVoiceInstallerTests(unittest.TestCase):
    @patch("core.cosyvoice_installer.download_model")
    @patch("core.cosyvoice_installer.subprocess.run")
    @patch("core.cosyvoice_installer.check_command", return_value=True)
    @patch("core.cosyvoice_installer.os.path.exists")
    @patch("core.cosyvoice_installer.os.makedirs")
    def test_install_cosyvoice_returns_absolute_dir(
        self,
        _makedirs,
        mock_exists,
        _check_command,
        _subprocess_run,
        _download_model,
    ):
        def exists_side_effect(path):
            return path.endswith("requirements.txt")

        mock_exists.side_effect = exists_side_effect

        result = cosyvoice_installer.install_cosyvoice(r".\temp\CosyVoice", log=lambda _msg: None)

        self.assertTrue(os.path.isabs(result))
        self.assertTrue(result.endswith(os.path.join("temp", "CosyVoice")))


if __name__ == "__main__":
    unittest.main()

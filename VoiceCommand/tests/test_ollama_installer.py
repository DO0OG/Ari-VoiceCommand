import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import ollama_installer


class OllamaInstallerTests(unittest.TestCase):
    def test_normalize_models_removes_empty_and_duplicates(self):
        models = ollama_installer.normalize_models(
            ["llama3.2:3b", "", "qwen3:4b", "llama3.2:3b", "  ", "qwen3:4b"]
        )

        self.assertEqual(models, ["llama3.2:3b", "qwen3:4b"])

    @patch("core.ollama_installer.pull_models")
    @patch("core.ollama_installer.ensure_ollama_server")
    @patch("core.ollama_installer.find_ollama_executable", return_value=r"C:\Ollama\ollama.exe")
    @patch("core.ollama_installer.is_ollama_installed", return_value=True)
    def test_install_ollama_skips_installer_when_already_installed(
        self,
        _installed,
        _find_exe,
        mock_ensure_server,
        mock_pull_models,
    ):
        mock_pull_models.return_value = ["llama3.2:3b"]

        result = ollama_installer.install_ollama(models=["llama3.2:3b"], log=lambda _msg: None)

        self.assertEqual(result["ollama_exe"], r"C:\Ollama\ollama.exe")
        self.assertEqual(result["installed_models"], ["llama3.2:3b"])
        mock_ensure_server.assert_called_once()
        mock_pull_models.assert_called_once()

    @patch("core.ollama_installer._post_local_json")
    @patch("core.ollama_installer._require_existing_executable", return_value=r"C:\Ollama\ollama.exe")
    def test_pull_models_uses_local_http_api(
        self,
        _require_executable,
        mock_post,
    ):
        installed = ollama_installer.pull_models(
            r"C:\Ollama\ollama.exe",
            ["llama3.2:3b", "qwen3:4b"],
            ollama_installer.DEFAULT_OLLAMA_BASE_URL,
            log=lambda _msg: None,
        )

        self.assertEqual(installed, ["llama3.2:3b", "qwen3:4b"])
        self.assertEqual(mock_post.call_count, 2)


if __name__ == "__main__":
    unittest.main()

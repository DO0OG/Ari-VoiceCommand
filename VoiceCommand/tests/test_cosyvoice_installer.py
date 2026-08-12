import os
import sys
import unittest
from unittest.mock import call, patch


from core import cosyvoice_installer


class CosyVoiceInstallerTests(unittest.TestCase):
    def test_install_cosyvoice_uses_injected_python(self):
        def exists_side_effect(path):
            return os.fspath(path).endswith("requirements.txt")

        python_exe = os.path.abspath(sys.executable)
        with (
            patch("core.cosyvoice_installer.download_model") as download_model,
            patch("core.cosyvoice_installer.subprocess.run") as subprocess_run,
            patch("core.cosyvoice_installer._ensure_tts_venv") as ensure_tts_venv,
            patch(
                "core.cosyvoice_installer._git_executable", return_value="git"
            ),
            patch(
                "core.cosyvoice_installer.os.path.exists",
                side_effect=exists_side_effect,
            ),
            patch("core.cosyvoice_installer.os.makedirs"),
        ):
            result = cosyvoice_installer.install_cosyvoice(
                r".\temp\CosyVoice",
                log=lambda _message: None,
                python_exe=python_exe,
            )

        self.assertTrue(os.path.isabs(result))
        self.assertTrue(result.endswith(os.path.join("temp", "CosyVoice")))
        ensure_tts_venv.assert_not_called()
        download_model.assert_called_once()
        self.assertIn(
            call(
                [
                    python_exe,
                    "-m",
                    "pip",
                    "install",
                    "huggingface_hub",
                    "torch",
                    "torchaudio",
                    "--upgrade",
                ],
                check=False,
            ),
            subprocess_run.call_args_list,
        )

    def test_install_cosyvoice_defaults_to_tts_venv(self):
        tts_python = os.path.abspath(r".venv-tts\Scripts\python.exe")
        with (
            patch("core.cosyvoice_installer.download_model"),
            patch("core.cosyvoice_installer.subprocess.run") as subprocess_run,
            patch(
                "core.cosyvoice_installer._ensure_tts_venv",
                return_value=tts_python,
            ) as ensure_tts_venv,
            patch(
                "core.cosyvoice_installer._git_executable", return_value="git"
            ),
            patch("core.cosyvoice_installer.os.path.exists", return_value=True),
        ):
            cosyvoice_installer.install_cosyvoice(
                r".\temp\CosyVoice", log=lambda _message: None
            )

        ensure_tts_venv.assert_called_once_with()
        self.assertIn(
            call(
                [
                    tts_python,
                    "-m",
                    "pip",
                    "install",
                    "huggingface_hub",
                    "torch",
                    "torchaudio",
                    "--upgrade",
                ],
                check=False,
            ),
            subprocess_run.call_args_list,
        )

    def test_ensure_tts_venv_creates_missing_environment(self):
        expected_python = cosyvoice_installer._tts_venv_python_path()
        with (
            patch(
                "core.cosyvoice_installer.os.path.exists",
                side_effect=(False, True),
            ),
            patch("core.cosyvoice_installer.venv.EnvBuilder") as env_builder,
        ):
            result = cosyvoice_installer._ensure_tts_venv()

        self.assertEqual(expected_python, result)
        env_builder.assert_called_once_with(with_pip=True)
        env_builder.return_value.create.assert_called_once_with(
            cosyvoice_installer.TTS_VENV_DIR
        )


if __name__ == "__main__":
    unittest.main()

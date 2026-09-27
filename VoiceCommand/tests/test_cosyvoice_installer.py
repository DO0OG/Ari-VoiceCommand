import os
import tempfile
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import call, patch

from core import cosyvoice_installer


def _write_required_model_files(model_dir):
    os.makedirs(model_dir, exist_ok=True)
    for name in cosyvoice_installer._MODEL_REQUIRED_FILES:
        with open(os.path.join(model_dir, name), "wb") as model_file:
            model_file.write(b"model")


class CosyVoiceInstallerTests(unittest.TestCase):
    def test_install_cosyvoice_uses_injected_python_and_checks_each_command(self):
        def exists_side_effect(path):
            return os.fspath(path).endswith("requirements.txt")

        python_exe = os.path.abspath("python.exe")
        with (
            patch("core.cosyvoice_installer.download_model") as download_model,
            patch(
                "core.cosyvoice_installer.subprocess.run",
                return_value=SimpleNamespace(returncode=0),
            ) as subprocess_run,
            patch("core.cosyvoice_installer._ensure_tts_venv") as ensure_tts_venv,
            patch("core.cosyvoice_installer._git_executable", return_value="git"),
            patch("core.cosyvoice_installer.os.path.exists", side_effect=exists_side_effect),
            patch("core.cosyvoice_installer.mark_cosyvoice_install_started"),
            patch("core.cosyvoice_installer.mark_cosyvoice_install_complete", return_value=True),
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
                ["git", "clone", "--recursive", cosyvoice_installer.REPO_URL, result],
                check=False,
            ),
            subprocess_run.call_args_list,
        )
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
        self.assertIn(
            call([python_exe, "-m", "pip", "install", "-r", os.path.join(result, "requirements.txt")], check=False),
            subprocess_run.call_args_list,
        )

    def test_install_failure_reports_stage_and_stops(self):
        with (
            patch("core.cosyvoice_installer.download_model") as download_model,
            patch(
                "core.cosyvoice_installer.subprocess.run",
                return_value=SimpleNamespace(returncode=128),
            ),
            patch("core.cosyvoice_installer._git_executable", return_value="git"),
            patch("core.cosyvoice_installer.os.path.exists", return_value=False),
            patch("core.cosyvoice_installer.mark_cosyvoice_install_started"),
            patch("core.cosyvoice_installer.os.makedirs"),
        ):
            with self.assertRaisesRegex(RuntimeError, "저장소 클론.*128"):
                cosyvoice_installer.install_cosyvoice(
                    r".\temp\CosyVoice",
                    log=lambda _message: None,
                    python_exe="python.exe",
                )

        download_model.assert_not_called()

    def test_tts_venv_uses_user_data_location_and_recognizes_legacy_location(self):
        writable_dir = os.path.abspath(r".ari_runtime\.venv-tts")
        writable_python = cosyvoice_installer._tts_venv_python_in(writable_dir)
        legacy_python = cosyvoice_installer._tts_venv_python_in(
            cosyvoice_installer.LEGACY_TTS_VENV_DIR
        )

        with (
            patch.object(cosyvoice_installer, "_writable_tts_venv_dir", return_value=writable_dir),
            patch(
                "core.cosyvoice_installer.os.path.isfile",
                side_effect=lambda path: os.fspath(path) == writable_python,
            ),
        ):
            self.assertEqual(cosyvoice_installer._tts_venv_python_path(), writable_python)

        with (
            patch.object(cosyvoice_installer, "_writable_tts_venv_dir", return_value=writable_dir),
            patch(
                "core.cosyvoice_installer.os.path.isfile",
                side_effect=lambda path: os.fspath(path) == legacy_python,
            ),
        ):
            self.assertEqual(cosyvoice_installer._tts_venv_python_path(), legacy_python)

    def test_ensure_tts_venv_creates_at_writable_location(self):
        writable_dir = os.path.abspath(r".ari_runtime\.venv-tts")
        python_exe = cosyvoice_installer._tts_venv_python_in(writable_dir)
        with (
            patch.object(cosyvoice_installer, "_writable_tts_venv_dir", return_value=writable_dir),
            patch(
                "core.cosyvoice_installer.os.path.isfile",
                side_effect=(False, False, False, True),
            ),
            patch("core.cosyvoice_installer._base_python_executable", return_value="python.exe"),
            patch("core.cosyvoice_installer._create_tts_venv") as create_venv,
        ):
            result = cosyvoice_installer._ensure_tts_venv()

        self.assertEqual(result, python_exe)
        create_venv.assert_called_once_with(writable_dir, "python.exe", cosyvoice_installer.logging.info)

    def test_create_venv_uses_base_python_and_checks_exit_code(self):
        with patch(
            "core.cosyvoice_installer.subprocess.run",
            return_value=SimpleNamespace(returncode=0),
        ) as subprocess_run:
            cosyvoice_installer._create_tts_venv("C:/AppData/Ari/.venv-tts", "C:/Python/python.exe", lambda _message: None)

        subprocess_run.assert_called_once_with(
            ["C:/Python/python.exe", "-m", "venv", "C:/AppData/Ari/.venv-tts"],
            check=False,
        )

    def test_bundled_install_requires_a_runnable_external_python(self):
        with (
            patch("core.resource_manager.is_bundled", return_value=True),
            patch("core.cosyvoice_installer.shutil.which", return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "Python 3"):
                cosyvoice_installer._base_python_executable()

    def test_download_resumes_in_place_and_marks_only_complete_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            model_dir = os.path.join(temp_dir, "model")
            hub = ModuleType("huggingface_hub")

            def snapshot_download(repo_id, revision, local_dir):
                self.assertEqual(repo_id, cosyvoice_installer.MODEL_REPO_ID)
                self.assertEqual(revision, cosyvoice_installer.MODEL_REVISION)
                _write_required_model_files(local_dir)

            hub.snapshot_download = snapshot_download
            with patch.dict("sys.modules", {"huggingface_hub": hub}):
                cosyvoice_installer.download_model(model_dir)

            self.assertTrue(cosyvoice_installer._is_complete_model(model_dir))

    def test_failed_download_remains_resumable_but_not_complete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            model_dir = os.path.join(temp_dir, "model")
            hub = ModuleType("huggingface_hub")

            def partial_download(repo_id, revision, local_dir):
                os.makedirs(local_dir, exist_ok=True)
                with open(os.path.join(local_dir, "cosyvoice3.yaml"), "wb") as model_file:
                    model_file.write(b"partial")
                raise RuntimeError("network interrupted")

            hub.snapshot_download = partial_download
            with patch.dict("sys.modules", {"huggingface_hub": hub}):
                with self.assertRaisesRegex(RuntimeError, "network interrupted"):
                    cosyvoice_installer.download_model(model_dir)

            self.assertTrue(os.path.isfile(os.path.join(model_dir, "cosyvoice3.yaml")))
            self.assertFalse(cosyvoice_installer._is_complete_model(model_dir))

    def test_installing_state_does_not_suppress_prompt_after_model_download(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cosyvoice_dir = os.path.join(temp_dir, "CosyVoice")
            model_dir = os.path.join(
                cosyvoice_dir,
                "pretrained_models",
                "Fun-CosyVoice3-0.5B",
            )
            flag_file = os.path.join(temp_dir, ".cosyvoice_asked")
            _write_required_model_files(model_dir)
            cosyvoice_installer.mark_cosyvoice_install_started(cosyvoice_dir, flag_file)

            self.assertFalse(cosyvoice_installer.is_cosyvoice_install_recorded(flag_file, cosyvoice_dir))
            self.assertTrue(cosyvoice_installer.mark_cosyvoice_install_complete(cosyvoice_dir, flag_file))
            self.assertTrue(cosyvoice_installer.is_cosyvoice_install_recorded(flag_file, cosyvoice_dir))

    def test_declined_prompt_is_not_asked_again(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            flag_file = os.path.join(temp_dir, ".cosyvoice_asked")
            self.assertFalse(cosyvoice_installer.is_cosyvoice_install_recorded(flag_file, ""))
            cosyvoice_installer.mark_cosyvoice_prompt_declined(flag_file)
            self.assertTrue(cosyvoice_installer.is_cosyvoice_install_recorded(flag_file, ""))


if __name__ == "__main__":
    unittest.main()

import io
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core import cosyvoice_installer, ollama_installer
from ui.local_installers import LocalInstallDetectThread, LocalInstallSection
from ui.settings_tts_page import _TTSSettingsPage


def _touch(path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()
    return path


class OllamaDetectionTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = self._temp.name

    def tearDown(self):
        self._temp.cleanup()

    def _find(self, configured: str, on_path: str | None = None):
        with patch("core.config_manager.ConfigManager.get", return_value=configured), \
                patch.object(ollama_installer.shutil, "which", return_value=on_path), \
                patch.object(ollama_installer, "_default_install_dir", return_value=os.path.join(self.root, "none")):
            return ollama_installer.find_ollama_executable()

    def test_configured_executable_is_checked_first(self):
        configured = _touch(os.path.join(self.root, "custom", "ollama.exe"))
        self.assertEqual(self._find(configured, on_path=r"C:\other\ollama.exe"), os.path.abspath(configured))

    def test_missing_or_wrong_configured_file_falls_back_to_path(self):
        wrong = _touch(os.path.join(self.root, "custom", "notepad.exe"))
        self.assertEqual(self._find(wrong, on_path=r"C:\other\ollama.exe"), r"C:\other\ollama.exe")
        missing = os.path.join(self.root, "gone", "ollama.exe")
        self.assertEqual(self._find(missing, on_path=r"C:\other\ollama.exe"), r"C:\other\ollama.exe")
        self.assertIsNone(self._find("", on_path=None))

    def test_installed_models_are_read_from_local_server(self):
        body = json.dumps({"models": [{"name": "llama3.2:3b"}, {"name": "qwen3:4b"}, {"name": "qwen3:4b"}]})
        with patch.object(ollama_installer, "_safe_open_url", return_value=io.BytesIO(body.encode("utf-8"))) as opener:
            models = ollama_installer.list_installed_models()
        self.assertEqual(models, ["llama3.2:3b", "qwen3:4b"])
        self.assertEqual(opener.call_args.args[0], "http://localhost:11434/api/tags")

    def test_installed_models_is_none_when_server_does_not_answer(self):
        with patch.object(ollama_installer, "_safe_open_url", side_effect=urllib.error.URLError("refused")):
            self.assertIsNone(ollama_installer.list_installed_models())


class CosyVoiceDetectionTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = self._temp.name
        self.default_dir = os.path.join(self.root, "CosyVoice")

    def tearDown(self):
        self._temp.cleanup()

    def _find(self, configured: str, auto: str = "") -> str:
        with patch.object(cosyvoice_installer, "DEFAULT_COSYVOICE_DIR", self.default_dir), \
                patch("tts.cosyvoice_tts._get_cosyvoice_dir", return_value=auto):
            return cosyvoice_installer.find_cosyvoice_dir(configured)

    def test_candidate_needs_pretrained_models_marker(self):
        without_marker = os.path.join(self.root, "empty")
        os.makedirs(without_marker)
        self.assertEqual(self._find(without_marker), "")

    def test_configured_path_wins_then_auto_then_installer_default(self):
        configured = os.path.join(self.root, "configured")
        auto = os.path.join(self.root, "auto")
        for path in (configured, auto, self.default_dir):
            os.makedirs(os.path.join(path, "pretrained_models"))
        self.assertEqual(self._find(configured, auto), os.path.abspath(configured))
        self.assertEqual(self._find("", auto), os.path.abspath(auto))
        self.assertEqual(self._find(""), os.path.abspath(self.default_dir))


class LocalInstallUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_detect_thread_reports_both_programs(self):
        thread = LocalInstallDetectThread("C:/CosyVoice")
        received = []
        thread.done.connect(received.append)
        with patch("core.ollama_installer.find_ollama_executable", return_value=r"C:\Ollama\ollama.exe"), \
                patch("core.ollama_installer.list_installed_models", return_value=["qwen3:4b"]), \
                patch("core.cosyvoice_installer.find_cosyvoice_dir", return_value=r"C:\CosyVoice") as find_dir:
            thread.run()
        find_dir.assert_called_once_with("C:/CosyVoice")
        self.assertEqual(received, [{
            "ollama_path": r"C:\Ollama\ollama.exe",
            "ollama_models": ["qwen3:4b"],
            "cosyvoice_dir": r"C:\CosyVoice",
        }])

    def test_installed_ollama_turns_button_into_model_download(self):
        section = LocalInstallSection()
        section._on_detected({"ollama_path": r"C:\Ollama\ollama.exe", "ollama_models": None, "cosyvoice_dir": ""})
        self.assertEqual(section.ollama_install_btn.text(), "모델 받기")
        self.assertIn(r"C:\Ollama\ollama.exe", section.ollama_status.text())
        self.assertEqual(section.cosyvoice_status.text(), "설치되지 않음")

        section._on_detected({"ollama_path": "", "ollama_models": None, "cosyvoice_dir": ""})
        self.assertEqual(section.ollama_install_btn.text(), "Ollama 설치/모델 받기")

    def test_detected_cosyvoice_fills_setting_and_ollama_path_is_saved(self):
        page = _TTSSettingsPage({"ollama_executable_path": r"D:\Tools\ollama.exe"})
        page.local_install_section._on_detected(
            {"ollama_path": "", "ollama_models": None, "cosyvoice_dir": r"D:\CosyVoice"}
        )
        values = page.get_values()
        self.assertEqual(values["cosyvoice_dir"], r"D:\CosyVoice")
        self.assertEqual(values["ollama_executable_path"], r"D:\Tools\ollama.exe")

    def test_existing_cosyvoice_asks_before_reinstalling(self):
        page = _TTSSettingsPage({})
        page.local_install_section.cosyvoice_dir = r"D:\CosyVoice"
        with patch("ui.settings_tts_page.QMessageBox.question", return_value=MagicMock()) as question, \
                patch("ui.settings_tts_page.CosyVoiceInstallerThread") as installer:
            page._install_cosyvoice()
        self.assertIn(r"D:\CosyVoice", question.call_args.args[2])
        installer.assert_not_called()

    def test_custom_elevenlabs_ids_survive_save_and_typed_id_wins(self):
        page = _TTSSettingsPage({"elevenlabs_model_id": "eleven_custom", "elevenlabs_voice_id": "voice_saved"})
        values = page.get_values()
        self.assertEqual(values["elevenlabs_model_id"], "eleven_custom")
        self.assertEqual(values["elevenlabs_voice_id"], "voice_saved")

        page.elevenlabs_model_combo.setEditText("eleven_typed")
        self.assertEqual(page.get_values()["elevenlabs_model_id"], "eleven_typed")

    def _run_elevenlabs_action(self, page, callback, *, cleanup):
        release, finished = threading.Event(), threading.Event()

        def action():
            release.wait(2)
            finished.set()
            return ["late"]

        page._start_elevenlabs_action(page.elevenlabs_models_button, action, callback)
        if cleanup:
            page.cleanup_threads()
        release.set()
        self.assertTrue(finished.wait(2))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not callback.called:
            QApplication.processEvents()
            time.sleep(0.01)

    def test_elevenlabs_result_is_handled_on_gui_thread(self):
        page = _TTSSettingsPage({})
        thread_ids = []
        callback = MagicMock(side_effect=lambda *_: thread_ids.append(threading.get_ident()))
        self._run_elevenlabs_action(page, callback, cleanup=False)
        callback.assert_called_once_with(["late"], "")
        self.assertEqual(thread_ids, [threading.get_ident()])
        self.assertTrue(page.elevenlabs_models_button.isEnabled())

    def test_cleanup_stops_elevenlabs_result_handling(self):
        page = _TTSSettingsPage({})
        callback = MagicMock()
        self._run_elevenlabs_action(page, callback, cleanup=True)
        callback.assert_not_called()

    def test_empty_elevenlabs_model_falls_back_to_default(self):
        page = _TTSSettingsPage({})
        page.elevenlabs_model_combo.setEditText("")
        self.assertEqual(page.get_values()["elevenlabs_model_id"], "eleven_multilingual_v2")


if __name__ == "__main__":
    unittest.main()

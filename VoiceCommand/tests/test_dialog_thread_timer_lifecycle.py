import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QLabel

from ui.common import show_temp_status
from ui.settings_dialog import SettingsDialog
from ui.skills_dialog import SkillsDialog, _live_install_threads
from ui.settings_tts_page import (
    _TTSSettingsPage,
    _live_installer_threads,
)


class DialogThreadTimerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_closed_settings_page_ignores_installer_results(self):
        page = SimpleNamespace(_closed=True, local_install_section=SimpleNamespace(
            start_detection=lambda: self.fail("closed page started detection")
        ))

        with patch("ui.settings_tts_page.QMessageBox.information") as information, \
                patch("ui.settings_tts_page.QMessageBox.warning") as warning:
            _TTSSettingsPage._on_ollama_install_done(page, True, "done", {})
            _TTSSettingsPage._on_cosyvoice_install_done(page, True, "done", "path")

            information.assert_not_called()
            warning.assert_not_called()

    def test_install_is_not_started_twice_while_previous_install_runs(self):
        page = SimpleNamespace()
        with patch("ui.settings_tts_page._installer_running", return_value=True), \
                patch("ui.settings_tts_page.QMessageBox.information") as information, \
                patch("ui.settings_tts_page.CosyVoiceInstallerThread") as cosyvoice_thread, \
                patch("ui.settings_tts_page.OllamaInstallDialog") as ollama_dialog:
            _TTSSettingsPage._install_cosyvoice(page)
            _TTSSettingsPage._open_ollama_installer(page)

            self.assertEqual(information.call_count, 2)
            cosyvoice_thread.assert_not_called()
            ollama_dialog.assert_not_called()

    def test_skill_install_and_update_wait_for_install_started_by_closed_dialog(self):
        previous = MagicMock()
        previous.isRunning.return_value = True
        dialog = SimpleNamespace(
            source_input=SimpleNamespace(text=lambda: "https://example.com/skill.git"),
            _install_thread=None,
            _selected_skill_name=lambda: "sample",
        )
        _live_install_threads.add(previous)
        try:
            with patch("ui.skills_dialog.QMessageBox.information") as information,                     patch("ui.skills_dialog._SkillInstallThread") as install_thread:
                SkillsDialog._on_install(dialog)
                SkillsDialog._on_update(dialog)

                self.assertEqual(information.call_count, 2)
                install_thread.assert_not_called()
        finally:
            _live_install_threads.discard(previous)

    def test_done_stops_embedding_timers_without_leaking_threads(self):
        with patch("ui.settings_dialog.ConfigManager.load_settings", return_value={}), \
                patch("ui.settings_dialog.get_update_status", return_value={}), \
                patch("services.google_auth.is_connected", return_value=False):
            for _ in range(30):
                dialog = SettingsDialog()
                timer = dialog._agent_page.embedding_status_timer
                self.assertTrue(timer.isActive())

                dialog.done(0)

                self.assertFalse(timer.isActive())
                self.assertFalse(any(
                    child.isActive()
                    for child in dialog.findChildren(QTimer)
                ))
                self.assertFalse(_live_installer_threads)
                dialog.deleteLater()
                self._app.processEvents()

    def test_temp_status_timer_is_safe_after_label_deletion(self):
        label = QLabel()
        show_temp_status(label, "temporary", 0)
        label.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self._app.processEvents()


if __name__ == "__main__":
    unittest.main()

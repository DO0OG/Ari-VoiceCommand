import io
import json
import os
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from agent.skill_installer import SkillInstaller
from ui.skills_dialog import SkillsDialog, _live_install_threads


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._payload


class SkillInstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_install_from_local_dir_copies_skill_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = os.path.join(temp_dir, "source-skill")
            target_dir = os.path.join(temp_dir, "skills")
            os.makedirs(source_dir, exist_ok=True)
            with open(os.path.join(source_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("로컬 스킬")

            installed = SkillInstaller(target_dir).install(source_dir)

            self.assertEqual(installed, ["source-skill"])
            self.assertTrue(os.path.exists(os.path.join(target_dir, "source-skill", "SKILL.md")))
            with open(
                os.path.join(target_dir, "source-skill", ".ari_skill_meta.json"),
                "r",
                encoding="utf-8",
            ) as handle:
                metadata = json.load(handle)
            self.assertEqual(metadata["source"], source_dir)
            self.assertTrue(metadata["enabled"])

    def test_install_from_github_tree_extracts_selected_subpath(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zip_handle:
            zip_handle.writestr("k-skill-main/coupang-product-search/SKILL.md", "쿠팡 스킬")
            zip_handle.writestr("k-skill-main/coupang-product-search/scripts/run.py", "print('ok')")
            zip_handle.writestr("k-skill-main/other-skill/SKILL.md", "기타 스킬")

        with tempfile.TemporaryDirectory() as temp_dir:
            installer = SkillInstaller(temp_dir)
            with mock.patch(
                "agent.skill_installer.urllib.request.urlopen",
                return_value=_FakeResponse(archive.getvalue()),
            ) as urlopen:
                installed = installer.install(
                    "NomaDamas/k-skill/tree/main/coupang-product-search"
                )

            self.assertEqual(installed, ["coupang-product-search"])
            self.assertEqual(urlopen.call_args.kwargs["timeout"], 30)
            self.assertTrue(
                os.path.exists(os.path.join(temp_dir, "coupang-product-search", "SKILL.md"))
            )
            self.assertFalse(
                os.path.exists(os.path.join(temp_dir, "other-skill", "SKILL.md"))
            )

    def test_update_accepts_skill_directory_and_preserves_disabled_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = os.path.join(temp_dir, "custom-folder")
            skills_dir = os.path.join(temp_dir, "skills")
            skill_dir = os.path.join(skills_dir, "custom-folder")
            os.makedirs(source_dir, exist_ok=True)
            os.makedirs(skill_dir, exist_ok=True)
            with open(os.path.join(source_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("updated skill")
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("old skill")
            with open(
                os.path.join(skill_dir, ".ari_skill_meta.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump({"enabled": False, "source": source_dir}, handle)

            self.assertTrue(SkillInstaller(skills_dir).update(skill_dir))

            with open(
                os.path.join(skill_dir, ".ari_skill_meta.json"), encoding="utf-8"
            ) as handle:
                metadata = json.load(handle)
            self.assertFalse(metadata["enabled"])
            with open(os.path.join(skill_dir, "SKILL.md"), encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "updated skill")

    def test_update_restores_existing_skill_when_install_result_omits_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skills_dir = os.path.join(temp_dir, "skills")
            skill_dir = os.path.join(skills_dir, "existing")
            os.makedirs(skill_dir)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("original content")
            with open(os.path.join(skill_dir, ".ari_skill_meta.json"), "w", encoding="utf-8") as handle:
                json.dump({"enabled": False, "source": "https://example.test/skill"}, handle)

            installer = SkillInstaller(skills_dir)
            with mock.patch.object(installer, "install", return_value=[]):
                with self.assertRaises(ValueError):
                    installer.update(skill_dir)

            with open(os.path.join(skill_dir, "SKILL.md"), encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "original content")
            with open(os.path.join(skill_dir, ".ari_skill_meta.json"), encoding="utf-8") as handle:
                self.assertFalse(json.load(handle)["enabled"])

    def test_failed_update_restores_every_other_skill_it_touched(self):
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as temp_dir:
                skills_dir = os.path.join(temp_dir, "skills")
                skill_dir = os.path.join(skills_dir, "existing")
                other_dir = os.path.join(skills_dir, "other")
                source_dir = os.path.join(temp_dir, "other")
                os.makedirs(skill_dir)
                os.makedirs(source_dir)
                with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                    handle.write("original target")
                with open(os.path.join(skill_dir, ".ari_skill_meta.json"), "w", encoding="utf-8") as handle:
                    json.dump({"enabled": False, "source": "source"}, handle)
                with open(os.path.join(source_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                    handle.write("new other")
                if existing:
                    os.makedirs(other_dir)
                    with open(os.path.join(other_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                        handle.write("original other")
                    with open(os.path.join(other_dir, ".ari_skill_meta.json"), "w", encoding="utf-8") as handle:
                        json.dump({"enabled": False, "source": "old source"}, handle)

                installer = SkillInstaller(skills_dir)

                def install_other(_source):
                    return installer._install_from_local_dir(source_dir, "source")

                with mock.patch.object(installer, "install", side_effect=install_other):
                    with self.assertRaises(ValueError):
                        installer.update(skill_dir)

                if existing:
                    with open(os.path.join(other_dir, "SKILL.md"), encoding="utf-8") as handle:
                        self.assertEqual(handle.read(), "original other")
                    with open(os.path.join(other_dir, ".ari_skill_meta.json"), encoding="utf-8") as handle:
                        self.assertFalse(json.load(handle)["enabled"])
                else:
                    self.assertFalse(os.path.exists(other_dir))

    def test_failed_update_keeps_backup_and_reports_path_when_restore_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skills_dir = os.path.join(temp_dir, "skills")
            skill_dir = os.path.join(skills_dir, "existing")
            other_dir = os.path.join(skills_dir, "other")
            source_dir = os.path.join(temp_dir, "other")
            os.makedirs(skill_dir)
            os.makedirs(other_dir)
            os.makedirs(source_dir)
            for directory, content in ((skill_dir, "target"), (other_dir, "original other"), (source_dir, "new other")):
                with open(os.path.join(directory, "SKILL.md"), "w", encoding="utf-8") as handle:
                    handle.write(content)
            with open(os.path.join(skill_dir, ".ari_skill_meta.json"), "w", encoding="utf-8") as handle:
                json.dump({"source": "source"}, handle)
            installer = SkillInstaller(skills_dir)
            replace = os.replace

            def fail_restore(source, destination):
                if os.path.basename(source).startswith(".ari-update-backup-"):
                    raise OSError("restore failed")
                replace(source, destination)

            with mock.patch.object(installer, "install", side_effect=lambda _source: installer._install_from_local_dir(source_dir, "source")), \
                    mock.patch("agent.skill_installer.os.replace", side_effect=fail_restore), \
                    mock.patch("agent.skill_installer._", side_effect=lambda key: "복구 실패 {path}" if key == "skills.update_restore_failed" else key):
                with self.assertRaisesRegex(RuntimeError, "\.ari-update-backup-") as raised:
                    installer.update(skill_dir)

            backup_path = next(
                os.path.join(skills_dir, name)
                for name in os.listdir(skills_dir)
                if name.startswith(".ari-update-backup-")
            )
            self.assertIn(backup_path, str(raised.exception))
            self.assertTrue(os.path.isfile(os.path.join(backup_path, "SKILL.md")))

    def test_update_dialog_runs_update_thread_with_skill_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = mock.Mock()
            manager.skills_dir = os.path.join(temp_dir, "skills")
            manager.load_all.return_value = []
            manager.get_skill.return_value = SimpleNamespace(
                skill_dir=os.path.join(manager.skills_dir, "actual-folder")
            )
            with mock.patch(
                "agent.skill_manager.get_skill_manager", return_value=manager
            ), mock.patch("ui.skills_dialog._SkillInstallThread.start") as start:
                dialog = SkillsDialog()
                dialog._selected_skill_name = lambda: "Display title"

                dialog._on_update()

                self.assertIsInstance(dialog._install_thread, QThread)
                self.assertEqual(
                    dialog._install_thread.skill_dir,
                    os.path.join(manager.skills_dir, "actual-folder"),
                )
                start.assert_called_once()
                dialog.close()

    def test_install_thread_is_released_when_finished(self):
        manager = mock.Mock()
        manager.skills_dir = "skills"
        manager.load_all.return_value = []
        with mock.patch("agent.skill_manager.get_skill_manager", return_value=manager), \
                mock.patch("ui.skills_dialog._SkillInstallThread.start"):
            dialog = SkillsDialog()
            dialog.source_input.setText("source")
            dialog._on_install()
            thread = dialog._install_thread

            self.assertIn(thread, _live_install_threads)
            thread.finished.emit()

            self.assertNotIn(thread, _live_install_threads)
            self.assertIsNone(dialog._install_thread)
            dialog.close()

    def test_closed_dialog_ignores_install_and_update_results(self):
        manager = mock.Mock()
        manager.load_all.return_value = []
        with mock.patch("agent.skill_manager.get_skill_manager", return_value=manager):
            dialog = SkillsDialog()
        dialog.close()
        progress = mock.Mock()
        dialog._refresh_list = mock.Mock()

        with mock.patch("ui.skills_dialog.QMessageBox.information") as information, \
                mock.patch("ui.skills_dialog.QMessageBox.warning") as warning:
            dialog._on_install_done(["skill"], progress)
            dialog._on_install_error("error", progress)
            dialog._on_update_done(True, "skill", progress)
            dialog._on_update_error("error", progress)

            progress.close.assert_not_called()
            information.assert_not_called()
            warning.assert_not_called()
            dialog._refresh_list.assert_not_called()


if __name__ == "__main__":
    unittest.main()

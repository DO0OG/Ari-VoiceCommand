import os
import tempfile
import unittest
from unittest.mock import patch

from core.resource_manager import ResourceManager


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class LegacyDataImportTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = self._temp.name
        self.app_data = os.path.join(self.root, "AppData", "Ari")
        self.old_zip = os.path.join(self.root, "Ari-old")
        self.runtime = os.path.join(self.old_zip, ".ari_runtime")
        _write(os.path.join(self.runtime, "ari_settings.json"), "old settings")
        _write(os.path.join(self.runtime, "ari_memory.db"), "old memory")
        _write(os.path.join(self.runtime, "skills", "a", "skill.json"), "old skill")
        _write(os.path.join(self.app_data, "ari_settings.json"), "new settings")
        _write(os.path.join(self.app_data, "skills", "b", "skill.json"), "new skill")
        self._env = patch.dict(os.environ, {"ARI_APP_DATA_DIR": self.app_data})
        self._env.start()
        ResourceManager.reset_cache()

    def tearDown(self):
        self._env.stop()
        ResourceManager.reset_cache()
        self._temp.cleanup()

    def test_copies_only_missing_files_from_parent_folder(self):
        copied = ResourceManager.import_legacy_runtime_data(self.old_zip)

        self.assertEqual(copied, 2)
        self.assertEqual(_read(os.path.join(self.app_data, "ari_settings.json")), "new settings")
        self.assertEqual(_read(os.path.join(self.app_data, "ari_memory.db")), "old memory")
        self.assertEqual(_read(os.path.join(self.app_data, "skills", "a", "skill.json")), "old skill")
        self.assertEqual(_read(os.path.join(self.app_data, "skills", "b", "skill.json")), "new skill")
        # 원본은 지우지 않는다.
        self.assertTrue(os.path.exists(os.path.join(self.runtime, "ari_memory.db")))

    def test_accepts_runtime_folder_itself_and_repeated_import_copies_nothing(self):
        self.assertEqual(ResourceManager.import_legacy_runtime_data(self.runtime), 2)
        self.assertEqual(ResourceManager.import_legacy_runtime_data(self.runtime), 0)

    def test_rejects_folder_without_ari_data(self):
        unrelated = os.path.join(self.root, "Documents")
        _write(os.path.join(unrelated, "notes.txt"), "x")

        with self.assertRaises(ValueError):
            ResourceManager.import_legacy_runtime_data(unrelated)
        self.assertFalse(os.path.exists(os.path.join(self.app_data, "notes.txt")))


if __name__ == "__main__":
    unittest.main()

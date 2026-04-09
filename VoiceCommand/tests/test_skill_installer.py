import io
import json
import os
import tempfile
import unittest
import zipfile
from unittest import mock


from agent.skill_installer import SkillInstaller


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
            ):
                installed = installer.install(
                    "NomaDamas/k-skill/tree/main/coupang-product-search"
                )

            self.assertEqual(installed, ["coupang-product-search"])
            self.assertTrue(
                os.path.exists(os.path.join(temp_dir, "coupang-product-search", "SKILL.md"))
            )
            self.assertFalse(
                os.path.exists(os.path.join(temp_dir, "other-skill", "SKILL.md"))
            )


if __name__ == "__main__":
    unittest.main()

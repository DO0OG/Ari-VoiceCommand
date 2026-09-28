import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.release_manifest import create_release_assets, validate_manifest


class ReleaseManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.installer = self.root / "Ari-Setup-1.2.3.exe"
        self.installer.write_bytes(b"installer payload")
        self.output = self.root / "output"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_stable_manifest_contains_canonical_urls_and_checksum(self):
        result = create_release_assets(
            self.installer, "1.2.3", "v1.2.3", "DO0OG/Ari-VoiceCommand", self.output
        )
        self.assertEqual(result, self.output / "update.json")
        manifest = json.loads(result.read_text(encoding="utf-8"))
        expected_hash = hashlib.sha256(self.installer.read_bytes()).hexdigest()
        expected_installer_url = (
            "https://github.com/DO0OG/Ari-VoiceCommand/releases/download/"
            "v1.2.3/Ari-Setup-1.2.3.exe"
        )
        expected_notes_url = "https://github.com/DO0OG/Ari-VoiceCommand/releases/tag/v1.2.3"
        self.assertEqual(manifest["schema"], 1)
        self.assertEqual(manifest["version"], "1.2.3")
        self.assertEqual(manifest["installer"]["name"], self.installer.name)
        self.assertEqual(manifest["installer"]["url"], expected_installer_url)
        self.assertEqual(manifest["notes_url"], expected_notes_url)
        self.assertEqual(manifest["installer"]["size"], len(self.installer.read_bytes()))
        self.assertEqual(manifest["installer"]["sha256"], expected_hash)
        self.assertEqual(manifest["min_updatable_from"], "1.0.0")
        self.assertTrue(manifest["released_at"].endswith("Z"))
        self.assertEqual(
            (self.output / "SHA256SUMS.txt").read_text(encoding="utf-8"),
            f"{expected_hash}  {self.installer.name}\n",
        )
        self.assertFalse((self.output / "update-beta.json").exists())

    def test_prerelease_writes_beta_manifest_only(self):
        beta_installer = self.root / "Ari-Setup-1.2.3-rc.1.exe"
        beta_installer.write_bytes(b"beta installer")
        result = create_release_assets(
            beta_installer,
            "1.2.3-rc.1",
            "v1.2.3-rc.1",
            "DO0OG/Ari-VoiceCommand",
            self.output,
        )
        manifest = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual(result.name, "update-beta.json")
        self.assertIn("/download/v1.2.3-rc.1/", manifest["installer"]["url"])
        self.assertFalse((self.output / "update.json").exists())

    def test_non_tag_build_creates_no_manifest(self):
        result = create_release_assets(
            self.installer, "0.0.0-dev", None, "DO0OG/Ari-VoiceCommand", self.output
        )
        self.assertIsNone(result)
        self.assertFalse(self.output.exists())

    def test_validation_rejects_version_tag_mismatch(self):
        with self.assertRaisesRegex(ValueError, "tag"):
            create_release_assets(
                self.installer, "1.2.3", "v1.2.4", "DO0OG/Ari-VoiceCommand", self.output
            )

    def test_generation_rejects_installer_name_version_mismatch(self):
        wrong_name = self.root / "Ari-Setup-9.9.9.exe"
        wrong_name.write_bytes(b"installer payload")
        with self.assertRaisesRegex(ValueError, "filename"):
            create_release_assets(
                wrong_name, "1.2.3", "v1.2.3", "DO0OG/Ari-VoiceCommand", self.output
            )

    def test_validation_rejects_hash_size_and_url_host_mismatches(self):
        manifest_path = create_release_assets(
            self.installer, "1.2.3", "v1.2.3", "DO0OG/Ari-VoiceCommand", self.output
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        invalid_manifests = []
        wrong_hash = json.loads(json.dumps(manifest))
        wrong_hash["installer"]["sha256"] = "0" * 64
        invalid_manifests.append(wrong_hash)
        wrong_size = json.loads(json.dumps(manifest))
        wrong_size["installer"]["size"] += 1
        invalid_manifests.append(wrong_size)
        wrong_host = json.loads(json.dumps(manifest))
        wrong_host["installer"]["url"] = wrong_host["installer"]["url"].replace(
            "https://github.com", "https://example.com"
        )
        invalid_manifests.append(wrong_host)
        wrong_scheme = json.loads(json.dumps(manifest))
        wrong_scheme["notes_url"] = wrong_scheme["notes_url"].replace("https://", "http://")
        invalid_manifests.append(wrong_scheme)
        for candidate in invalid_manifests:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    validate_manifest(candidate, self.installer, "v1.2.3", "DO0OG/Ari-VoiceCommand")

    def test_validation_rejects_missing_fields_and_invalid_sha_format(self):
        manifest_path = create_release_assets(
            self.installer, "1.2.3", "v1.2.3", "DO0OG/Ari-VoiceCommand", self.output
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        del manifest["min_updatable_from"]
        with self.assertRaisesRegex(ValueError, "min_updatable_from"):
            validate_manifest(manifest, self.installer, "v1.2.3", "DO0OG/Ari-VoiceCommand")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["installer"]["sha256"] = "not-a-hash"
        with self.assertRaisesRegex(ValueError, "sha256"):
            validate_manifest(manifest, self.installer, "v1.2.3", "DO0OG/Ari-VoiceCommand")


if __name__ == "__main__":
    unittest.main()

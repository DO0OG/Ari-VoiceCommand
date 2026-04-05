import os
import sys
import unittest
import io
import tempfile
import zipfile
import hashlib
import json
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import marketplace_client


class MarketplaceClientTests(unittest.TestCase):
    def _build_archive_bytes(self, plugin_name: str = "sample_plugin", entry: str = "main.py") -> bytes:
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as archive:
            archive.writestr("plugin.json", json.dumps({"name": plugin_name, "entry": entry}, ensure_ascii=False))
            archive.writestr(entry, "PLUGIN_INFO = {}\n\ndef register(context):\n    return {}\n")
        return archive_buffer.getvalue()

    def test_require_web_url_accepts_http_and_https(self):
        self.assertEqual(
            marketplace_client._require_web_url("https://example.com/plugin.zip"),
            "https://example.com/plugin.zip",
        )
        self.assertEqual(
            marketplace_client._require_web_url("http://localhost:8000/plugin.zip"),
            "http://localhost:8000/plugin.zip",
        )

    def test_require_web_url_rejects_file_scheme(self):
        with self.assertRaises(ValueError):
            marketplace_client._require_web_url("file:///tmp/plugin.zip")

    def test_install_plugin_rejects_non_web_release_url(self):
        with mock.patch.object(
            marketplace_client,
            "_post",
            return_value={
                "release_url": "file:///tmp/plugin.zip",
                "name": "sample_plugin",
                "entry": "main.py",
                "sha256": "0" * 64,
            },
        ):
            self.assertFalse(marketplace_client.install_plugin("plugin-123", plugin_dir="C:\\temp\\ari-test"))

    def test_install_plugin_saves_zip_plugin_package(self):
        archive_bytes = self._build_archive_bytes()

        class _FakeResponse:
            def __init__(self, payload: bytes):
                self._payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._payload

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(
                marketplace_client,
                "_post",
                return_value={
                    "release_url": "https://example.com/plugin.zip",
                    "name": "sample_plugin",
                    "entry": "main.py",
                    "sha256": hashlib.sha256(archive_bytes).hexdigest(),
                },
            ):
                with mock.patch("core.marketplace_client.urllib.request.urlopen", return_value=_FakeResponse(archive_bytes)):
                    with mock.patch("core.marketplace_client.get_plugin_manager", side_effect=Exception("unused"), create=True):
                        self.assertTrue(marketplace_client.install_plugin("plugin-123", plugin_dir=temp_dir))

            self.assertTrue(os.path.exists(os.path.join(temp_dir, "sample_plugin.zip")))
            self.assertFalse(os.path.exists(os.path.join(temp_dir, "main.py")))

    def test_install_plugin_falls_back_to_fetch_plugin_when_install_response_is_old(self):
        archive_bytes = self._build_archive_bytes()

        class _FakeResponse:
            def __init__(self, payload: bytes):
                self._payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._payload

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(
                marketplace_client,
                "_post",
                return_value={"release_url": "https://example.com/plugin.zip"},
            ):
                with mock.patch.object(
                    marketplace_client,
                    "fetch_plugin",
                    return_value={
                        "name": "sample_plugin",
                        "entry": "main.py",
                        "sha256": hashlib.sha256(archive_bytes).hexdigest(),
                    },
                ):
                    with mock.patch("core.marketplace_client.urllib.request.urlopen", return_value=_FakeResponse(archive_bytes)):
                        self.assertTrue(marketplace_client.install_plugin("plugin-123", plugin_dir=temp_dir))

            self.assertTrue(os.path.exists(os.path.join(temp_dir, "sample_plugin.zip")))

    def test_install_plugin_rejects_checksum_mismatch(self):
        archive_bytes = self._build_archive_bytes()

        class _FakeResponse:
            def __init__(self, payload: bytes):
                self._payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._payload

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(
                marketplace_client,
                "_post",
                return_value={
                    "release_url": "https://example.com/plugin.zip",
                    "name": "sample_plugin",
                    "entry": "main.py",
                    "sha256": "0" * 64,
                },
            ):
                with mock.patch("core.marketplace_client.urllib.request.urlopen", return_value=_FakeResponse(archive_bytes)):
                    self.assertFalse(marketplace_client.install_plugin("plugin-123", plugin_dir=temp_dir))

    def test_install_plugin_rejects_missing_checksum(self):
        archive_bytes = self._build_archive_bytes()

        class _FakeResponse:
            def __init__(self, payload: bytes):
                self._payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._payload

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(
                marketplace_client,
                "_post",
                return_value={
                    "release_url": "https://example.com/plugin.zip",
                    "name": "sample_plugin",
                    "entry": "main.py",
                },
            ):
                with mock.patch.object(marketplace_client, "fetch_plugin", return_value={"name": "sample_plugin", "entry": "main.py"}):
                    with mock.patch("core.marketplace_client.urllib.request.urlopen", return_value=_FakeResponse(archive_bytes)):
                        self.assertFalse(marketplace_client.install_plugin("plugin-123", plugin_dir=temp_dir))

    def test_marketplace_contract_files_expose_sha256_end_to_end(self):
        repo_root = os.path.dirname(ROOT)
        install_fn = os.path.join(repo_root, "market", "supabase", "functions", "install-plugin", "index.ts")
        get_fn = os.path.join(repo_root, "market", "supabase", "functions", "get-plugin", "index.ts")
        upload_fn = os.path.join(repo_root, "market", "supabase", "functions", "upload-plugin", "index.ts")
        status_fn = os.path.join(repo_root, "market", "supabase", "functions", "plugin-status", "index.ts")
        finalize_script = os.path.join(repo_root, "market", "marketplace", "scripts", "finalize.py")
        migration = os.path.join(repo_root, "market", "supabase", "migrations", "002_add_plugin_sha256.sql")
        install_sync_migration = os.path.join(repo_root, "market", "supabase", "migrations", "003_record_plugin_install.sql")
        integration_client = os.path.join(repo_root, "market", "ari_integration", "core", "marketplace_client.py")
        web_types = os.path.join(repo_root, "market", "web", "src", "lib", "types.ts")

        with open(install_fn, "r", encoding="utf-8") as handle:
            install_text = handle.read()
        with open(get_fn, "r", encoding="utf-8") as handle:
            get_text = handle.read()
        with open(upload_fn, "r", encoding="utf-8") as handle:
            upload_text = handle.read()
        with open(status_fn, "r", encoding="utf-8") as handle:
            status_text = handle.read()
        with open(finalize_script, "r", encoding="utf-8") as handle:
            finalize_text = handle.read()
        with open(migration, "r", encoding="utf-8") as handle:
            migration_text = handle.read()
        with open(install_sync_migration, "r", encoding="utf-8") as handle:
            install_sync_text = handle.read()
        with open(integration_client, "r", encoding="utf-8") as handle:
            integration_text = handle.read()
        with open(web_types, "r", encoding="utf-8") as handle:
            web_types_text = handle.read()

        self.assertIn("sha256", install_text)
        self.assertIn("record_plugin_install", install_text)
        self.assertIn("sha256", get_text)
        self.assertIn("sha256", upload_text)
        self.assertIn("plugin zip must be 5MB or smaller", upload_text)
        self.assertIn("review_report", status_text)
        self.assertIn("sha256", finalize_text)
        self.assertIn("sha256", migration_text)
        self.assertIn("record_plugin_install", install_sync_text)
        self.assertIn("sha256", integration_text)
        self.assertIn("sha256?: string", web_types_text)


if __name__ == "__main__":
    unittest.main()

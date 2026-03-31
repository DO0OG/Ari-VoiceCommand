import os
import sys
import unittest
import io
import tempfile
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import marketplace_client


class MarketplaceClientTests(unittest.TestCase):
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
            return_value={"release_url": "file:///tmp/plugin.zip", "name": "sample_plugin", "entry": "main.py"},
        ):
            self.assertFalse(marketplace_client.install_plugin("plugin-123", plugin_dir="C:\\temp\\ari-test"))

    def test_install_plugin_saves_zip_plugin_package(self):
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as archive:
            archive.writestr("plugin.json", '{"name":"sample_plugin","entry":"main.py"}')
            archive.writestr("main.py", "PLUGIN_INFO = {}\n\ndef register(context):\n    return {}\n")

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
                with mock.patch("core.marketplace_client.urllib.request.urlopen", return_value=_FakeResponse(archive_buffer.getvalue())):
                    with mock.patch("core.marketplace_client.get_plugin_manager", side_effect=Exception("unused"), create=True):
                        self.assertTrue(marketplace_client.install_plugin("plugin-123", plugin_dir=temp_dir))

            self.assertTrue(os.path.exists(os.path.join(temp_dir, "sample_plugin.zip")))
            self.assertFalse(os.path.exists(os.path.join(temp_dir, "main.py")))

    def test_install_plugin_falls_back_to_fetch_plugin_when_install_response_is_old(self):
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as archive:
            archive.writestr("plugin.json", '{"name":"sample_plugin","entry":"main.py"}')
            archive.writestr("main.py", "PLUGIN_INFO = {}\n\ndef register(context):\n    return {}\n")

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
                    return_value={"name": "sample_plugin", "entry": "main.py"},
                ):
                    with mock.patch("core.marketplace_client.urllib.request.urlopen", return_value=_FakeResponse(archive_buffer.getvalue())):
                        self.assertTrue(marketplace_client.install_plugin("plugin-123", plugin_dir=temp_dir))

            self.assertTrue(os.path.exists(os.path.join(temp_dir, "sample_plugin.zip")))


if __name__ == "__main__":
    unittest.main()

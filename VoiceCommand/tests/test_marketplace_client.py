import os
import sys
import unittest
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
            return_value={"release_url": "file:///tmp/plugin.zip"},
        ):
            self.assertFalse(marketplace_client.install_plugin("plugin-123", plugin_dir="C:\\temp\\ari-test"))


if __name__ == "__main__":
    unittest.main()

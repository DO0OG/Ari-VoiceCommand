import json
import os
import tempfile
import unittest
from unittest.mock import patch

from core.app_version import (
    DEV_VERSION,
    compare_versions,
    dispatch_version_command,
    get_build_info,
    get_version,
    get_windows_version,
    is_release_build,
    record_last_run_version,
)
from core.resource_manager import ResourceManager


class AppVersionTests(unittest.TestCase):
    def test_missing_build_info_uses_development_version(self):
        with patch.object(ResourceManager, "get_bundle_path", return_value="missing.json"):
            self.assertEqual(get_version(), DEV_VERSION)
            self.assertFalse(is_release_build())

    def test_build_info_exposes_release_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "build_info.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "version": "1.2.3-rc.1",
                        "commit": "0123456789abcdef",
                        "built_at": "2026-09-29T00:00:00Z",
                        "channel": "beta",
                    },
                    handle,
                )
            with patch.object(ResourceManager, "get_bundle_path", return_value=path):
                self.assertEqual(get_version(), "1.2.3-rc.1")
                self.assertEqual(get_build_info()["commit"], "0123456789abcdef")
                self.assertTrue(is_release_build())

    def test_version_command_prints_only_version(self):
        with patch("core.app_version.get_version", return_value="1.2.3"):
            with patch("builtins.print") as output:
                self.assertEqual(dispatch_version_command(["Ari.exe", "--version"]), 0)
                output.assert_called_once_with("1.2.3")
                self.assertIsNone(dispatch_version_command(["Ari.exe"]))

    def test_compare_versions_orders_core_and_prerelease_parts(self):
        self.assertEqual(compare_versions("1.2.4", "1.2.3"), 1)
        self.assertEqual(compare_versions("1.2.3-rc.2", "1.2.3-rc.10"), -1)
        self.assertEqual(compare_versions("1.2.3-rc.1", "1.2.3-rc"), 1)
        self.assertEqual(compare_versions("1.2.3-rc.1", "1.2.3"), -1)
        with self.assertRaises(ValueError):
            compare_versions("1.2", "1.2.3")

    def test_windows_version_is_four_numeric_components(self):
        self.assertEqual(get_windows_version("1.2.3-rc.1"), "1.2.3.0")
        self.assertIsNone(get_windows_version("1.2"))

    def test_record_last_run_version_preserves_runtime_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "runtime_state.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"other_state": True}, handle)
            with (
                patch.object(ResourceManager, "get_runtime_path", return_value=path),
                patch("core.app_version.get_version", return_value="1.2.3"),
            ):
                self.assertTrue(record_last_run_version())
            with open(path, encoding="utf-8") as handle:
                state = json.load(handle)
            self.assertEqual(state["last_run_version"], "1.2.3")
            self.assertTrue(state["other_state"])

    def test_startup_version_change_is_reported_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "runtime_state.json")
            with (
                patch.object(ResourceManager, "get_runtime_path", return_value=path),
                patch("core.app_version.get_version", return_value="1.2.4"),
                patch("core.app_version.is_release_build", return_value=True),
            ):
                self.assertTrue(record_last_run_version())
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump({"last_run_version": "1.2.3"}, handle)
                self.assertTrue(record_last_run_version())
                with open(path, encoding="utf-8") as handle:
                    self.assertEqual(json.load(handle)["installed_update_pending"], "1.2.4")
                self.assertTrue(record_last_run_version())
                with open(path, encoding="utf-8") as handle:
                    self.assertEqual(json.load(handle)["installed_update_pending"], "1.2.4")

    def test_runtime_path_error_skips_last_run_write(self):
        with patch.object(
            ResourceManager,
            "get_runtime_path",
            side_effect=PermissionError("runtime directory is read-only"),
        ):
            self.assertFalse(record_last_run_version())


if __name__ == "__main__":
    unittest.main()

import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from core import update_checker
from core.resource_manager import ResourceManager


def _manifest(version="1.1.0", minimum="1.0.0"):
    installer_name = f"Ari-Setup-{version}.exe"
    base = "https://github.com/DO0OG/Ari-VoiceCommand/releases"
    return {
        "schema": 1,
        "version": version,
        "released_at": "2026-09-29T00:00:00Z",
        "installer": {
            "name": installer_name,
            "url": f"{base}/download/v{version}/{installer_name}",
            "size": 123,
            "sha256": "a" * 64,
        },
        "min_updatable_from": minimum,
        "notes_url": f"{base}/tag/v{version}",
    }


def _read_state(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class _FakeSocket:
    def settimeout(self, _timeout):
        pass


class _FakeResponse:
    def __init__(self, status, headers=None, body=b""):
        self.status = status
        self._headers = headers or {}
        self._body = body
        self._offset = 0

    def getheaders(self):
        return list(self._headers.items())

    def getheader(self, name):
        return self._headers.get(name)

    def read(self, size):
        chunk = self._body[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk


class _FakeConnection:
    def __init__(self, response):
        self.sock = _FakeSocket()
        self.response = response
        self.request_headers = None

    def connect(self):
        pass

    def request(self, _method, _path, headers):
        self.request_headers = headers

    def getresponse(self):
        return self.response

    def close(self):
        pass


class UpdateCheckerTests(unittest.TestCase):
    def test_manifest_rejects_missing_fields(self):
        paths = (
            ("schema",),
            ("version",),
            ("released_at",),
            ("installer",),
            ("installer", "name"),
            ("installer", "url"),
            ("installer", "size"),
            ("installer", "sha256"),
            ("min_updatable_from",),
            ("notes_url",),
        )
        for keys in paths:
            with self.subTest(field=".".join(keys)):
                manifest = _manifest()
                parent = manifest
                for key in keys[:-1]:
                    parent = parent[key]
                del parent[keys[-1]]
                with self.assertRaises(ValueError):
                    update_checker.validate_manifest(manifest)

    def test_manifest_rejects_invalid_fields_and_hosts(self):
        update_checker.validate_manifest(_manifest())
        cases = (
            ("schema", 2),
            ("installer.name", "../Ari-Setup-1.1.0.exe"),
            ("installer.sha256", "g" * 64),
            ("installer.url", "https://example.com/setup.exe"),
            ("notes_url", "http://github.com/DO0OG/Ari-VoiceCommand/releases/tag/v1.1.0"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                manifest = _manifest()
                if "." in field:
                    parent, key = field.split(".")
                    manifest[parent][key] = value
                else:
                    manifest[field] = value
                with self.assertRaises(ValueError):
                    update_checker.validate_manifest(manifest)

    def test_manifest_urls_follow_stable_release_format(self):
        manifest = _manifest("1.2.0-rc.1")
        update_checker.validate_manifest(manifest)
        self.assertIn(
            "releases/latest/download/update.json",
            update_checker._manifest_url("stable"),
        )
        self.assertIn(
            "releases/download/beta-channel/update-beta.json",
            update_checker._manifest_url("beta"),
        )

    def test_request_allows_github_asset_redirect_but_rejects_other_hosts(self):
        redirected = _FakeConnection(
            _FakeResponse(
                302,
                {"Location": "https://release-assets.githubusercontent.com/manifest"},
            )
        )
        asset = _FakeConnection(_FakeResponse(200, {"ETag": "abc"}, b"{}"))
        with patch(
            "core.update_checker.http.client.HTTPSConnection",
            side_effect=[redirected, asset],
        ):
            status, headers, body = update_checker._request_manifest(
                update_checker._manifest_url("stable"), {"User-Agent": "Ari/1.0.0 (Windows)"}
            )
        self.assertEqual(status, 200)
        self.assertEqual(headers["etag"], "abc")
        self.assertEqual(body, b"{}")

        untrusted = _FakeConnection(
            _FakeResponse(302, {"Location": "https://example.com/manifest"})
        )
        with patch("core.update_checker.http.client.HTTPSConnection", return_value=untrusted):
            with self.assertRaises(ValueError):
                update_checker._request_manifest(
                    update_checker._manifest_url("stable"), {}
                )

    def test_request_rejects_manifest_over_size_limit(self):
        connection = _FakeConnection(
            _FakeResponse(200, body=b"x" * (update_checker._MAX_MANIFEST_BYTES + 1))
        )
        with patch("core.update_checker.http.client.HTTPSConnection", return_value=connection):
            with self.assertRaises(ValueError):
                update_checker._request_manifest(update_checker._manifest_url("stable"), {})

    def test_request_rejects_rate_limit_and_missing_asset(self):
        for status in (403, 404):
            with self.subTest(status=status):
                connection = _FakeConnection(_FakeResponse(status))
                with patch(
                    "core.update_checker.http.client.HTTPSConnection",
                    return_value=connection,
                ):
                    with self.assertRaises(OSError):
                        update_checker._request_manifest(
                            update_checker._manifest_url("stable"), {}
                        )

    def test_success_persists_pending_version_and_conditional_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "runtime_state.json")
            body = json.dumps(_manifest()).encode("utf-8")
            with (
                patch.object(ResourceManager, "get_runtime_path", return_value=path),
                patch.object(update_checker.ConfigManager, "get", return_value="stable"),
                patch("core.update_checker.get_version", return_value="1.0.0"),
                patch(
                    "core.update_checker._request_manifest",
                    return_value=(
                        200,
                        {"etag": "manifest-tag", "last-modified": "Mon, 28 Sep 2026 00:00:00 GMT"},
                        body,
                    ),
                ) as request,
            ):
                status, failures = update_checker._check_for_updates()
            state = _read_state(path)
            self.assertEqual((status, failures), (200, 0))
            self.assertEqual(state["pending_version"], "1.1.0")
            self.assertEqual(state["etag"], "manifest-tag")
            self.assertEqual(state["last_modified"], "Mon, 28 Sep 2026 00:00:00 GMT")
            request.assert_called_once()

    def test_304_preserves_pending_update_and_uses_saved_etag(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "runtime_state.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "etag": "old-tag",
                        "last_modified": "Mon, 28 Sep 2026 00:00:00 GMT",
                        "last_checked_channel": "stable",
                        "pending_version": "1.1.0",
                    },
                    handle,
                )
            with (
                patch.object(ResourceManager, "get_runtime_path", return_value=path),
                patch.object(update_checker.ConfigManager, "get", return_value="stable"),
                patch("core.update_checker.get_version", return_value="1.0.0"),
                patch(
                    "core.update_checker._request_manifest",
                    return_value=(304, {"etag": "old-tag"}, b""),
                ) as request,
            ):
                status, failures = update_checker._check_for_updates()
            headers = request.call_args.args[1]
            self.assertEqual(headers["If-None-Match"], "old-tag")
            self.assertEqual(
                headers["If-Modified-Since"], "Mon, 28 Sep 2026 00:00:00 GMT"
            )
            self.assertEqual((status, failures), (304, 0))
            self.assertEqual(_read_state(path)["pending_version"], "1.1.0")

    def test_failure_is_quietly_recorded_with_backoff(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "runtime_state.json")
            with (
                patch.object(ResourceManager, "get_runtime_path", return_value=path),
                patch.object(update_checker.ConfigManager, "get", return_value="stable"),
                patch("core.update_checker.get_version", return_value="1.0.0"),
                patch(
                    "core.update_checker._request_manifest",
                    side_effect=TimeoutError("timed out"),
                ),
                patch("core.update_checker.logging.debug") as log_debug,
            ):
                status, failures = update_checker._check_for_updates()
            self.assertEqual((status, failures), (0, 1))
            self.assertEqual(_read_state(path)["update_check_failures"], 1)
            self.assertEqual(
                update_checker._next_check_delay(failures),
                update_checker._CHECK_INTERVAL_SECONDS * 2,
            )
            log_debug.assert_called_once()

    def test_skipped_version_is_not_kept_as_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "runtime_state.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"skipped_version": "1.1.0"}, handle)
            with (
                patch.object(ResourceManager, "get_runtime_path", return_value=path),
                patch.object(update_checker.ConfigManager, "get", return_value="stable"),
                patch("core.update_checker.get_version", return_value="1.0.0"),
                patch(
                    "core.update_checker._request_manifest",
                    return_value=(200, {}, json.dumps(_manifest()).encode("utf-8")),
                ),
            ):
                update_checker._check_for_updates()
            self.assertEqual(_read_state(path)["pending_version"], "")

    def test_network_result_cannot_restore_a_skipped_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "runtime_state.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"skipped_version": "1.1.0"}, handle)
            with patch.object(ResourceManager, "get_runtime_path", return_value=path):
                update_checker._write_runtime_state(
                    {
                        "pending_version": "1.1.0",
                        "pending_notes_url": _manifest()["notes_url"],
                        "pending_min_updatable_from": "1.0.0",
                    }
                )
            state = _read_state(path)
            self.assertEqual(state["pending_version"], "")
            self.assertEqual(state["skipped_version"], "1.1.0")

    def test_notice_is_tray_once_and_bubble_once_per_day(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "runtime_state.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "pending_version": "1.1.0",
                        "pending_notes_url": _manifest()["notes_url"],
                        "pending_min_updatable_from": "1.0.0",
                    },
                    handle,
                )
            tray = Mock()
            character = Mock()
            checker = update_checker.UpdateChecker(tray, character)
            with (
                patch.object(ResourceManager, "get_runtime_path", return_value=path),
                patch("core.update_checker.get_version", return_value="0.9.0"),
            ):
                checker._notify_pending()
                checker._notify_pending()
            checker.stop()
            tray.showMessage.assert_called_once()
            self.assertEqual(tray.showMessage.call_args.args[1], "Ari 1.1.0은 직접 설치해야 합니다.")
            character.say.assert_called_once()

    def test_installed_update_notice_is_consumed_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "runtime_state.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"installed_update_pending": "1.1.0"}, handle)
            tray = Mock()
            character = Mock()
            checker = update_checker.UpdateChecker(tray, character)
            with (
                patch.object(ResourceManager, "get_runtime_path", return_value=path),
                patch("core.update_checker.get_version", return_value="1.1.0"),
            ):
                checker.notify_installed_update()
                checker.notify_installed_update()
            checker.stop()
            tray.showMessage.assert_called_once()
            self.assertIn("빠른 로컬 명령 처리를 사용할 수 있습니다.",
                          tray.showMessage.call_args.args[1])
            character.say.assert_called_once()
            self.assertEqual(_read_state(path)["installed_update_pending"], "")

    def test_source_build_does_not_start_a_check(self):
        checker = update_checker.UpdateChecker()
        with patch("core.update_checker.is_release_build", return_value=False):
            checker.start()
            checker.check_now()
        self.assertFalse(checker._check_timer.isActive())
        self.assertFalse(checker._checking)
        checker.stop()

    def test_disabled_setting_does_not_schedule_automatic_check(self):
        checker = update_checker.UpdateChecker()
        with (
            patch("core.update_checker.is_release_build", return_value=True),
            patch.object(update_checker.ConfigManager, "get", return_value=False),
        ):
            checker.start()
        self.assertFalse(checker._check_timer.isActive())
        checker.stop()


if __name__ == "__main__":
    unittest.main()

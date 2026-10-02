"""릴리스 업데이트 확인과 알림을 담당한다."""

from datetime import datetime, timezone
import http.client
import json
import logging
import random
import re
import ssl
import threading
import time
from urllib.parse import urljoin, urlsplit

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QSystemTrayIcon

from core.app_version import compare_versions, get_version, is_release_build
from core.atomic_io import write_json_atomic
from core.config_manager import ConfigManager
from core.resource_manager import ResourceManager
from i18n.translator import _


_STABLE_MANIFEST_URL = (
    "https://github.com/DO0OG/Ari-VoiceCommand/releases/latest/download/update.json"
)
_BETA_MANIFEST_URL = (
    "https://github.com/DO0OG/Ari-VoiceCommand/releases/download/beta-channel/update-beta.json"
)
_GITHUB_HOST = "github.com"
# 릴리스 자산 다운로드는 GitHub가 자산 전용 호스트로 리디렉트한다(예전 호스트 포함).
_REDIRECT_HOSTS = frozenset({
    _GITHUB_HOST,
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
})
_MAX_MANIFEST_BYTES = 64 * 1024
_CONNECT_TIMEOUT_SECONDS = 5
_TOTAL_TIMEOUT_SECONDS = 10
_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
_RNG = random.SystemRandom()
_RUNTIME_STATE_LOCK = threading.RLock()
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
_UTC_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _manifest_url(channel: str) -> str:
    if channel == "beta":
        return _BETA_MANIFEST_URL
    return _STABLE_MANIFEST_URL


def _automatic_checks_enabled() -> bool:
    value = ConfigManager.get("update_check_enabled", True)
    return value if isinstance(value, bool) else True


def _validate_github_url(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("manifest URL is missing")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != _GITHUB_HOST
        or parsed.hostname != _GITHUB_HOST
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("manifest URLs must use HTTPS on github.com")
    return value


def validate_manifest(manifest: object) -> dict:
    """U2 manifest의 U3에서 쓰는 필드를 검증한다."""
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    schema = manifest.get("schema")
    if not isinstance(schema, int) or isinstance(schema, bool) or schema != 1:
        raise ValueError("unsupported manifest schema")

    version = manifest.get("version")
    minimum = manifest.get("min_updatable_from")
    if (
        not isinstance(version, str)
        or _VERSION_PATTERN.fullmatch(version) is None
        or not isinstance(minimum, str)
        or _VERSION_PATTERN.fullmatch(minimum) is None
    ):
        raise ValueError("manifest version is invalid")

    released_at = manifest.get("released_at")
    if (
        not isinstance(released_at, str)
        or _UTC_TIMESTAMP_PATTERN.fullmatch(released_at) is None
    ):
        raise ValueError("manifest release time is invalid")
    try:
        datetime.strptime(released_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ValueError("manifest release time is invalid") from error

    installer = manifest.get("installer")
    if not isinstance(installer, dict):
        raise ValueError("manifest installer is missing")
    expected_name = f"Ari-Setup-{version}.exe"
    if installer.get("name") != expected_name:
        raise ValueError("manifest installer name is invalid")
    size = installer.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ValueError("manifest installer size is invalid")
    digest = installer.get("sha256")
    if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
        raise ValueError("manifest installer hash is invalid")

    expected_base = "https://github.com/DO0OG/Ari-VoiceCommand/releases"
    installer_url = _validate_github_url(installer.get("url"))
    notes_url = _validate_github_url(manifest.get("notes_url"))
    if installer_url != f"{expected_base}/download/v{version}/{expected_name}":
        raise ValueError("manifest installer URL is invalid")
    if notes_url != f"{expected_base}/tag/v{version}":
        raise ValueError("manifest notes URL is invalid")

    return manifest


def _read_runtime_state() -> tuple[str, dict]:
    path = ResourceManager.get_runtime_path("runtime_state.json")
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        state = {}
    if not isinstance(state, dict):
        raise ValueError("runtime state must be an object")
    return path, state


def _write_runtime_state(updates: dict) -> dict:
    with _RUNTIME_STATE_LOCK:
        path, state = _read_runtime_state()
        changes = dict(updates)
        pending_version = changes.get("pending_version")
        if pending_version and state.get("skipped_version") == pending_version:
            changes.update(
                {
                    "pending_version": "",
                    "pending_notes_url": "",
                    "pending_min_updatable_from": "",
                }
            )
        state.update(changes)
        write_json_atomic(path, state, ensure_ascii=False, indent=2)
    return state


def get_update_status() -> dict:
    """설정 화면에 표시할 업데이트 상태를 반환한다."""
    try:
        state = _read_runtime_state()[1]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        logging.debug("업데이트 상태를 읽지 못했습니다: %s", error)
        return {}
    status = {
        key: state.get(key)
        for key in (
            "pending_version",
            "pending_notes_url",
            "pending_min_updatable_from",
            "skipped_version",
            "last_checked_at",
            "notified_update_version",
            "last_update_bubble_date",
            "installed_update_pending",
        )
    }
    if not isinstance(status["pending_version"], str) or not _VERSION_PATTERN.fullmatch(
        status["pending_version"]
    ):
        status["pending_version"] = ""
    for key in ("pending_min_updatable_from",):
        value = status[key]
        if not isinstance(value, str) or not _VERSION_PATTERN.fullmatch(value):
            status[key] = ""
    try:
        status["pending_notes_url"] = _validate_github_url(status["pending_notes_url"])
    except ValueError:
        status["pending_notes_url"] = ""
    return status


def _request_manifest(url: str, headers: dict[str, str]) -> tuple[int, dict, bytes]:
    deadline = time.monotonic() + _TOTAL_TIMEOUT_SECONDS
    current_url = url
    for _redirect in range(5):
        parsed = urlsplit(current_url)
        allowed_hosts = _REDIRECT_HOSTS if _redirect else {_GITHUB_HOST}
        if (
            parsed.scheme != "https"
            or parsed.hostname not in allowed_hosts
            or parsed.netloc != parsed.hostname
        ):
            raise ValueError("update redirect host is not allowed")

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("update check timed out")
        connection = http.client.HTTPSConnection(
            parsed.hostname,
            timeout=min(_CONNECT_TIMEOUT_SECONDS, remaining),
            context=ssl.create_default_context(),
        )
        try:
            connection.connect()
            if connection.sock is None:
                raise OSError("update connection was closed")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("update check timed out")
            connection.sock.settimeout(remaining)
            path = parsed.path or "/"
            if parsed.query:
                path += f"?{parsed.query}"
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            response_headers = {key.lower(): value for key, value in response.getheaders()}

            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise ValueError("update redirect has no location")
                current_url = urljoin(current_url, location)
                redirected = urlsplit(current_url)
                if (
                    redirected.scheme != "https"
                    or redirected.hostname not in _REDIRECT_HOSTS
                    or redirected.netloc != redirected.hostname
                ):
                    raise ValueError("update redirect host is not allowed")
                continue
            if response.status not in {200, 304}:
                raise OSError(f"update server returned HTTP {response.status}")
            if response.status == 304:
                return 304, response_headers, b""

            body = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("update check timed out")
                connection.sock.settimeout(remaining)
                chunk = response.read(min(8192, _MAX_MANIFEST_BYTES + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > _MAX_MANIFEST_BYTES:
                    raise ValueError("update manifest exceeds the size limit")
            return 200, response_headers, bytes(body)
        finally:
            connection.close()
    raise ValueError("too many update redirects")


def _load_manifest(url: str, headers: dict[str, str]) -> tuple[int, dict, dict | None]:
    status, response_headers, body = _request_manifest(url, headers)
    manifest = None
    if status == 200:
        manifest = validate_manifest(json.loads(body.decode("utf-8")))
    return status, response_headers, manifest


def _record_failure() -> int:
    try:
        state = _read_runtime_state()[1]
        previous = state.get("update_check_failures", 0)
        failures = (
            previous + 1
            if isinstance(previous, int) and not isinstance(previous, bool) and previous >= 0
            else 1
        )
        _write_runtime_state(
            {
                "update_check_failures": failures,
                "last_check_attempt_at": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
        )
        return failures
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        logging.debug("업데이트 확인 실패 상태를 저장하지 못했습니다: %s", error)
        return 1


def _check_for_updates() -> tuple[int, int]:
    try:
        state = _read_runtime_state()[1]
        headers = {
            "User-Agent": f"Ari/{get_version()} (Windows)",
            "Accept": "application/json",
        }
        channel_setting = ConfigManager.get("update_channel", "stable")
        channel = "beta" if channel_setting == "beta" else "stable"
        same_channel = state.get("last_checked_channel") == channel
        if same_channel and isinstance(state.get("etag"), str) and state["etag"]:
            headers["If-None-Match"] = state["etag"]
        if (
            same_channel
            and isinstance(state.get("last_modified"), str)
            and state["last_modified"]
        ):
            headers["If-Modified-Since"] = state["last_modified"]

        manifests = []
        status = 0
        cache_result = None
        if channel == "beta":
            beta_result = None
            beta_error = None
            try:
                beta_result = _load_manifest(_BETA_MANIFEST_URL, headers)
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValueError,
                TimeoutError,
                RecursionError,
                http.client.HTTPException,
            ) as error:
                beta_error = error

            stable_headers = {
                key: value
                for key, value in headers.items()
                if key not in {"If-None-Match", "If-Modified-Since"}
            }
            try:
                stable_result = _load_manifest(_STABLE_MANIFEST_URL, stable_headers)
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValueError,
                TimeoutError,
                RecursionError,
                http.client.HTTPException,
            ):
                stable_result = None

            if beta_result is None and stable_result is None:
                raise beta_error
            if beta_result is not None:
                beta_status, _, beta_manifest = beta_result
                cache_result = beta_result
                status = beta_status
                if beta_manifest is not None:
                    manifests.append(beta_manifest)
            if stable_result is not None:
                stable_status, _, stable_manifest = stable_result
                if beta_result is None or stable_status == 200:
                    status = 200
                if stable_manifest is not None:
                    manifests.append(stable_manifest)
            if beta_result is not None and beta_result[0] == 304:
                pending_version = state.get("pending_version")
                if (
                    isinstance(pending_version, str)
                    and _VERSION_PATTERN.fullmatch(pending_version)
                ):
                    manifests.append(
                        {
                            "version": pending_version,
                            "notes_url": state.get("pending_notes_url", ""),
                            "min_updatable_from": state.get(
                                "pending_min_updatable_from", ""
                            ),
                        }
                    )
        else:
            cache_result = _load_manifest(_manifest_url(channel), headers)
            status, _, manifest = cache_result
            if manifest is not None:
                manifests.append(manifest)

        updates = {
            "last_checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last_check_attempt_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "update_check_failures": 0,
            "last_checked_channel": channel,
        }
        if cache_result is not None:
            cache_status, cache_headers, _ = cache_result
            if "etag" in cache_headers:
                updates["etag"] = cache_headers["etag"]
            elif cache_status == 200:
                updates["etag"] = ""
            if "last-modified" in cache_headers:
                updates["last_modified"] = cache_headers["last-modified"]
            elif cache_status == 200:
                updates["last_modified"] = ""

        if status == 200 or manifests:
            current_version = get_version()
            selected_manifest = None
            for manifest in manifests:
                if compare_versions(manifest["version"], current_version) <= 0:
                    continue
                if (
                    selected_manifest is None
                    or compare_versions(
                        manifest["version"], selected_manifest["version"]
                    ) > 0
                ):
                    selected_manifest = manifest
            if (
                selected_manifest is not None
                and state.get("skipped_version") != selected_manifest["version"]
            ):
                updates.update(
                    {
                        "pending_version": selected_manifest["version"],
                        "pending_notes_url": selected_manifest["notes_url"],
                        "pending_min_updatable_from": selected_manifest[
                            "min_updatable_from"
                        ],
                    }
                )
            else:
                updates.update(
                    {
                        "pending_version": "",
                        "pending_notes_url": "",
                        "pending_min_updatable_from": "",
                    }
                )
        _write_runtime_state(updates)
        return status, 0
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        TimeoutError,
        RecursionError,
        http.client.HTTPException,
    ) as error:
        logging.debug("업데이트 확인을 건너뜁니다: %s", error)
        return 0, _record_failure()


def _next_check_delay(failures: int) -> int:
    if failures <= 0:
        return _CHECK_INTERVAL_SECONDS
    return _CHECK_INTERVAL_SECONDS * min(2 ** min(failures, 3), 7)


def _initial_check_delay() -> int:
    try:
        state = _read_runtime_state()[1]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return _RNG.randint(60, 120)
    last_attempt = state.get("last_check_attempt_at")
    if not isinstance(last_attempt, str):
        return _RNG.randint(60, 120)
    try:
        attempted_at = datetime.strptime(last_attempt, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return _RNG.randint(60, 120)
    failures = state.get("update_check_failures", 0)
    failures = failures if isinstance(failures, int) and not isinstance(failures, bool) else 0
    due_at = attempted_at.timestamp() + _next_check_delay(failures)
    remaining = due_at - time.time()
    return int(remaining) if remaining > 0 else _RNG.randint(60, 120)


class UpdateChecker(QObject):
    """네트워크 확인을 백그라운드에서 실행하고 UI 알림을 예약한다."""

    _result_ready = Signal(object)
    status_changed = Signal(object)

    def __init__(self, tray_icon=None, character_widget=None, is_busy=None, is_game_mode=None):
        super().__init__()
        self.tray_icon = tray_icon
        self.character_widget = character_widget
        self.is_busy = is_busy or (lambda: False)
        self.is_game_mode = is_game_mode or (lambda: False)
        self._checking = False
        self._check_timer = QTimer(self)
        self._check_timer.setSingleShot(True)
        self._check_timer.timeout.connect(self.check_now)
        self._notify_timer = QTimer(self)
        self._notify_timer.setSingleShot(True)
        self._notify_timer.timeout.connect(self._notify_pending)
        self._result_ready.connect(self._on_check_complete)

    def start(self) -> None:
        if not is_release_build() or not _automatic_checks_enabled():
            return
        self._check_timer.start(_initial_check_delay() * 1000)

    def check_now(self) -> None:
        if self._checking or not is_release_build():
            return
        if self.is_game_mode():
            self._check_timer.start(_CHECK_INTERVAL_SECONDS * 1000)
            return
        self._checking = True
        worker = threading.Thread(target=self._run_check, daemon=True, name="UpdateCheck")
        worker.start()

    def _run_check(self) -> None:
        status, failures = _check_for_updates()
        self._result_ready.emit((status, failures))

    def _on_check_complete(self, value: object) -> None:
        self._checking = False
        status, failures = value
        delay = _CHECK_INTERVAL_SECONDS if status == 304 else _next_check_delay(failures)
        self._notify_pending()
        self.status_changed.emit(get_update_status())
        if _automatic_checks_enabled():
            self._check_timer.start(delay * 1000)

    def _notify_pending(self) -> None:
        if self.is_game_mode() or self.is_busy():
            self._notify_timer.start(60_000)
            return
        status = get_update_status()
        current_version = get_version()
        installed_version = status.get("installed_update_pending")
        installed_notice = installed_version == current_version
        version = status.get("pending_version")
        has_update = (
            isinstance(version, str)
            and bool(version)
            and compare_versions(version, current_version) > 0
            and status.get("skipped_version") != version
        )
        if not installed_notice and not has_update:
            return

        installed_message = _("Ari {version}으로 업데이트됐어요.").format(
            version=current_version
        )
        quick_message = _("빠른 로컬 명령 처리를 사용할 수 있습니다.")
        update_message = _("Ari {version}을 사용할 수 있어요.").format(version=version)
        minimum = status.get("pending_min_updatable_from")
        if (
            has_update
            and isinstance(minimum, str)
            and compare_versions(current_version, minimum) < 0
        ):
            update_message = _("Ari {version}은 직접 설치해야 합니다.").format(
                version=version
            )

        tray_messages = []
        state_updates = {}
        if installed_notice:
            tray_messages.extend((installed_message, quick_message))
        if has_update and status.get("notified_update_version") != version:
            tray_messages.append(update_message)
            state_updates["notified_update_version"] = version
        if self.tray_icon is not None and tray_messages:
            self.tray_icon.showMessage(
                _("업데이트 확인") if has_update else _("업데이트 완료"),
                "\n".join(tray_messages),
                QSystemTrayIcon.Information,
                10_000,
            )

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        bubble_messages = []
        if installed_notice:
            bubble_messages.extend((installed_message, quick_message))
            state_updates["installed_update_pending"] = ""
        if has_update and status.get("last_update_bubble_date") != today:
            bubble_messages.append(update_message)
        if self.character_widget is not None and bubble_messages:
            self.character_widget.say("\n".join(bubble_messages), duration=8_000)
            state_updates["last_update_bubble_date"] = today
        elif installed_notice and self.tray_icon is not None and tray_messages:
            state_updates["installed_update_pending"] = ""

        if state_updates:
            try:
                _write_runtime_state(state_updates)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                logging.debug("업데이트 알림 상태를 저장하지 못했습니다: %s", error)

    def notify_installed_update(self) -> None:
        self._notify_pending()

    def settings_changed(self) -> None:
        self._check_timer.stop()
        if _automatic_checks_enabled() and is_release_build():
            self._check_timer.start(1_000)

    def skip_pending_version(self) -> None:
        status = get_update_status()
        version = status.get("pending_version")
        if isinstance(version, str) and version:
            try:
                _write_runtime_state(
                    {
                        "skipped_version": version,
                        "pending_version": "",
                        "pending_notes_url": "",
                        "pending_min_updatable_from": "",
                    }
                )
                self.status_changed.emit(get_update_status())
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                logging.debug("건너뛴 업데이트를 저장하지 못했습니다: %s", error)

    def stop(self) -> None:
        self._check_timer.stop()
        self._notify_timer.stop()

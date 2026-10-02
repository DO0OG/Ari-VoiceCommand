"""Google OAuth 인증과 보호된 토큰 저장."""
from __future__ import annotations

import base64
import hashlib
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import secrets
import threading
import time
from urllib.parse import parse_qs, urlencode, urlparse
import webbrowser

import requests

from core.atomic_io import write_bytes_atomic
from core.resource_manager import ResourceManager
from core.secret_store import protect_bytes, unprotect_bytes
from i18n.translator import _

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
EXCHANGE_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
SCOPES = (
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
)
AUTH_CACHE_FILENAME = "google_token.dpapi"
LEGACY_AUTH_CACHE_FILENAME = "google_token.json"
CALLBACK_READ_TIMEOUT = 3


class GoogleAuthRequired(RuntimeError):
    pass


class GoogleOAuthError(RuntimeError):
    def __init__(self, error: str, description: str = ""):
        self.error = error
        super().__init__(f"{error}: {description}" if description else error)


_TOKEN_LOCK = threading.RLock()


def _token_path() -> str:
    return ResourceManager.get_runtime_path(AUTH_CACHE_FILENAME)


def _legacy_token_path() -> str:
    return ResourceManager.get_runtime_path(LEGACY_AUTH_CACHE_FILENAME)


def load_token() -> dict | None:
    path = _token_path()
    try:
        with open(path, "rb") as handle:
            encrypted = handle.read()
    except FileNotFoundError:
        legacy_path = _legacy_token_path()
        try:
            with open(legacy_path, "r", encoding="utf-8") as handle:
                token = json.load(handle)
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(token, dict):
            return None
        token.setdefault("expires_at", 0)
        save_token(token)
        os.remove(legacy_path)
        return token
    try:
        token = json.loads(unprotect_bytes(encrypted).decode("utf-8"))
    except Exception:
        raise GoogleAuthRequired("Google 인증 토큰을 읽을 수 없습니다.") from None
    return token if isinstance(token, dict) else None


def save_token(token: dict) -> None:
    payload = json.dumps({key: token.get(key, "" if key != "expires_at" else 0) for key in (
        "access_token", "refresh_token", "expires_at", "scope", "client_id", "client_secret"
    )}, ensure_ascii=False).encode("utf-8")
    write_bytes_atomic(_token_path(), protect_bytes(payload))


def clear_token() -> None:
    try:
        os.remove(_token_path())
    except FileNotFoundError:
        pass


def build_authorization_request(client_id: str, redirect_uri: str) -> tuple[str, str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    state = secrets.token_urlsafe(32)
    url = AUTH_URL + "?" + urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    })
    return url, verifier, state


def _oauth_response(response, sensitive_values=()) -> dict:
    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError):
        body = {}
    if not isinstance(body, dict):
        body = {}
    if not response.ok:
        error = str(body.get("error", "request_failed"))
        description = str(body.get("error_description", ""))
        for value in sensitive_values:
            if value:
                error = error.replace(value, "[redacted]")
                description = description.replace(value, "[redacted]")
        raise GoogleOAuthError(
            error,
            description,
        )
    if not body:
        raise GoogleOAuthError("invalid_response")
    return body


def exchange_code(client_id: str, client_secret: str, code: str, code_verifier: str, redirect_uri: str) -> dict:
    response = requests.post(
        EXCHANGE_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    token = _oauth_response(response, (client_secret, code, code_verifier))
    token["expires_at"] = time.time() + int(token.get("expires_in", 0))
    return token


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> dict:
    response = requests.post(
        EXCHANGE_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    return _oauth_response(response, (client_secret, refresh_token))


def authorize(client_id: str, client_secret: str, *, open_browser=webbrowser.open, timeout: int = 180, cancel_event=None) -> None:
    received = threading.Event()
    result: dict[str, str] = {}
    expected_state = ""

    class CallbackHandler(BaseHTTPRequestHandler):
        timeout = CALLBACK_READ_TIMEOUT

        def do_GET(self):
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            if parsed.path != "/":
                self.send_error(404)
                return
            if params.get("state", [""])[0] != expected_state:
                self.send_error(400)
                return
            result["state"] = params.get("state", [""])[0]
            result["code"] = params.get("code", [""])[0]
            result["error"] = params.get("error", [""])[0]
            result["error_description"] = params.get("error_description", [""])[0]
            received.set()
            message = html.escape(_("Google 인증이 완료되었습니다. 이 창을 닫아도 됩니다."))
            body = f"<html><body>{message}</body></html>".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # pylint: disable=redefined-builtin
            return

    server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
    server.timeout = 0.25
    try:
        redirect_uri = f"http://127.0.0.1:{server.server_address[1]}"
        url, verifier, expected_state = build_authorization_request(client_id, redirect_uri)
        if not open_browser(url):
            raise RuntimeError(_("Google 인증 브라우저를 열 수 없습니다."))
        deadline = time.monotonic() + timeout
        while not received.is_set():
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError(_("Google 인증이 취소되었습니다."))
            if time.monotonic() >= deadline:
                raise TimeoutError(_("Google 인증 시간이 초과되었습니다."))
            server.handle_request()
        if result.get("error"):
            raise GoogleOAuthError(result["error"], result.get("error_description", ""))
        if not result.get("code"):
            raise RuntimeError(_("Google 인증 코드가 없습니다."))
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError(_("Google 인증이 취소되었습니다."))
        token = exchange_code(client_id, client_secret, result["code"], verifier, redirect_uri)
        token["client_id"] = client_id
        token["client_secret"] = client_secret
        if cancel_event is not None and cancel_event.is_set():
            try:
                requests.post(
                    REVOKE_URL,
                    data={"token": token.get("refresh_token") or token.get("access_token", "")},
                    timeout=15,
                )
            except requests.RequestException:
                pass
            raise RuntimeError(_("Google 인증이 취소되었습니다."))
        save_token(token)
    finally:
        server.server_close()


def _configured_credentials() -> tuple[str, str]:
    from core.config_manager import ConfigManager
    return str(ConfigManager.get("google_client_id", "") or ""), str(ConfigManager.get("google_client_secret", "") or "")


def _refresh_stored_token(token: dict) -> str:
    client_id = str(token.get("client_id", "") or "")
    client_secret = str(token.get("client_secret", "") or "")
    if not client_id or not client_secret:
        client_id, client_secret = _configured_credentials()
    if not client_id or not client_secret:
        raise GoogleAuthRequired("설정에 저장된 Google Client ID·Secret을 확인하고 다시 연결해 주세요.")
    try:
        refreshed = refresh_access_token(client_id, client_secret, str(token.get("refresh_token", "")))
    except GoogleOAuthError as exc:
        if exc.error == "invalid_grant":
            clear_token()
            raise GoogleAuthRequired("Google 인증이 만료되었습니다. 다시 연결해 주세요.") from None
        if exc.error == "invalid_client":
            raise GoogleAuthRequired("설정에 저장된 Google Client ID·Secret을 확인하고 다시 연결해 주세요.") from None
        raise
    token.update(refreshed)
    token["expires_at"] = time.time() + int(refreshed.get("expires_in", 0))
    token["refresh_token"] = refreshed.get("refresh_token") or token.get("refresh_token", "")
    save_token(token)
    access_token = str(token.get("access_token", "") or "")
    if not access_token:
        raise GoogleAuthRequired("Google 인증 토큰에 access_token이 없습니다.")
    return access_token


def get_access_token() -> str:
    with _TOKEN_LOCK:
        token = load_token()
        if not token:
            raise GoogleAuthRequired("Google 인증 토큰이 없습니다. 설정에서 계정을 연결해 주세요.")
        access = str(token.get("access_token", "") or "")
        expires_at = float(token.get("expires_at", 0) or 0)
        if access and expires_at > time.time() + 60:
            return access
        if access and expires_at == 0 and not token.get("refresh_token"):
            return access
        if not token.get("refresh_token"):
            raise GoogleAuthRequired("Google 인증이 만료되었습니다. 다시 연결해 주세요.")
        return _refresh_stored_token(token)


def force_refresh_access_token() -> str:
    with _TOKEN_LOCK:
        token = load_token()
        if not token or not token.get("refresh_token"):
            raise GoogleAuthRequired("Google 인증이 만료되었습니다. 다시 연결해 주세요.")
        return _refresh_stored_token(token)


def request_with_auth(method, url: str, **kwargs):
    token = get_access_token()
    headers = dict(kwargs.pop("headers", {}) or {})
    headers["Authorization"] = f"Bearer {token}"
    response = method(url, headers=headers, **kwargs)
    if response.status_code == 401:
        token = force_refresh_access_token()
        headers["Authorization"] = f"Bearer {token}"
        response = method(url, headers=headers, **kwargs)
        if response.status_code == 401:
            raise GoogleAuthRequired("Google 인증을 다시 연결해 주세요.")
    response.raise_for_status()
    return response


def sign_out() -> None:
    with _TOKEN_LOCK:
        try:
            token = load_token()
        except GoogleAuthRequired:
            token = None
        try:
            if token:
                try:
                    requests.post(REVOKE_URL, data={"token": token.get("refresh_token") or token.get("access_token", "")}, timeout=15)
                except requests.RequestException:
                    pass
        finally:
            clear_token()


def is_connected() -> bool:
    try:
        return bool(load_token())
    except Exception:
        return False

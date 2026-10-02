import base64
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

from services import google_auth
from services.google_calendar import GoogleCalendarService


class GoogleAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.token_path = Path(self.temp_dir.name) / "google_token.dpapi"
        self.legacy_path = Path(self.temp_dir.name) / "google_token.json"
        self.patches = [
            patch.object(google_auth, "_token_path", return_value=str(self.token_path)),
            patch.object(google_auth, "_legacy_token_path", return_value=str(self.legacy_path)),
            patch.object(google_auth, "protect_bytes", side_effect=lambda value: value),
            patch.object(google_auth, "unprotect_bytes", side_effect=lambda value: value),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp_dir.cleanup()

    def test_authorization_request_uses_pkce_and_required_parameters(self):
        url, verifier, state = google_auth.build_authorization_request("client", "http://127.0.0.1:1234")
        self.assertGreaterEqual(len(verifier), 43)
        self.assertLessEqual(len(verifier), 128)
        self.assertRegex(verifier, r"^[A-Za-z0-9._~-]+$")
        params = parse_qs(urlparse(url).query)
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode().rstrip("=")
        self.assertEqual(params["code_challenge"], [expected])
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertEqual(params["state"], [state])
        self.assertEqual(params["client_id"], ["client"])
        self.assertEqual(params["redirect_uri"], ["http://127.0.0.1:1234"])
        self.assertEqual(params["response_type"], ["code"])
        self.assertEqual(params["scope"], [" ".join(google_auth.SCOPES)])
        self.assertEqual(params["prompt"], ["consent"])

    def test_cancel_event_stops_authorization_wait(self):
        cancel_event = threading.Event()

        def cancel_after_open(_url):
            cancel_event.set()
            return True

        with self.assertRaisesRegex(RuntimeError, "취소"):
            google_auth.authorize(
                "client", "secret", open_browser=cancel_after_open,
                timeout=5, cancel_event=cancel_event,
            )

    def _authorize_callback(self, query):
        posted = Mock(ok=True)
        posted.json.return_value = {
            "access_token": "access",
            "expires_in": 3600,
            "refresh_token": "refresh",
            "scope": "scope",
        }
        class FakeServer:
            instances = []

            def __init__(self, _address, handler_class):
                self.server_address = ("127.0.0.1", 1234)
                self.handler_class = handler_class
                self.callbacks = []
                self.errors = []
                FakeServer.instances.append(self)

            def handle_request(self):
                handler = self.handler_class.__new__(self.handler_class)
                handler.path = "/?" + self.callbacks.pop(0)
                handler.wfile = Mock()
                handler.send_response = Mock()
                handler.send_error = Mock()
                handler.send_header = Mock()
                handler.end_headers = Mock()
                handler.do_GET()
                if handler.send_error.called:
                    self.errors.append(handler.send_error.call_args.args[0])

            def server_close(self):
                pass

        def open_browser(url):
            params = parse_qs(urlparse(url).query)
            queries = query(params)
            if isinstance(queries, str):
                queries = [queries]
            FakeServer.instances[-1].callbacks = queries
            return True

        FakeServer.instances.clear()
        with patch.object(google_auth, "HTTPServer", FakeServer), patch.object(
            google_auth.requests, "post", return_value=posted
        ) as post, patch.object(google_auth.webbrowser, "open", side_effect=open_browser) as browser:
            outcome = None
            try:
                google_auth.authorize("client", "secret", open_browser=google_auth.webbrowser.open, timeout=5)
            except Exception as exc:
                outcome = exc
            browser.assert_called_once()
        return outcome, post, FakeServer.instances[0].errors

    def test_state_mismatch_is_ignored_until_valid_callback(self):
        error, post, callback_errors = self._authorize_callback(
            lambda params: [
                "state=wrong&code=wrong-code",
                f"state={params['state'][0]}&code=valid-code",
            ]
        )
        self.assertIsNone(error)
        self.assertEqual(callback_errors, [400])
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["data"]["code"], "valid-code")

    def test_access_denied_callback_fails(self):
        error, post, _ = self._authorize_callback(lambda params: f"state={params['state'][0]}&error=access_denied")
        self.assertIsInstance(error, google_auth.GoogleOAuthError)
        post.assert_not_called()

    def test_successful_callback_exchanges_and_saves_token(self):
        error, post, _ = self._authorize_callback(lambda params: f"state={params['state'][0]}&code=auth-code")
        self.assertIsNone(error)
        self.assertEqual(post.call_args.kwargs["data"]["code"], "auth-code")
        token = google_auth.load_token()
        self.assertEqual(token["access_token"], "access")
        self.assertEqual(token["refresh_token"], "refresh")
        self.assertGreater(token["expires_at"], 0)

    def test_expired_token_refreshes_and_keeps_existing_refresh_token(self):
        google_auth.save_token({"access_token": "old", "refresh_token": "refresh", "expires_at": 1, "scope": "scope"})
        refreshed = Mock(ok=True)
        refreshed.json.return_value = {"access_token": "new", "expires_in": 3600}
        with patch("core.config_manager.ConfigManager.get", side_effect=lambda key, default=None: {"google_client_id": "id", "google_client_secret": "secret"}.get(key, default)), patch.object(google_auth.requests, "post", return_value=refreshed):
            self.assertEqual(google_auth.get_access_token(), "new")
        saved = google_auth.load_token()
        self.assertEqual(saved["refresh_token"], "refresh")
        self.assertEqual(saved["access_token"], "new")

    def test_invalid_grant_clears_token_and_requires_authorization(self):
        google_auth.save_token({"access_token": "old", "refresh_token": "refresh", "expires_at": 1})
        rejected = Mock(ok=False)
        rejected.json.return_value = {"error": "invalid_grant"}
        with patch("core.config_manager.ConfigManager.get", return_value="value"), patch.object(google_auth.requests, "post", return_value=rejected):
            with self.assertRaises(google_auth.GoogleAuthRequired):
                google_auth.get_access_token()
        self.assertFalse(self.token_path.exists())

    def test_oauth_error_does_not_expose_client_secret_or_refresh_token(self):
        rejected = Mock(ok=False)
        rejected.json.return_value = {
            "error": "invalid_client",
            "error_description": "secret-value refresh-value",
        }
        with patch.object(google_auth.requests, "post", return_value=rejected):
            with self.assertRaises(google_auth.GoogleOAuthError) as caught:
                google_auth.refresh_access_token("id", "secret-value", "refresh-value")
        self.assertNotIn("secret-value", str(caught.exception))
        self.assertNotIn("refresh-value", str(caught.exception))

    def test_legacy_plaintext_token_moves_to_protected_file(self):
        self.legacy_path.write_text(json.dumps({"access_token": "old", "refresh_token": "refresh"}), encoding="utf-8")
        token = google_auth.load_token()
        self.assertEqual(token["expires_at"], 0)
        self.assertTrue(self.token_path.exists())
        self.assertFalse(self.legacy_path.exists())

    def test_legacy_plaintext_remains_if_protected_write_fails(self):
        self.legacy_path.write_text(json.dumps({"access_token": "old"}), encoding="utf-8")
        with patch.object(google_auth, "protect_bytes", side_effect=RuntimeError("protect failed")):
            with self.assertRaises(RuntimeError):
                google_auth.load_token()
        self.assertTrue(self.legacy_path.exists())

    def test_corrupt_legacy_token_is_ignored_and_preserved(self):
        for content in (b"{", b"\xff", b"[]"):
            with self.subTest(content=content):
                self.legacy_path.write_bytes(content)
                self.assertIsNone(google_auth.load_token())
                self.assertEqual(self.legacy_path.read_bytes(), content)

    def test_legacy_access_token_without_expiry_or_refresh_is_returned(self):
        google_auth.save_token({"access_token": "old"})
        with patch.object(google_auth.requests, "post") as post:
            self.assertEqual(google_auth.get_access_token(), "old")
        post.assert_not_called()

    def test_missing_client_id_and_invalid_client_require_reconnect_without_deleting_token(self):
        google_auth.save_token({"access_token": "old", "refresh_token": "refresh", "expires_at": 1})
        with patch("core.config_manager.ConfigManager.get", side_effect=lambda key, default=None: {"google_client_id": "", "google_client_secret": "secret"}.get(key, default)), patch.object(google_auth.requests, "post") as post:
            with self.assertRaisesRegex(google_auth.GoogleAuthRequired, "Client ID·Secret"):
                google_auth.get_access_token()
        post.assert_not_called()
        self.assertTrue(self.token_path.exists())

        with patch("core.config_manager.ConfigManager.get", side_effect=lambda key, default=None: {"google_client_id": "id", "google_client_secret": "secret"}.get(key, default)):
            rejected = Mock(ok=False)
            rejected.json.return_value = {"error": "invalid_client"}
            with patch.object(google_auth.requests, "post", return_value=rejected):
                with self.assertRaisesRegex(google_auth.GoogleAuthRequired, "Client ID·Secret"):
                    google_auth.get_access_token()
        self.assertTrue(self.token_path.exists())

    def test_calendar_retries_once_after_401_and_uses_z_time(self):
        unauthorized = Mock(status_code=401)
        authorized = Mock(status_code=200)
        authorized.json.return_value = {"items": []}
        with patch.object(google_auth, "get_access_token", return_value="old"), patch.object(google_auth, "force_refresh_access_token", return_value="new"), patch("services.google_calendar.requests.get", side_effect=[unauthorized, authorized]) as get:
            self.assertEqual(GoogleCalendarService().get_events(), [])
        self.assertEqual(get.call_count, 2)
        params = get.call_args.kwargs["params"]
        self.assertTrue(params["timeMin"].endswith("Z"))
        self.assertNotIn("+00:00", params["timeMin"])


if __name__ == "__main__":
    unittest.main()

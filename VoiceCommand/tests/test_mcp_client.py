import json
import unittest
from io import BytesIO
from urllib.error import HTTPError
from unittest import mock


from agent.mcp_client import McpClientPool, McpSession, reset_mcp_pool


class _FakeResponse:
    def __init__(self, payload: bytes = b"", *, headers: dict | None = None, lines: list[bytes] | None = None):
        self._payload = payload
        self.headers = headers or {}
        self._lines = list(lines or [])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._payload

    def readline(self):
        if not self._lines:
            return b""
        return self._lines.pop(0)


class McpClientTests(unittest.TestCase):
    def tearDown(self):
        reset_mcp_pool()

    def test_initialize_sends_initialized_notification(self):
        seen_requests = []

        def fake_urlopen(request, timeout=None):
            del timeout
            seen_requests.append(request)
            method = request.get_method()
            if method == "POST" and len(seen_requests) == 1:
                payload = {"jsonrpc": "2.0", "result": {"capabilities": {}}}
                return _FakeResponse(
                    json.dumps(payload).encode("utf-8"),
                    headers={
                        "Mcp-Session-Id": "session-123",
                        "Content-Type": "application/json",
                    },
                )
            return _FakeResponse(b"", headers={"Content-Type": "application/json"})

        session = McpSession("https://example.com/mcp")
        with mock.patch("agent.mcp_client.urlopen", side_effect=fake_urlopen):
            self.assertTrue(session.initialize())

        self.assertEqual(session.session_id, "session-123")
        self.assertEqual(len(seen_requests), 2)
        notification_payload = json.loads(seen_requests[1].data.decode("utf-8"))
        self.assertEqual(notification_payload["method"], "notifications/initialized")

    def test_call_tool_parses_sse_response(self):
        session = McpSession("https://example.com/mcp")
        session.session_id = "session-123"
        sse_payload = b"event: message\ndata: {\"result\":{\"content\":[{\"type\":\"text\",\"text\":\"ok\"}]}}\n\n"

        with mock.patch(
            "agent.mcp_client.urlopen",
            return_value=_FakeResponse(
                sse_payload,
                headers={"Content-Type": "text/event-stream"},
            ),
        ):
            result = session.call_tool("search_coupang_products", {"keyword": "monitor"})

        self.assertEqual(result, "ok")

    def test_sse_listener_delivers_notifications(self):
        session = McpSession("https://example.com/mcp")
        session.session_id = "session-123"
        notifications = []
        session._notification_cb = notifications.append
        response = _FakeResponse(
            lines=[
                b"event: message\n",
                b"data: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/tools/list_changed\"}\n",
                b"\n",
                b"",
            ],
            headers={"Content-Type": "text/event-stream"},
        )

        with mock.patch("agent.mcp_client.urlopen", return_value=response):
            session._start_sse_listener()
            session._sse_thread.join(timeout=2.0)

        self.assertTrue(notifications)
        self.assertEqual(notifications[0]["method"], "notifications/tools/list_changed")

    def test_close_ignores_http_405(self):
        session = McpSession("https://example.com/mcp")
        session.session_id = "session-123"
        error = HTTPError("https://example.com/mcp", 405, "Method Not Allowed", {}, BytesIO())

        with mock.patch("agent.mcp_client.urlopen", side_effect=error):
            session.close()

        self.assertIsNone(session.session_id)

    def test_pool_close_all_closes_sessions(self):
        pool = McpClientPool()
        session_a = mock.Mock()
        session_b = mock.Mock()
        pool._sessions = {
            "https://example.com/a": session_a,
            "https://example.com/b": session_b,
        }

        pool.close_all()

        session_a.close.assert_called_once()
        session_b.close.assert_called_once()
        self.assertEqual(pool._sessions, {})


if __name__ == "__main__":
    unittest.main()

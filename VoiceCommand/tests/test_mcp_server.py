import json
import unittest
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent.mcp_server import AriMCPServer


class MCPServerTests(unittest.TestCase):
    def test_http_boundary_requires_token_and_valid_host_origin(self):
        middleware = []
        app = Mock()
        app.middleware.return_value = lambda handler: middleware.append(handler) or handler
        def response(content, status_code=200):
            return SimpleNamespace(status_code=status_code)

        with patch.dict("sys.modules", {
            "fastapi": SimpleNamespace(FastAPI=lambda **kwargs: app),
            "fastapi.responses": SimpleNamespace(JSONResponse=response),
        }):
            AriMCPServer(token="secret").create_app()
            AriMCPServer(token="").create_app()

        async def next_handler(request):
            return response({}, 200)

        cases = [
            ({"host": ["127.0.0.1:8765"]}, 401),
            ({"host": ["evil.example:8765"], "authorization": ["Bearer secret"]}, 403),
            ({"host": ["127.0.0.1:8765"], "origin": ["https://evil.example"], "authorization": ["Bearer secret"]}, 403),
            ({"host": ["127.0.0.1:8765"], "origin": ["null"], "authorization": ["Bearer secret"]}, 403),
            ({"host": ["localhost:8765"], "authorization": ["Bearer wrong"]}, 401),
            ({"host": ["localhost:8765"], "authorization": ["Bearer secret"]}, 200),
            ({"host": ["127.0.0.1:8765"], "origin": ["http://localhost:8765"], "authorization": ["Bearer secret"]}, 200),
            ({"host": ["localhost:8765", "evil.example"], "authorization": ["Bearer secret"]}, 403),
        ]
        for headers, expected in cases:
            with self.subTest(headers=headers):
                request = SimpleNamespace(headers=SimpleNamespace(getlist=lambda key: headers.get(key, [])))
                self.assertEqual(asyncio.run(middleware[0](request, next_handler)).status_code, expected)
        request = SimpleNamespace(headers=SimpleNamespace(getlist=lambda key: {
            "host": ["localhost:8765"], "authorization": ["Bearer secret"],
        }.get(key, [])))
        self.assertEqual(asyncio.run(middleware[1](request, next_handler)).status_code, 503)

    def test_file_tools_deny_paths_outside_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "allowed"
            root.mkdir()
            server = AriMCPServer(allowed_paths=[str(root)])
            with patch("agent.file_tools.read_file", return_value={"ok": True}) as read, \
                 patch("agent.file_tools.write_file", return_value={"ok": True}) as write:
                for path in (root / ".." / "secret", Path(directory) / "allowed-sibling" / "secret"):
                    self.assertIn("error:", server._read_file(str(path)))
                    self.assertIn("error:", server._write_file(str(path), "data"))
                read.assert_not_called()
                write.assert_not_called()
                server._read_file(str(root / "file"))
                server._write_file(str(root / "new-file"), "data")
                read.assert_called_once()
                write.assert_called_once()
            with self.assertRaises(PermissionError):
                AriMCPServer(allowed_paths=[])._resolve_allowed_path(str(root / "file"))

    def test_resolved_link_outside_allowlist_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = AriMCPServer(allowed_paths=[str(root)])
            with patch.object(Path, "resolve", return_value=root.parent / "secret"):
                with self.assertRaises(PermissionError):
                    server._resolve_allowed_path(str(root / "link"))

    def test_tools_list_returns_ari_tools(self):
        server = AriMCPServer()
        response = server.handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertIn("ari_tts", names)
        self.assertIn("ari_get_system_info", names)

    def test_system_info_tool_returns_text_content(self):
        server = AriMCPServer()
        response = server.handle_jsonrpc({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "ari_get_system_info", "arguments": {}},
        })
        text = response["result"]["content"][0]["text"]
        self.assertIsInstance(json.loads(text), dict)


if __name__ == "__main__":
    unittest.main()

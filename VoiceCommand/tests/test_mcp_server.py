import json
import unittest

from agent.mcp_server import AriMCPServer


class MCPServerTests(unittest.TestCase):
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

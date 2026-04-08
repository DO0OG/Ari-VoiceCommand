import os
import tempfile
import unittest


from agent.llm_provider import LLMProvider
from commands.ai_command import AICommand
from commands.base_command import BaseCommand
from commands.command_registry import CommandRegistry
from core.plugin_loader import PluginContext, PluginManager
from core.plugin_sandbox import run_sandboxed


class _FakeAssistant:
    def chat_with_tools(self, text, include_context=True):
        return "무엇을 도와드릴까요?", []

    def feed_tool_result(self, original_text, tool_calls, results):
        del original_text, tool_calls, results
        return ""


class _TempPluginManager(PluginManager):
    def __init__(self, plugin_dir: str):
        super().__init__()
        self._plugin_dir = plugin_dir

    def plugin_dir(self) -> str:
        return self._plugin_dir


class _DummyCommand(BaseCommand):
    priority = 5

    def matches(self, text: str) -> bool:
        return text == "dummy"

    def execute(self, text: str) -> None:
        del text


class PluginSystemTests(unittest.TestCase):
    def test_plugin_api_version_rejects_incompatible_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_path = os.path.join(tmp, "bad_plugin.py")
            with open(plugin_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "PLUGIN_INFO = {'name': 'bad', 'version': '0.0.1', 'api_version': '99.0'}\n"
                )
            manager = _TempPluginManager(tmp)
            plugins = manager.load_plugins(PluginContext())
            self.assertFalse(plugins[0].loaded)
            self.assertIn("호환되지 않는 플러그인 API 버전", plugins[0].error)

    def test_plugin_context_injects_sandbox_and_callbacks(self):
        calls = {"menu": [], "cmd": [], "tool": []}
        with tempfile.TemporaryDirectory() as tmp:
            plugin_path = os.path.join(tmp, "good_plugin.py")
            with open(plugin_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "PLUGIN_INFO = {'name': 'good', 'version': '1.0.0', 'api_version': '1.0'}\n"
                    "def register(context):\n"
                    "    context.register_menu_action('메뉴', lambda: None)\n"
                    "    context.register_command(object())\n"
                    "    context.register_tool({'type':'function','function':{'name':'plug_tool','description':'d','parameters':{'type':'object','properties':{}}}}, lambda args: 'ok')\n"
                    "    return {'sandbox': callable(context.run_sandboxed)}\n"
                )
            manager = _TempPluginManager(tmp)
            plugins = manager.load_plugins(
                PluginContext(
                    register_menu_action=lambda label, callback: calls["menu"].append(label),
                    register_command=lambda command: calls["cmd"].append(command),
                    register_tool=lambda schema, handler: calls["tool"].append((schema["function"]["name"], handler({}))),
                )
            )
            self.assertTrue(plugins[0].loaded)
            self.assertTrue(plugins[0].exports["sandbox"])
            self.assertEqual(calls["menu"], ["메뉴"])
            self.assertEqual(len(calls["cmd"]), 1)
            self.assertEqual(calls["tool"][0][0], "plug_tool")

    def test_command_registry_register_command_keeps_priority_order(self):
        registry = CommandRegistry(None, object(), object(), lambda *_: None, lambda *_: None, {"enabled": False})
        registry.register_command(_DummyCommand())
        self.assertIsInstance(registry.commands[0], _DummyCommand)

    def test_llm_provider_register_plugin_tool_extends_tools(self):
        provider = LLMProvider()
        provider.register_plugin_tool(
            {
                "type": "function",
                "function": {
                    "name": "plugin_tool",
                    "description": "plugin",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        )
        tool_names = [tool["function"]["name"] for tool in provider.get_available_tools()]
        self.assertIn("plugin_tool", tool_names)

    def test_ai_command_register_plugin_tool_handler_updates_dispatch(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})
        command.register_plugin_tool_handler("plugin_tool", lambda args: args.get("name", ""))
        self.assertIn("plugin_tool", command._dispatch)
        self.assertEqual(command._dispatch["plugin_tool"]({"name": "ok"}), "ok")

    def test_plugin_sandbox_handles_success_error_and_timeout(self):
        self.assertEqual(run_sandboxed("print(42)")["output"], "42\n")
        self.assertFalse(run_sandboxed("1/0")["ok"])
        self.assertIn("ZeroDivisionError", run_sandboxed("1/0")["error"])
        self.assertFalse(run_sandboxed("import time; time.sleep(2)", timeout=1)["ok"])


if __name__ == "__main__":
    unittest.main()

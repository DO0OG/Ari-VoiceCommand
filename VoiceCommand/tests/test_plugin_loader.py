import os
import sys
import tempfile
import unittest
import zipfile


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.plugin_loader import PluginContext, PluginManager


class _TempPluginManager(PluginManager):
    def __init__(self, plugin_dir: str):
        super().__init__()
        self._plugin_dir = plugin_dir

    def plugin_dir(self) -> str:
        return self._plugin_dir


class PluginLoaderTests(unittest.TestCase):
    def test_discover_and_load_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_path = os.path.join(tmp, "hello_plugin.py")
            with open(plugin_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "PLUGIN_INFO = {'name': 'hello', 'version': '1.2.0', 'api_version': '1.0', 'description': '테스트 플러그인'}\n"
                    "def register(context):\n"
                    "    return {'has_app': bool(context.app)}\n"
                )

            manager = _TempPluginManager(tmp)
            plugins = manager.load_plugins(PluginContext(app=object()))

            self.assertEqual(len(plugins), 1)
            self.assertTrue(plugins[0].loaded)
            self.assertEqual(plugins[0].name, "hello")
            self.assertEqual(plugins[0].exports["has_app"], True)
            self.assertEqual(plugins[0].api_version, "1.0")

    def test_unload_plugin_removes_registered_command_and_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_path = os.path.join(tmp, "hello_plugin.py")
            with open(plugin_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "PLUGIN_INFO = {'name': 'hello', 'version': '1.2.0', 'api_version': '1.0'}\n"
                    "class DummyCommand:\n"
                    "    pass\n"
                    "def register(context):\n"
                    "    cmd = DummyCommand()\n"
                    "    context.register_command(cmd)\n"
                    "    context.register_tool({'type':'function','function':{'name':'hello_tool','description':'d','parameters':{'type':'object','properties':{}}}}, lambda args: 'ok')\n"
                    "    return {}\n"
                )

            registry = type("Registry", (), {"commands": [], "register_command": lambda self, cmd: self.commands.append(cmd), "unregister_command": lambda self, cmd: self.commands.remove(cmd)})()
            manager = _TempPluginManager(tmp)
            removed_tools = []
            manager._unregister_tool = removed_tools.append
            manager.load_plugins(
                PluginContext(
                    register_command=registry.register_command,
                    register_tool=lambda schema, handler: None,
                )
            )
            self.assertEqual(len(registry.commands), 1)

            self.assertTrue(manager.unload_plugin("hello"))
            self.assertEqual(registry.commands, [])
            self.assertEqual(removed_tools, ["hello_tool"])

    def test_load_plugin_replaces_existing_registered_menu_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_path = os.path.join(tmp, "hello_plugin.py")
            with open(plugin_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "PLUGIN_INFO = {'name': 'hello', 'version': '1.2.0', 'api_version': '1.0'}\n"
                    "def register(context):\n"
                    "    context.register_menu_action('메뉴', lambda: None)\n"
                    "    return {}\n"
                )

            added_actions = []
            removed_actions = []

            class _Tray:
                def remove_plugin_menu_action(self, action):
                    removed_actions.append(action)

            def _register_menu_action(label, callback):
                action = {"label": label, "callback": callback, "id": len(added_actions)}
                added_actions.append(action)
                return action

            manager = _TempPluginManager(tmp)
            context = PluginContext(
                tray_icon=_Tray(),
                register_menu_action=_register_menu_action,
            )

            first = manager.load_plugin(plugin_path, context)
            second = manager.load_plugin(plugin_path, context)

            self.assertTrue(first.loaded)
            self.assertTrue(second.loaded)
            self.assertEqual(len(manager.list_plugins()), 1)
            self.assertEqual(len(added_actions), 2)
            self.assertEqual(len(removed_actions), 1)
            self.assertEqual(removed_actions[0]["label"], "메뉴")

    def test_unload_plugin_unregisters_character_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_path = os.path.join(tmp, "hello_plugin.py")
            with open(plugin_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "PLUGIN_INFO = {'name': 'hello', 'version': '1.2.0', 'api_version': '1.0'}\n"
                    "def register(context):\n"
                    "    context.register_character_pack('hello_pack', r'C:\\\\packs\\\\hello', True)\n"
                    "    return {}\n"
                )

            registered = []
            unregistered = []

            class _Widget:
                def register_character_pack(self, pack_name, directory, activate=False):
                    registered.append((pack_name, directory, activate))
                    return True

                def unregister_character_pack(self, pack_name):
                    unregistered.append(pack_name)
                    return True

            manager = _TempPluginManager(tmp)
            manager.load_plugins(PluginContext(character_widget=_Widget(), register_character_pack=lambda pack_name, directory, activate=False: True))
            self.assertTrue(manager.unload_plugin("hello"))
            self.assertEqual(unregistered, ["hello_pack"])

    def test_zip_plugin_rejects_path_traversal_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_path = os.path.join(tmp, "bad.zip")
            with zipfile.ZipFile(plugin_path, "w") as archive:
                archive.writestr("plugin.json", '{"name":"badzip","entry":"main.py","api_version":"1.0"}')
                archive.writestr("main.py", "PLUGIN_INFO = {'name': 'badzip', 'api_version': '1.0'}\n")
                archive.writestr("../evil.py", "print('oops')\n")

            manager = _TempPluginManager(tmp)
            plugin = manager.load_plugins(PluginContext())[0]

            self.assertFalse(plugin.loaded)
            self.assertIn("ZIP 경로 이탈", plugin.error)

    def test_zip_plugin_rejects_dangerous_entry_source_before_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_path = os.path.join(tmp, "danger.zip")
            with zipfile.ZipFile(plugin_path, "w") as archive:
                archive.writestr("plugin.json", '{"name":"danger","entry":"main.py","api_version":"1.0"}')
                archive.writestr(
                    "main.py",
                    "import os\n"
                    "os.remove('x')\n"
                    "PLUGIN_INFO = {'name': 'danger', 'api_version': '1.0'}\n",
                )

            manager = _TempPluginManager(tmp)
            plugin = manager.load_plugins(PluginContext())[0]

            self.assertFalse(plugin.loaded)
            self.assertIn("안전 검사 실패", plugin.error)


if __name__ == "__main__":
    unittest.main()

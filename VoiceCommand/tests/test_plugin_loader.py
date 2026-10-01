import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
import zipfile
from unittest.mock import Mock, patch


from core.plugin_loader import PluginContext, PluginInfo, PluginManager
from i18n.translator import _


class _TempPluginManager(PluginManager):
    def __init__(self, plugin_dir: str):
        self._plugin_dir = plugin_dir
        self._trust_path = os.path.join(plugin_dir, "plugin_trust.json")
        super().__init__()

    def plugin_dir(self) -> str:
        return self._plugin_dir

    def _trusted_plugins_path(self) -> str:
        return self._trust_path

    def _confirm_plugin_load(self, _plugin_name: str) -> bool:
        return True


class PluginLoaderTests(unittest.TestCase):
    def test_discovery_does_not_replace_loaded_plugin_cleanup_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_path = os.path.join(tmp, "active_plugin.py")
            with open(plugin_path, "w", encoding="utf-8") as handle:
                handle.write("PLUGIN_INFO = {}\n")
            manager = _TempPluginManager(tmp)
            active = PluginInfo(
                name="active_plugin",
                version="1.0",
                description="active",
                path=plugin_path,
                loaded=True,
                runtime_path=os.path.join(tmp, "runtime"),
                registered_menu_actions=[{"label": "menu"}],
                registered_commands=["command"],
            )
            manager._plugins = [active]

            discovered = manager.discover_plugins()

            self.assertEqual(discovered[0].name, active.name)
            self.assertIs(manager.list_plugins()[0], active)
            self.assertEqual(active.registered_menu_actions, [{"label": "menu"}])
            self.assertEqual(active.registered_commands, ["command"])
            self.assertEqual(active.runtime_path, os.path.join(tmp, "runtime"))

    def test_rejected_plugin_is_not_executed_or_asked_again_this_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_path = os.path.join(tmp, "rejected_plugin.py")
            marker_path = os.path.join(tmp, "executed.txt")
            with open(plugin_path, "w", encoding="utf-8") as handle:
                handle.write(
                    f"open({marker_path!r}, 'w').write('ran')\n"
                    "PLUGIN_INFO = {'name': 'rejected'}\n"
                )

            manager = _TempPluginManager(tmp)
            confirm = Mock(return_value=False)
            context = PluginContext(confirm_plugin_load=confirm)

            first = manager.load_plugins(context)[0]
            second = manager.load_plugins(context)[0]

            self.assertFalse(first.loaded)
            self.assertFalse(second.loaded)
            self.assertEqual(first.error, _("플러그인 로드가 거부되었습니다."))
            self.assertFalse(os.path.exists(marker_path))
            confirm.assert_called_once_with("rejected_plugin")

    def test_trusted_hash_persists_and_changed_file_requires_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_path = os.path.join(tmp, "versioned_plugin.py")
            source = "PLUGIN_INFO = {'name': 'versioned'}\n"
            with open(plugin_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(source)

            first_manager = _TempPluginManager(tmp)
            first_approval = Mock(return_value=True)
            first = first_manager.load_plugins(
                PluginContext(confirm_plugin_load=first_approval)
            )[0]
            self.assertTrue(first.loaded)
            first_approval.assert_called_once_with("versioned_plugin")

            with open(first_manager._trusted_plugins_path(), "r", encoding="utf-8") as handle:
                stored = json.load(handle)
            self.assertEqual(
                stored["versioned_plugin.py"],
                hashlib.sha256(source.encode("utf-8")).hexdigest(),
            )

            trusted_manager = _TempPluginManager(tmp)
            no_prompt = Mock(return_value=False)
            trusted = trusted_manager.load_plugins(
                PluginContext(confirm_plugin_load=no_prompt)
            )[0]
            self.assertTrue(trusted.loaded)
            no_prompt.assert_not_called()

            changed_source = source + "# updated\n"
            with open(plugin_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(changed_source)
            changed_manager = _TempPluginManager(tmp)
            changed_approval = Mock(return_value=True)
            changed = changed_manager.load_plugins(
                PluginContext(confirm_plugin_load=changed_approval)
            )[0]
            self.assertTrue(changed.loaded)
            changed_approval.assert_called_once_with("versioned_plugin")

    def test_matching_bundled_plugin_is_trusted_without_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = os.path.join(tmp, "runtime")
            bundle_dir = os.path.join(tmp, "bundle")
            os.makedirs(runtime_dir)
            os.makedirs(bundle_dir)
            source = "PLUGIN_INFO = {'name': 'bundled'}\n"
            plugin_path = os.path.join(runtime_dir, "bundled_plugin.py")
            bundle_path = os.path.join(bundle_dir, "bundled_plugin.py")
            for path in (plugin_path, bundle_path):
                with open(path, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(source)

            manager = _TempPluginManager(runtime_dir)
            confirm = Mock(return_value=False)
            with patch(
                "core.resource_manager.ResourceManager.get_bundle_path",
                return_value=bundle_dir,
            ):
                plugin = manager.load_plugins(
                    PluginContext(confirm_plugin_load=confirm)
                )[0]

            self.assertTrue(plugin.loaded)
            confirm.assert_not_called()
            with open(manager._trusted_plugins_path(), "r", encoding="utf-8") as handle:
                stored = json.load(handle)
            self.assertEqual(
                stored["bundled_plugin.py"],
                hashlib.sha256(source.encode("utf-8")).hexdigest(),
            )

    def test_different_bundled_plugin_hash_requires_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = os.path.join(tmp, "runtime")
            bundle_dir = os.path.join(tmp, "bundle")
            os.makedirs(runtime_dir)
            os.makedirs(bundle_dir)
            plugin_path = os.path.join(runtime_dir, "modified_plugin.py")
            bundle_path = os.path.join(bundle_dir, "modified_plugin.py")
            with open(plugin_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("PLUGIN_INFO = {'name': 'modified'}\n")
            with open(bundle_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("PLUGIN_INFO = {'name': 'bundled'}\n")

            manager = _TempPluginManager(runtime_dir)
            confirm = Mock(return_value=True)
            with patch(
                "core.resource_manager.ResourceManager.get_bundle_path",
                return_value=bundle_dir,
            ):
                plugin = manager.load_plugins(
                    PluginContext(confirm_plugin_load=confirm)
                )[0]

            self.assertTrue(plugin.loaded)
            confirm.assert_called_once_with("modified_plugin")

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

    def test_register_tool_forwards_declared_intents(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_path = os.path.join(tmp, "intent_plugin.py")
            with open(plugin_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "PLUGIN_INFO = {'name': 'intent_plugin', 'api_version': '1.0'}\n"
                    "def register(context):\n"
                    "    def make_schema(name):\n"
                    "        return {'type': 'function', 'function': {'name': name, "
                    "'description': 'd', 'parameters': {'type': 'object', 'properties': {}}}}\n"
                    "    context.register_tool(make_schema('legacy_tool'), lambda args: 'ok')\n"
                    "    context.register_tool(make_schema('conversation_tool'), "
                    "lambda args: 'ok', intents=['conversation'])\n"
                    "    return {}\n"
                )

            registered_intents = []

            def _register_tool(schema, handler, intents=None):
                registered_intents.append(intents)

            manager = _TempPluginManager(tmp)
            plugin = manager.load_plugins(
                PluginContext(register_tool=_register_tool)
            )[0]

            self.assertTrue(plugin.loaded)
            self.assertEqual(registered_intents, [None, ["conversation"]])

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

    def test_load_plugin_serializes_concurrent_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_path = os.path.join(tmp, "first.py")
            second_path = os.path.join(tmp, "second.py")
            for path, name in ((first_path, "first"), (second_path, "second")):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(
                        f"PLUGIN_INFO = {{'name': '{name}', 'version': '1.0.0', 'api_version': '1.0'}}\n"
                    )

            manager = _TempPluginManager(tmp)
            counter_lock = threading.Lock()
            active_loads = 0
            max_concurrent = 0

            def fake_load_single(plugin, context):
                nonlocal active_loads, max_concurrent
                with counter_lock:
                    active_loads += 1
                    max_concurrent = max(max_concurrent, active_loads)
                time.sleep(0.05)
                plugin.loaded = True
                plugin.error = ""
                with counter_lock:
                    active_loads -= 1
                return plugin

            manager._load_single_plugin = fake_load_single

            threads = [
                threading.Thread(target=manager.load_plugin, args=(first_path, PluginContext())),
                threading.Thread(target=manager.load_plugin, args=(second_path, PluginContext())),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(max_concurrent, 1)
            self.assertEqual(sorted(plugin.name for plugin in manager.list_plugins()), ["first", "second"])

    def test_plugin_event_bus_emit_subscribe_and_unsubscribe(self):
        manager = _TempPluginManager(tempfile.mkdtemp())
        received = []

        unsubscribe = manager.subscribe_event("sample.event", received.append)
        manager.emit_event("sample.event", {"value": 1})
        unsubscribe()
        manager.emit_event("sample.event", {"value": 2})

        self.assertEqual(received, [{"value": 1}])

    def test_plugin_context_exposes_event_bus(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_path = os.path.join(tmp, "event_plugin.py")
            with open(plugin_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "PLUGIN_INFO = {'name': 'eventer', 'version': '1.0.0', 'api_version': '1.0'}\n"
                    "def register(context):\n"
                    "    seen = []\n"
                    "    context.subscribe_event('ping', seen.append)\n"
                    "    context.emit_event('ready', {'ok': True})\n"
                    "    return {'seen': seen}\n"
                )

            manager = _TempPluginManager(tmp)
            ready = []
            manager.subscribe_event("ready", ready.append)
            plugin = manager.load_plugins(PluginContext())[0]
            manager.emit_event("ping", {"n": 1})

            self.assertEqual(ready, [{"ok": True}])
            self.assertEqual(plugin.exports["seen"], [{"n": 1}])


if __name__ == "__main__":
    unittest.main()

import os
import sys
import tempfile
import unittest


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
                    "PLUGIN_INFO = {'name': 'hello', 'version': '1.2.0', 'description': '테스트 플러그인'}\n"
                    "def register(context):\n"
                    "    return {'has_app': bool(context.app)}\n"
                )

            manager = _TempPluginManager(tmp)
            plugins = manager.load_plugins(PluginContext(app=object()))

            self.assertEqual(len(plugins), 1)
            self.assertTrue(plugins[0].loaded)
            self.assertEqual(plugins[0].name, "hello")
            self.assertEqual(plugins[0].exports["has_app"], True)


if __name__ == "__main__":
    unittest.main()

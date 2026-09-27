import ast
import os
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


MAIN_PATH = Path(__file__).resolve().parents[1] / "Main.py"


def _load_main_function(function_name, namespace):
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(module, str(MAIN_PATH), "exec"), namespace)
    return namespace[function_name]


class _Signal:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback

    def emit(self):
        self.callback()


class MainStartupTests(unittest.TestCase):
    def test_optional_startup_failures_do_not_prevent_event_loop(self):
        instances = {}

        class FakeApp:
            def __init__(self, _argv):
                instances["app"] = self
                self.exec_count = 0

            def setWindowIcon(self, _icon):
                pass

            def exec(self):
                self.exec_count += 1
                instances["voice_thread"].microphone_available = False
                instances["voice_thread"].microphone_unavailable.emit()
                return 0

        class FakeCharacter:
            def __init__(self):
                self.messages = []
                instances["character"] = self

            def say(self, text):
                self.messages.append(text)

            def cleanup(self):
                pass

            def close(self):
                pass

        class FakeVoiceThread:
            def __init__(self):
                self.microphone_available = None
                self.microphone_unavailable = _Signal()
                self.notification_claimed = False
                instances["voice_thread"] = self

            def claim_microphone_unavailable_notification(self):
                if self.notification_claimed:
                    return False
                self.notification_claimed = True
                return True

        class FakeAriCore:
            def __init__(self):
                self.voice_thread = FakeVoiceThread()

            def cleanup(self):
                pass

        logger = Mock()
        namespace = {
            "sys": SimpleNamespace(argv=[], platform="linux"),
            "os": os,
            "logging": logger,
            "datetime": datetime,
            "QApplication": FakeApp,
            "QSystemTrayIcon": SimpleNamespace(isSystemTrayAvailable=lambda: False),
            "QIcon": Mock(),
            "get_ai_assistant": Mock(return_value=object()),
            "set_ai_assistant": Mock(),
            "start_performance_warmups": Mock(),
            "check_cosyvoice_first_run": Mock(side_effect=PermissionError("config is read-only")),
            "_resolve_icon_path": Mock(return_value=None),
            "AriCore": FakeAriCore,
            "start_tts_background": Mock(side_effect=TypeError("provider init failed")),
            "tts_wrapper": Mock(),
            "get_scheduler": Mock(side_effect=PermissionError("scheduler storage unavailable")),
            "register_background_learning_tasks": Mock(),
            "CharacterWidget": FakeCharacter,
            "set_character_widget": Mock(),
            "create_text_interface": Mock(side_effect=RuntimeError("text UI init failed")),
            "on_language_changed": Mock(),
            "_state": SimpleNamespace(command_registry=None),
            "AICommand": type("AICommand", (), {}),
            "get_plugin_manager": Mock(side_effect=PermissionError("plugin folder is read-only")),
            "PluginContext": object,
            "flush_runtime_state": Mock(),
            "setup_logging": Mock(),
            "icon_path": None,
            "ai_assistant": None,
            "tray_icon": None,
            "plugin_watcher": None,
            "plugin_flush_timer": None,
            "telegram_bridge": None,
            "mcp_server_thread": None,
            "_": lambda text: text,
        }
        main = _load_main_function("main", namespace)

        with (
            patch("audio.audio_manager.initialize_global_audio", return_value=False),
            patch("core.config_manager.ConfigManager.get", return_value=False),
        ):
            main()

        self.assertIn("app", instances)
        self.assertEqual(instances["app"].exec_count, 1)
        self.assertEqual(
            instances["character"].messages,
            ["마이크를 찾을 수 없어 음성 인식을 사용할 수 없습니다. 설정에서 마이크를 지정해 주세요."],
        )
        self.assertIs(instances["character"].voice_thread, instances["voice_thread"])
        self.assertTrue(instances["voice_thread"].notification_claimed)

    def test_logging_permission_failure_keeps_console_free_startup(self):
        handlers = []

        class FakeRoot:
            def __init__(self):
                self.handlers = []

            def removeHandler(self, handler):
                self.handlers.remove(handler)

        class FakeLogging:
            INFO = 20
            root = FakeRoot()

            def basicConfig(self, **kwargs):
                handlers.extend(kwargs["handlers"])

            def NullHandler(self):
                return object()

            def warning(self, *_args):
                pass

        setup_logging = _load_main_function(
            "setup_logging",
            {
                "logging": FakeLogging(),
                "sys": SimpleNamespace(stdout=None),
                "os": os,
                "datetime": datetime,
                "_cleanup_old_logs": Mock(),
            },
        )

        with patch(
            "core.resource_manager.ResourceManager.get_writable_path",
            side_effect=PermissionError("logs directory is read-only"),
        ):
            setup_logging()

        self.assertEqual(len(handlers), 1)


if __name__ == "__main__":
    unittest.main()

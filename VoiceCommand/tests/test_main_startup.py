import ast
import os
import types
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
    # Main.py는 가져오기만 해도 앱 초기화가 일어나므로, 대상 함수만 컴파일해 격리된 전역으로 만든다.
    module = ast.Module(body=[function], type_ignores=[])
    module_code = compile(module, str(MAIN_PATH), "exec")
    function_code = next(
        const for const in module_code.co_consts
        if isinstance(const, types.CodeType) and const.co_name == function_name
    )
    return types.FunctionType(function_code, namespace, function_name)


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
                self.show_count = 0
                self.raise_count = 0
                instances["character"] = self

            def say(self, text):
                self.messages.append(text)

            def show(self):
                self.show_count += 1

            def raise_(self):
                self.raise_count += 1

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
        ensure_single_instance = Mock(return_value=True)
        start_single_instance_server = Mock()
        namespace = {
            "sys": SimpleNamespace(argv=[], platform="linux"),
            "os": os,
            "logging": logger,
            "datetime": datetime,
            "ensure_single_instance": ensure_single_instance,
            "start_single_instance_server": start_single_instance_server,
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
            "record_last_run_version": Mock(return_value=True),
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
        ensure_single_instance.assert_called_once()
        start_single_instance_server.assert_called_once()
        self.assertEqual(instances["app"].exec_count, 1)
        namespace["record_last_run_version"].assert_called_once_with()
        self.assertEqual(
            instances["character"].messages,
            ["마이크를 찾을 수 없어 음성 인식을 사용할 수 없습니다. 설정에서 마이크를 지정해 주세요."],
        )
        self.assertIs(instances["character"].voice_thread, instances["voice_thread"])
        self.assertTrue(instances["voice_thread"].notification_claimed)
        start_single_instance_server.call_args.args[0]()
        self.assertEqual(instances["character"].show_count, 1)
        self.assertEqual(instances["character"].raise_count, 1)

    def test_duplicate_instance_returns_before_creating_qt_app(self):
        ensure_single_instance = Mock(return_value=False)
        setup_logging = Mock()
        flush_runtime_state = Mock()
        main = _load_main_function(
            "main",
            {
                "sys": SimpleNamespace(argv=["Main.py"]),
                "ensure_single_instance": ensure_single_instance,
                "setup_logging": setup_logging,
                "flush_runtime_state": flush_runtime_state,
                "logging": Mock(),
            },
        )

        main()

        ensure_single_instance.assert_called_once()
        setup_logging.assert_not_called()
        flush_runtime_state.assert_not_called()

    def test_version_dispatch_is_before_gui_imports(self):
        tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
        dispatch_line = next(
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "dispatch_version_command"
        )
        gui_import_line = next(
            node.lineno
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module == "PySide6.QtWidgets"
        )
        self.assertLess(dispatch_line, gui_import_line)

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

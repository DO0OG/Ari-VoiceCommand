import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ui.global_hotkey import GlobalVoiceHotkey, parse_global_hotkey


class GlobalHotkeyTests(unittest.TestCase):
    def test_parse_default_shortcut(self):
        self.assertEqual(parse_global_hotkey("Ctrl+Alt+Space"), (3, 0x20))

    def test_parse_function_key_and_reject_unmodified_key(self):
        self.assertEqual(parse_global_hotkey("Shift+F12"), (4, 0x7B))
        with self.assertRaises(ValueError):
            parse_global_hotkey("Space")

    def test_failed_registration_is_logged_and_does_not_raise(self):
        api = Mock()
        api.RegisterHotKey.return_value = False
        hotkey = GlobalVoiceHotkey(Mock(), api=api, platform="win32")

        with (
            patch(
                "ui.global_hotkey.ConfigManager.load_settings",
                return_value={"voice_activation_hotkey": "Ctrl+Alt+Space"},
            ),
            patch("ui.global_hotkey.logging.warning") as warning,
        ):
            self.assertFalse(hotkey.configure())

        warning.assert_called_once()
        api.UnregisterHotKey.assert_not_called()

    def test_native_event_filter_dispatches_registered_hotkey(self):
        voice_thread = Mock()
        hotkey = GlobalVoiceHotkey(voice_thread, api=Mock(), platform="win32")
        hotkey._registered_id = 0xA191
        hotkey._mode = "toggle"
        message = SimpleNamespace(message=0x0312, wParam=0xA191)

        with patch(
            "ui.global_hotkey.ctypes.cast",
            return_value=SimpleNamespace(contents=message),
        ):
            result = hotkey.nativeEventFilter(b"windows_dispatcher_MSG", 1)

        self.assertEqual(result, (True, 0))
        voice_thread.request_listening.assert_called_once_with()

    def test_reconfigure_registers_new_binding_before_removing_old_one(self):
        api = Mock()
        api.RegisterHotKey.return_value = True
        voice_thread = Mock()
        hotkey = GlobalVoiceHotkey(voice_thread, api=api, platform="win32")
        settings = [
            {
                "voice_activation_hotkey": "Ctrl+Alt+Space",
                "voice_activation_mode": "toggle",
            },
            {
                "voice_activation_hotkey": "Ctrl+Shift+F4",
                "voice_activation_mode": "toggle",
            },
            {
                "voice_activation_hotkey": "Alt+F8",
                "voice_activation_mode": "toggle",
            },
        ]

        with patch("ui.global_hotkey.ConfigManager.load_settings", side_effect=settings):
            self.assertTrue(hotkey.configure())
            self.assertTrue(hotkey.configure())
            self.assertTrue(hotkey.configure())
            hotkey.cleanup()

        self.assertEqual(
            [call.args[1] for call in api.RegisterHotKey.call_args_list],
            [0xA191, 0xA192, 0xA191],
        )
        self.assertEqual(
            [call.args[1] for call in api.UnregisterHotKey.call_args_list],
            [0xA191, 0xA192, 0xA191],
        )


if __name__ == "__main__":
    unittest.main()

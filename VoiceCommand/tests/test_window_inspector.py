import ctypes
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core import window_inspector


class WindowInspectorTests(unittest.TestCase):
    def test_fullscreen_is_unknown_off_windows(self):
        with patch.object(window_inspector.sys, "platform", "linux"):
            self.assertIsNone(window_inspector.get_foreground_fullscreen())

    def test_fullscreen_uses_monitor_and_window_bounds(self):
        user32 = SimpleNamespace()
        user32.GetForegroundWindow = Mock(return_value=0x100000001)
        user32.MonitorFromWindow = Mock(return_value=0x200000001)

        def set_window_rect(hwnd, rect_pointer):
            rect = ctypes.cast(
                rect_pointer, ctypes.POINTER(window_inspector._WindowRect)
            ).contents
            rect.left, rect.top, rect.right, rect.bottom = 0, 0, 1920, 1080
            return 1

        def set_monitor_info(monitor, info_pointer):
            info = ctypes.cast(
                info_pointer, ctypes.POINTER(window_inspector._MonitorInfo)
            ).contents
            info.rcMonitor.left = 0
            info.rcMonitor.top = 0
            info.rcMonitor.right = 1920
            info.rcMonitor.bottom = 1080
            return 1

        user32.GetWindowRect = Mock(side_effect=set_window_rect)
        user32.GetMonitorInfoW = Mock(side_effect=set_monitor_info)
        with patch.object(window_inspector.sys, "platform", "win32"), patch.object(
            window_inspector, "_dll", lambda _name: user32
        ):
            self.assertIs(window_inspector.get_foreground_fullscreen(), True)

        self.assertIs(user32.GetForegroundWindow.restype, ctypes.c_void_p)
        self.assertIs(user32.MonitorFromWindow.restype, ctypes.c_void_p)

    @unittest.skipUnless(sys.platform == "win32", "Windows 전용")
    def test_helpers_do_not_change_shared_windll_prototypes(self):
        shared = ctypes.windll.user32.GetWindowRect
        before = shared.argtypes
        window_inspector.get_foreground_window_rect()
        window_inspector.get_foreground_fullscreen()
        self.assertIs(shared.argtypes, before)


if __name__ == "__main__":
    unittest.main()

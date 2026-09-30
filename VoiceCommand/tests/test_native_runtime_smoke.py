import _ctypes
import ctypes
import os
import sys
import threading
import unittest
from ctypes import wintypes
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from core import window_inspector
from core.activity_monitor import ActivityMonitor, _SessionNativeEventFilter
from core.exception_logging import get_error_count
from ui.global_hotkey import GlobalVoiceHotkey


@unittest.skipUnless(sys.platform == "win32", "Windows API 실경로")
class NativeRuntimeSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def test_session_filter_handles_real_message_structure(self):
        monitor = Mock()
        native_filter = _SessionNativeEventFilter(monitor, 0x1234)
        message = wintypes.MSG()
        message.hWnd = 0x1234
        message.message = 0x0400
        message.wParam = 0
        pointer = ctypes.addressof(message)

        self.assertEqual(
            native_filter.nativeEventFilter(b"windows_generic_MSG", pointer),
            (False, 0),
        )
        monitor.handle_session_change.assert_not_called()

        message.message = 0x02B1
        message.wParam = 7
        self.assertEqual(
            native_filter.nativeEventFilter(b"windows_dispatcher_MSG", pointer),
            (False, 0),
        )
        monitor.handle_session_change.assert_called_once_with(7)

    def test_window_inspector_uses_real_windows_apis(self):
        idle_seconds = window_inspector.get_idle_seconds()
        self.assertIsInstance(idle_seconds, int)
        self.assertGreaterEqual(idle_seconds, 0)
        window_inspector.get_session_locked()
        window_inspector.get_foreground_app_category()
        window_inspector.get_foreground_window_rect()
        window_inspector.is_taskbar_hidden()
        window_inspector.get_quiet_reason()

    def test_global_hotkey_accepts_real_message_structure(self):
        hotkey = GlobalVoiceHotkey(Mock(), api=Mock(), platform="win32")
        hotkey._registered_id = 0xA191
        hotkey._mode = "toggle"
        message = wintypes.MSG()
        message.message = 0x0312
        message.wParam = hotkey._registered_id

        with patch("VoiceCommand.is_tts_playing", return_value=False):
            result = hotkey.nativeEventFilter(
                b"windows_dispatcher_MSG", ctypes.addressof(message)
            )

        self.assertEqual(result, (True, 0))
        hotkey.voice_thread.request_listening.assert_called_once_with()

    def test_activity_monitor_starts_polls_and_stops_with_real_apis(self):
        monitor = ActivityMonitor(api=window_inspector)
        error_count = get_error_count()
        try:
            self.assertTrue(monitor.start())
            monitor._refresh_display_state()
            monitor._check_idle()
            monitor._check_quiet()
            monitor._check_ide_long_use()
        finally:
            monitor.stop()

        self.assertEqual(get_error_count(), error_count)

    def test_volume_adjusts_from_worker_thread(self):
        from pycaw.pycaw import AudioUtilities

        from core.VoiceCommand import adjust_volume

        try:
            AudioUtilities.GetSpeakers().EndpointVolume.GetMasterVolumeLevelScalar()
        except _ctypes.COMError as exc:
            # E_NOTFOUND: 기본 출력 장치가 없는 CI 러너
            if exc.hresult != -2147023728:
                raise
            self.skipTest(f"스피커 장치 없음: {exc}")

        results = []
        worker = threading.Thread(
            target=lambda: results.append(adjust_volume(0, announce=False))
        )
        worker.start()
        worker.join(10)

        self.assertEqual(results, [True])


if __name__ == "__main__":
    unittest.main()

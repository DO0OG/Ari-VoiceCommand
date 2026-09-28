"""활성 창 정보 조회 유틸리티."""
from __future__ import annotations

import ctypes
import sys
from typing import Optional


class _WindowRect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", _WindowRect),
        ("rcWork", _WindowRect),
        ("dwFlags", ctypes.c_ulong),
    ]


def get_foreground_window_title() -> str:
    """현재 활성 창 제목을 소문자로 반환한다."""
    if sys.platform != "win32":
        return ""
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value.lower()
    except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError):
        return ""


def get_foreground_process_name() -> str:
    """현재 활성 창 프로세스 이름을 소문자로 반환한다."""
    if sys.platform != "win32":
        return ""
    try:
        import psutil
    except ImportError:
        return ""
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return psutil.Process(pid.value).name().lower()
    except (
        psutil.Error,
        AttributeError,
        OSError,
        TypeError,
        ValueError,
        ctypes.ArgumentError,
    ):
        return ""


def get_foreground_fullscreen() -> Optional[bool]:
    """전경 창이 모니터 전체를 덮는지 반환한다. 판정할 수 없으면 None이다."""
    if sys.platform != "win32":
        return None
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.MonitorFromWindow.restype = ctypes.c_void_p
        user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_WindowRect)]
        user32.GetWindowRect.restype = ctypes.c_int
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MonitorInfo)]
        user32.GetMonitorInfoW.restype = ctypes.c_int
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        window_rect = _WindowRect()
        monitor_info = _MonitorInfo()
        monitor_info.cbSize = ctypes.sizeof(_MonitorInfo)
        monitor = user32.MonitorFromWindow(hwnd, 2)
        if not monitor or not user32.GetWindowRect(hwnd, ctypes.byref(window_rect)):
            return None
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
            return None

        bounds = monitor_info.rcMonitor
        return (
            window_rect.left <= bounds.left
            and window_rect.top <= bounds.top
            and window_rect.right >= bounds.right
            and window_rect.bottom >= bounds.bottom
        )
    except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError):
        return None

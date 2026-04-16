"""활성 창 정보 조회 유틸리티."""
from __future__ import annotations

import sys


def get_foreground_window_title() -> str:
    """현재 활성 창 제목을 소문자로 반환한다."""
    if sys.platform != "win32":
        return ""
    try:
        import ctypes

        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value.lower()
    except Exception:
        return ""


def get_foreground_process_name() -> str:
    """현재 활성 창 프로세스 이름을 소문자로 반환한다."""
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        import psutil

        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return psutil.Process(pid.value).name().lower()
    except Exception:
        return ""

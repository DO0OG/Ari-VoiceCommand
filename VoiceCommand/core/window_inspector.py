"""활성 창 정보 조회 유틸리티."""
from __future__ import annotations

import ctypes
import functools
import sys
from ctypes import wintypes
from typing import Optional



@functools.lru_cache(maxsize=None)
def _dll(name: str):
    """이 모듈 전용 DLL 핸들을 반환한다.

    공유 ctypes.windll 함수의 argtypes를 바꾸면 pygetwindow 같은 다른 호출이 깨진다.
    """
    return ctypes.WinDLL(name)

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
        hwnd = _dll("user32").GetForegroundWindow()
        if not hwnd:
            return ""
        length = _dll("user32").GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        _dll("user32").GetWindowTextW(hwnd, buf, length + 1)
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
        hwnd = _dll("user32").GetForegroundWindow()
        if not hwnd:
            return ""
        pid = ctypes.c_ulong()
        _dll("user32").GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
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
        user32 = _dll("user32")
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


_APP_CATEGORIES = {
    "ide": {"code.exe", "devenv.exe", "pycharm64.exe", "idea64.exe", "rider64.exe"},
    "browser": {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"},
    "game": {
        "cs2.exe",
        "dota2.exe",
        "eldenring.exe",
        "fortniteclient-win64-shipping.exe",
        "gta5.exe",
        "overwatch.exe",
        "robloxplayerbeta.exe",
        "valorant-win64-shipping.exe",
    },
    "video": {"vlc.exe", "mpv.exe", "potplayer.exe", "potplayermini64.exe", "mpc-hc64.exe"},
    "office": {"winword.exe", "excel.exe", "powerpnt.exe", "onenote.exe"},
    "chat": {
        "discord.exe",
        "kakaotalk.exe",
        "slack.exe",
        "teams.exe",
        "zoom.exe",
    },
}


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def get_idle_seconds() -> int | None:
    """마지막 입력 이후 초를 반환한다."""
    if sys.platform != "win32":
        return None
    info = _LastInputInfo(ctypes.sizeof(_LastInputInfo), 0)
    user32 = _dll("user32")
    user32.GetLastInputInfo.argtypes = (ctypes.POINTER(_LastInputInfo),)
    user32.GetLastInputInfo.restype = wintypes.BOOL
    user32.GetTickCount.restype = wintypes.DWORD
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    elapsed_ms = (user32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    return elapsed_ms // 1000


def get_session_locked() -> bool | None:
    """현재 입력 데스크톱이 잠금 화면인지 확인한다."""
    if sys.platform != "win32":
        return False
    user32 = _dll("user32")
    user32.OpenInputDesktop.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    desktop = user32.OpenInputDesktop(0, False, 0x0001)
    if not desktop:
        return None

    try:
        required = wintypes.DWORD()
        user32.GetUserObjectInformationW.argtypes = (
            wintypes.HANDLE,
            wintypes.INT,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        )
        user32.GetUserObjectInformationW.restype = wintypes.BOOL
        user32.GetUserObjectInformationW(desktop, 2, None, 0, ctypes.byref(required))
        if required.value == 0:
            return None
        name = ctypes.create_unicode_buffer(required.value)
        if not user32.GetUserObjectInformationW(
            desktop,
            2,
            name,
            ctypes.sizeof(name),
            ctypes.byref(required),
        ):
            return None
        return name.value.casefold() != "default"
    finally:
        user32.CloseDesktop.argtypes = (wintypes.HANDLE,)
        user32.CloseDesktop.restype = wintypes.BOOL
        user32.CloseDesktop(desktop)


def get_foreground_app_category() -> str | None:
    """활성 앱을 고정된 카테고리로만 반환한다."""
    if sys.platform != "win32":
        return None
    user32 = _dll("user32")
    user32.GetForegroundWindow.restype = wintypes.HWND
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    )
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    if not process_id.value:
        return None
    try:
        import psutil
    except ImportError:
        return None
    try:
        process_name = psutil.Process(process_id.value).name().lower()
    except (psutil.Error, OSError, ValueError):
        return None
    return next(
        (category for category, names in _APP_CATEGORIES.items() if process_name in names),
        "other",
    )


def get_foreground_window_rect() -> tuple[int, int, int, int] | None:
    """활성 창의 사각형을 반환한다."""
    if sys.platform != "win32":
        return None
    user32 = _dll("user32")
    user32.GetForegroundWindow.restype = wintypes.HWND
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    # get_foreground_fullscreen과 같은 프로토타입을 써야 호출 순서에 따라 깨지지 않는다.
    rect = _WindowRect()
    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_WindowRect)]
    user32.GetWindowRect.restype = ctypes.c_int
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def foreground_covers_screen(width: int, height: int) -> bool:
    """활성 창이 화면 크기와 거의 같은지 확인한다."""
    rect = get_foreground_window_rect()
    return rect_covers_screen(rect, width, height)


def rect_covers_screen(
    rect: tuple[int, int, int, int] | None, width: int, height: int
) -> bool:
    if rect is None:
        return False
    left, top, right, bottom = rect
    return right - left >= width - 5 and bottom - top >= height - 5


def is_taskbar_hidden() -> bool:
    if sys.platform != "win32":
        return False
    user32 = _dll("user32")
    find_window = user32.FindWindowW
    find_window.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    find_window.restype = wintypes.HWND
    taskbar = find_window("Shell_TrayWnd", None)
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL
    return bool(taskbar and not user32.IsWindowVisible(taskbar))


def get_quiet_reason() -> str | None:
    """Windows 알림 상태를 조용한 상태 카테고리로 반환한다."""
    if sys.platform != "win32":
        return None
    state = wintypes.DWORD()
    shell32 = _dll("shell32")
    shell32.SHQueryUserNotificationState.argtypes = (ctypes.POINTER(wintypes.DWORD),)
    shell32.SHQueryUserNotificationState.restype = ctypes.c_long
    result = shell32.SHQueryUserNotificationState(ctypes.byref(state))
    if result != 0:
        return None
    return {
        2: "focus_assist",
        3: "fullscreen",
        4: "presentation",
        6: "focus_assist",
    }.get(state.value, "none")


def register_session_notifications(hwnd: int) -> bool:
    """현재 세션의 잠금·해제 알림을 등록한다."""
    if sys.platform != "win32":
        return False
    wtsapi32 = _dll("wtsapi32")
    wtsapi32.WTSRegisterSessionNotification.argtypes = (wintypes.HWND, wintypes.DWORD)
    wtsapi32.WTSRegisterSessionNotification.restype = wintypes.BOOL
    return bool(wtsapi32.WTSRegisterSessionNotification(hwnd, 0))


def unregister_session_notifications(hwnd: int) -> None:
    """현재 세션 알림 등록을 해제한다."""
    if sys.platform == "win32":
        wtsapi32 = _dll("wtsapi32")
        wtsapi32.WTSUnRegisterSessionNotification.argtypes = (wintypes.HWND,)
        wtsapi32.WTSUnRegisterSessionNotification.restype = wintypes.BOOL
        wtsapi32.WTSUnRegisterSessionNotification(hwnd)


def install_foreground_hook(callback):
    """전경 창 변경 훅과 네이티브 콜백을 반환한다."""
    if sys.platform != "win32":
        return None, None
    callback_type = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
        None,
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.HWND,
        wintypes.LONG,
        wintypes.LONG,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    native_callback = callback_type(lambda *_args: callback())
    user32 = _dll("user32")
    user32.SetWinEventHook.argtypes = (
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HMODULE,
        callback_type,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    user32.SetWinEventHook.restype = wintypes.HANDLE
    hook = user32.SetWinEventHook(
        3,
        3,
        None,
        native_callback,
        0,
        0,
        0,
    )
    return hook or None, native_callback


def remove_foreground_hook(hook) -> None:
    """전경 창 변경 훅을 해제한다."""
    if sys.platform == "win32" and hook:
        user32 = _dll("user32")
        user32.UnhookWinEvent.argtypes = (wintypes.HANDLE,)
        user32.UnhookWinEvent.restype = wintypes.BOOL
        user32.UnhookWinEvent(hook)

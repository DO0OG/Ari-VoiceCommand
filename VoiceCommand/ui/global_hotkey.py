"""Windows 전역 음성 입력 단축키."""

import ctypes
import logging
import re
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QTimer

from core.config_manager import ConfigManager
from core.exception_logging import log_exception


_MODIFIER_FLAGS = {
    "ctrl": 0x0002,
    "control": 0x0002,
    "alt": 0x0001,
    "shift": 0x0004,
    "meta": 0x0008,
    "win": 0x0008,
    "windows": 0x0008,
}
_KEYS = {
    "space": 0x20,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "insert": 0x2D,
    "ins": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pgup": 0x21,
    "pagedown": 0x22,
    "pgdown": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
    ";": 0xBA,
    "'": 0xDE,
    "[": 0xDB,
    "]": 0xDD,
    "\\": 0xDC,
    "-": 0xBD,
    "=": 0xBB,
    "`": 0xC0,
}
_HOTKEY_ID = 0xA191
_WM_HOTKEY = 0x0312
_MOD_NOREPEAT = 0x4000


def parse_global_hotkey(sequence: str) -> tuple[int, int]:
    """단축키 문자열에서 Win32 수정 키와 키 코드를 얻는다."""
    parts = [part.strip() for part in str(sequence).split("+") if part.strip()]
    if len(parts) < 2:
        raise ValueError("modifier and key required")

    modifiers = 0
    for modifier in parts[:-1]:
        flag = _MODIFIER_FLAGS.get(modifier.casefold())
        if flag is None or modifiers & flag:
            raise ValueError("invalid modifier")
        modifiers |= flag
    if not modifiers:
        raise ValueError("modifier required")

    token = parts[-1].casefold()
    key = _KEYS.get(token)
    if key is None and len(token) == 1 and token.isascii() and token.isalnum():
        key = ord(token.upper())
    if key is None:
        match = re.fullmatch(r"f(\d{1,2})", token)
        if match:
            number = int(match.group(1))
            if 1 <= number <= 24:
                key = 0x70 + number - 1
    if key is None:
        raise ValueError("unsupported key")
    return modifiers, key


class GlobalVoiceHotkey(QAbstractNativeEventFilter):
    """Qt 네이티브 이벤트 필터로 Win32 전역 단축키를 받는다."""

    def __init__(self, voice_thread, api=None, platform=None):
        super().__init__()
        self.voice_thread = voice_thread
        self._api = api
        self._platform = platform or sys.platform
        self._app = None
        self._filter_installed = False
        self._registered_id = None
        self._registered_sequence = None
        self._registered_key = None
        self._next_id = _HOTKEY_ID
        self._mode = "push_to_talk"
        self._holding = False
        self._timer = QTimer()
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._check_key_release)

    def install(self, app) -> bool:
        """필터와 단축키를 설치한다."""
        if self._platform != "win32":
            return False
        self._app = app
        app.installNativeEventFilter(self)
        self._filter_installed = True
        self.configure()
        return True

    def _user32(self):
        if self._api is None:
            self._api = ctypes.WinDLL("user32", use_last_error=True)
            self._api.RegisterHotKey.argtypes = [
                wintypes.HWND,
                wintypes.INT,
                wintypes.UINT,
                wintypes.UINT,
            ]
            self._api.RegisterHotKey.restype = wintypes.BOOL
            self._api.UnregisterHotKey.argtypes = [wintypes.HWND, wintypes.INT]
            self._api.UnregisterHotKey.restype = wintypes.BOOL
            self._api.GetAsyncKeyState.argtypes = [wintypes.INT]
            self._api.GetAsyncKeyState.restype = wintypes.SHORT
        return self._api

    def configure(self) -> bool:
        """저장된 단축키 설정을 적용한다."""
        settings = ConfigManager.load_settings()
        sequence = str(settings.get("voice_activation_hotkey", "Ctrl+Alt+Space"))
        mode = settings.get("voice_activation_mode", "push_to_talk")
        if self._holding and (sequence != self._registered_sequence or mode != self._mode):
            self._timer.stop()
            self.voice_thread.release_listening()
            self._holding = False
        self._mode = mode
        if sequence == self._registered_sequence:
            return True
        if self._platform != "win32":
            return False

        try:
            modifiers, key = parse_global_hotkey(sequence)
        except ValueError as exc:
            logging.warning("전역 단축키 설정이 올바르지 않습니다: %s", exc)
            return False

        api = self._user32()
        hotkey_id = self._next_id
        if not api.RegisterHotKey(None, hotkey_id, modifiers | _MOD_NOREPEAT, key):
            get_last_error = getattr(ctypes, "get_last_error", lambda: 0)
            logging.warning(
                "전역 단축키 등록 실패 (다른 앱이 사용 중일 수 있습니다, 오류 %d)",
                get_last_error(),
            )
            return False

        previous_id = self._registered_id
        self._registered_id = hotkey_id
        self._registered_sequence = sequence
        self._registered_key = key
        self._next_id = _HOTKEY_ID if hotkey_id != _HOTKEY_ID else _HOTKEY_ID + 1
        if previous_id is not None:
            api.UnregisterHotKey(None, previous_id)
        return True

    def nativeEventFilter(self, event_type, message):
        """WM_HOTKEY만 처리한다."""
        try:
            native_type = (
                event_type.encode("ascii", "ignore")
                if isinstance(event_type, str)
                else bytes(event_type)
            )
            if self._registered_id is None or native_type not in (
                b"windows_generic_MSG",
                b"windows_dispatcher_MSG",
            ):
                return False, 0
            native_message = ctypes.cast(
                int(message), ctypes.POINTER(wintypes.MSG)
            ).contents
            if (
                native_message.message != _WM_HOTKEY
                or native_message.wParam != self._registered_id
            ):
                return False, 0

            try:
                from VoiceCommand import is_tts_playing, stop_speaking
                if is_tts_playing():
                    stop_speaking()
            except (ImportError, AttributeError, RuntimeError) as exc:
                logging.debug("TTS 중단 처리 생략: %s", exc)

            if self._mode == "push_to_talk":
                self._holding = self.voice_thread.request_listening(push_to_talk=True)
                if self._holding:
                    self._timer.start()
            else:
                self.voice_thread.request_listening()
            return True, 0
        except Exception:
            # 네이티브 이벤트 콜백에서 예외가 새면 앱이 종료될 수 있다.
            log_exception("전역 단축키 네이티브 이벤트 처리 실패")
            return False, 0

    def _check_key_release(self) -> None:
        if not self._holding or self._registered_key is None:
            self._timer.stop()
            return
        if not self._user32().GetAsyncKeyState(self._registered_key) & 0x8000:
            self._timer.stop()
            self._holding = False
            self.voice_thread.release_listening()

    def cleanup(self) -> None:
        """단축키와 네이티브 필터를 해제한다."""
        self._timer.stop()
        if self._holding:
            self.voice_thread.release_listening()
            self._holding = False
        if self._registered_id is not None and self._api is not None:
            self._api.UnregisterHotKey(None, self._registered_id)
            self._registered_id = None
        if self._filter_installed and self._app is not None:
            self._app.removeNativeEventFilter(self)
            self._filter_installed = False

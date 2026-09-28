"""Windows 사용자 활동을 감지해 카테고리 이벤트만 발행한다."""
from __future__ import annotations

import ctypes
import logging
import sys
import time
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, QTimer, Signal
from PySide6.QtWidgets import QWidget

from core import window_inspector
from core.config_manager import ConfigManager


_WTS_SESSION_LOCK = 0x7
_WTS_SESSION_UNLOCK = 0x8
_APP_CATEGORIES = {"ide", "browser", "game", "video", "office", "chat", "other"}
_active_monitor = None


class _SessionNativeEventFilter(QAbstractNativeEventFilter):
    def __init__(self, monitor, hwnd: int):
        super().__init__()
        self._monitor = monitor
        self._hwnd = hwnd

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0
        native_message = ctypes.cast(
            int(message), ctypes.POINTER(wintypes.MSG)
        ).contents
        if native_message.hwnd != self._hwnd or native_message.message != 0x02B1:
            return False, 0
        self._monitor.handle_session_change(int(native_message.wParam))
        return False, 0


class ActivityMonitor(QObject):
    user_away = Signal(int)
    user_returned = Signal(int)
    session_locked = Signal()
    session_unlocked = Signal()
    quiet_state_changed = Signal(str)
    foreground_category_changed = Signal(str)
    ide_long_use_due = Signal(int)
    settings_refreshed = Signal()

    def __init__(
        self,
        parent=None,
        *,
        api=window_inspector,
        settings_provider: Callable[[], dict] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        super().__init__(parent)
        self._api = api
        self._settings_provider = settings_provider or self._load_settings
        self._clock = clock
        self._away_started_at = None
        self._category = None
        self._category_changed_at = clock()
        self._ide_active_started_at = None
        self._category_enabled = False
        self._quiet_reason = "none"
        self._session_locked = False
        self._wts_session_locked = False
        self._foreground_rect = None
        self._taskbar_hidden = False
        self._started = False
        self._lock_notifications_available = sys.platform != "win32"
        self._notification_window = None
        self._notification_hwnd = None
        self._native_filter = None
        self._foreground_hook = None
        self._native_callback = None

        self._idle_timer = QTimer(self)
        self._idle_timer.timeout.connect(self._check_idle)
        self._quiet_timer = QTimer(self)
        self._quiet_timer.timeout.connect(self._check_quiet)
        self._display_timer = QTimer(self)
        self._display_timer.timeout.connect(self._refresh_display_state)
        self._ide_long_use_timer = QTimer(self)
        self._ide_long_use_timer.timeout.connect(self._check_ide_long_use)

        global _active_monitor
        _active_monitor = self

    @staticmethod
    def _load_settings() -> dict:
        return ConfigManager.load_settings()

    @property
    def lock_notifications_available(self) -> bool:
        return self._lock_notifications_available

    @property
    def session_is_locked(self) -> bool:
        return self._session_locked

    @property
    def is_user_away(self) -> bool:
        return self._away_started_at is not None

    @property
    def quiet_reason(self) -> str:
        return self._quiet_reason

    @property
    def foreground_category(self) -> str | None:
        return self._category

    @property
    def taskbar_hidden(self) -> bool:
        return self._taskbar_hidden

    def start(self) -> bool:
        """낮은 빈도의 폴링과 Windows 네이티브 이벤트를 시작한다."""
        if self._started:
            return True
        self._started = True
        if sys.platform != "win32":
            return True

        app = QCoreApplication.instance()
        if app is None:
            self._started = False
            return False

        self._notification_window = QWidget()
        self._notification_hwnd = int(self._notification_window.winId())
        self._native_filter = _SessionNativeEventFilter(self, self._notification_hwnd)
        app.installNativeEventFilter(self._native_filter)
        self._lock_notifications_available = self._api.register_session_notifications(
            self._notification_hwnd
        )
        if not self._lock_notifications_available:
            app.removeNativeEventFilter(self._native_filter)
            self._native_filter = None
            logging.warning("세션 잠금 알림을 등록하지 못해 주기 확인으로 대신합니다.")
        self._refresh_session_state()

        self._foreground_hook, self._native_callback = self._api.install_foreground_hook(
            self._on_foreground_event
        )
        if self._foreground_hook is None:
            logging.warning("전경 창 이벤트를 등록하지 못했습니다.")
        self._idle_timer.start(5000)
        self._quiet_timer.start(30000)
        self._display_timer.start(1000)
        self._ide_long_use_timer.start(60000)
        self._on_foreground_event()
        return True

    def stop(self) -> None:
        self._idle_timer.stop()
        self._quiet_timer.stop()
        self._display_timer.stop()
        self._ide_long_use_timer.stop()
        app = QCoreApplication.instance()
        if app is not None and self._native_filter is not None:
            app.removeNativeEventFilter(self._native_filter)
        self._native_filter = None
        if self._notification_hwnd is not None and self._lock_notifications_available:
            self._api.unregister_session_notifications(self._notification_hwnd)
        if self._foreground_hook is not None:
            self._api.remove_foreground_hook(self._foreground_hook)
        if self._notification_window is not None:
            self._notification_window.close()
        self._notification_window = None
        self._notification_hwnd = None
        self._foreground_hook = None
        self._native_callback = None
        self._started = False
        global _active_monitor
        if _active_monitor is self:
            _active_monitor = None

    def handle_session_change(self, event: int) -> None:
        if event == _WTS_SESSION_LOCK:
            self._wts_session_locked = True
            self._set_session_locked(True)
        elif event == _WTS_SESSION_UNLOCK:
            self._wts_session_locked = False
            self._set_session_locked(False)

    def _set_session_locked(self, locked: bool) -> None:
        if locked == self._session_locked:
            return
        self._session_locked = locked
        (self.session_locked if locked else self.session_unlocked).emit()

    def _refresh_session_state(self) -> None:
        if self._wts_session_locked:
            return
        locked = self._api.get_session_locked()
        if locked is None:
            self._set_session_locked(True)
            return
        self._set_session_locked(locked)

    def refresh(self) -> None:
        self._check_idle()
        self._on_foreground_event()
        self._check_ide_long_use()
        self.settings_refreshed.emit()

    def _check_idle(self) -> None:
        settings = self._settings_provider()
        if not settings.get("activity_idle_reaction_enabled", True):
            if self._away_started_at is not None:
                self._away_started_at = None
                if self._category == "ide":
                    self._ide_active_started_at = self._clock()
                self.user_returned.emit(0)
            return
        idle_seconds = self._api.get_idle_seconds()
        if idle_seconds is None:
            return
        try:
            threshold = max(1, int(settings.get("activity_away_threshold_minutes", 5))) * 60
        except (TypeError, ValueError):
            threshold = 300

        now = self._clock()
        if idle_seconds >= threshold:
            if self._away_started_at is None:
                self._away_started_at = now - idle_seconds
                self._ide_active_started_at = None
                self.user_away.emit(idle_seconds)
        elif self._away_started_at is not None:
            away_seconds = max(0, int(now - self._away_started_at))
            self._away_started_at = None
            if self._category == "ide":
                self._ide_active_started_at = now
            self.user_returned.emit(away_seconds)

    def _check_quiet(self) -> None:
        settings = self._settings_provider()
        if not settings.get("activity_quiet_reaction_enabled", True):
            self._set_quiet_reason("none")
            return
        reason = self._api.get_quiet_reason()
        if reason is None:
            return
        if reason == "none" and self._category in ("game", "video"):
            reason = "game"
        self._set_quiet_reason(reason)

    def _on_foreground_event(self) -> None:
        self._refresh_display_state()
        settings = self._settings_provider()
        category_enabled = bool(settings.get("activity_app_category_reaction_enabled", False))
        if category_enabled:
            category = self._api.get_foreground_app_category()
            if isinstance(category, str) and category in _APP_CATEGORIES:
                self._set_category(category)
        elif self._category_enabled:
            self._set_category("other")
        self._category_enabled = category_enabled
        self._check_quiet()

    def _refresh_display_state(self) -> None:
        self._refresh_session_state()
        self._foreground_rect = self._api.get_foreground_window_rect()
        self._taskbar_hidden = self._api.is_taskbar_hidden()

    def _set_category(self, category: str) -> None:
        if category == self._category:
            return
        self._category = category
        self._category_changed_at = self._clock()
        self._ide_active_started_at = (
            self._category_changed_at
            if category == "ide" and not self.is_user_away
            else None
        )
        self.foreground_category_changed.emit(category)

    def _check_ide_long_use(self) -> None:
        settings = self._settings_provider()
        if (
            self._category != "ide"
            or self._ide_active_started_at is None
            or not settings.get("activity_app_category_reaction_enabled", False)
            or not settings.get("activity_ide_long_use_reaction_enabled", True)
        ):
            return
        duration = max(0, int(self._clock() - self._ide_active_started_at))
        if duration >= 3 * 60 * 60:
            self.ide_long_use_due.emit(duration)

    def _set_quiet_reason(self, reason: str) -> None:
        if reason != self._quiet_reason:
            self._quiet_reason = reason
            self.quiet_state_changed.emit(reason)

    def foreground_covers(self, width: int, height: int) -> bool:
        return window_inspector.rect_covers_screen(self._foreground_rect, width, height)

    def llm_activity_context(self) -> str:
        settings = self._settings_provider()
        if not settings.get("activity_app_category_reaction_enabled", False):
            return ""
        if self._category is None:
            return ""
        elapsed = max(0, int(self._clock() - self._category_changed_at))
        return f"[activity] category={self._category}; elapsed_seconds={elapsed}"


def get_activity_context() -> str:
    if _active_monitor is None:
        return ""
    return _active_monitor.llm_activity_context()


def refresh_activity_monitor() -> None:
    if _active_monitor is not None:
        _active_monitor.refresh()

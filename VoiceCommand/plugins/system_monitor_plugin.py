"""시스템 상태 오버레이 + 임계값 알림 플러그인."""
from __future__ import annotations

import logging
import secrets
import threading
import time

PLUGIN_INFO = {
    "name": "system_monitor_plugin",
    "version": "2.1.0",
    "api_version": "1.0",
    "description": "CPU/메모리/배터리 현황을 오버레이로 표시하고, 임계값 초과 시 캐릭터 반응을 표시한다",
}

_RNG = secrets.SystemRandom()
_widget_ref = None
_monitor_running = False
_monitor_thread: threading.Thread | None = None
_stop_event = threading.Event()
_last_alert_times: dict[str, float] = {}

# GC 방지
_active_overlay = None

THRESHOLDS = {
    "cpu": {"warn": 85, "critical": 95},
    "ram": {"warn": 85, "critical": 95},
    "battery_low": 20,
    "battery_critical": 10,
}

COOLDOWNS = {
    "cpu_warn": 300,
    "cpu_critical": 120,
    "ram_warn": 300,
    "ram_critical": 120,
    "battery_low": 600,
    "battery_critical": 60,
}


def _get_messages():
    from i18n.translator import _

    return {
        "cpu_warn": (
            "화남",
            [_("CPU가 힘들어하고 있어요!"), _("컴퓨터가 뜨거워요!"), _("프로그램이 너무 많아요~")],
        ),
        "cpu_critical": (
            "걱정",
            [_("CPU가 너무 바빠요! 좀 쉬게 해줘요!"), _("과부하예요, 조심해요!")],
        ),
        "ram_warn": (
            "걱정",
            [_("메모리가 꽉 찼어요..."), _("램이 부족해요!"), _("창을 좀 닫아주세요~")],
        ),
        "ram_critical": (
            "화남",
            [_("메모리가 위험해요!"), _("지금 당장 뭔가 닫아야 해요!")],
        ),
        "battery_low": (
            "걱정",
            [_("배터리가 얼마 없어요!"), _("충전기 꽂아주세요~"), _("방전되면 안 돼요!")],
        ),
        "battery_critical": (
            "화남",
            [_("충전 빨리요!!"), _("배터리가 {pct}%예요!"), _("꺼지기 전에 충전해요!")],
        ),
    }


def _maybe_react(key: str, now: float, pct: int = 0) -> None:
    last = _last_alert_times.get(key, 0.0)
    if now - last < COOLDOWNS[key]:
        return
    _last_alert_times[key] = now

    emotion, messages = _get_messages()[key]
    message = _RNG.choice(messages)
    if "{pct}" in message:
        message = message.format(pct=pct)

    widget = _widget_ref
    if widget:
        widget.set_emotion(emotion)
        widget.say(message, duration=5000)


def _check_system() -> None:
    """임계값 초과 시 캐릭터 반응 (백그라운드 스레드용)."""
    try:
        import psutil
    except ImportError:
        return

    now = time.time()
    try:
        cpu = psutil.cpu_percent(interval=1)
        if cpu >= THRESHOLDS["cpu"]["critical"]:
            _maybe_react("cpu_critical", now)
        elif cpu >= THRESHOLDS["cpu"]["warn"]:
            _maybe_react("cpu_warn", now)
    except Exception as exc:
        logging.debug("[SystemMonitorPlugin] CPU 확인 오류: %s", exc)

    try:
        ram = psutil.virtual_memory().percent
        if ram >= THRESHOLDS["ram"]["critical"]:
            _maybe_react("ram_critical", now)
        elif ram >= THRESHOLDS["ram"]["warn"]:
            _maybe_react("ram_warn", now)
    except Exception as exc:
        logging.debug("[SystemMonitorPlugin] RAM 확인 오류: %s", exc)

    try:
        battery = psutil.sensors_battery()
        if battery and not battery.power_plugged:
            pct = int(battery.percent)
            if pct <= THRESHOLDS["battery_critical"]:
                _maybe_react("battery_critical", now, pct=pct)
            elif pct <= THRESHOLDS["battery_low"]:
                _maybe_react("battery_low", now, pct=pct)
    except Exception as exc:
        logging.debug("[SystemMonitorPlugin] 배터리 확인 오류: %s", exc)


def _monitor_loop() -> None:
    logging.info("[SystemMonitorPlugin] 모니터링 루프 시작")
    while not _stop_event.is_set():
        try:
            _check_system()
        except Exception as exc:
            logging.debug("[SystemMonitorPlugin] 루프 오류: %s", exc)
        for _ in range(30):
            if _stop_event.is_set():
                break
            time.sleep(1)
    logging.info("[SystemMonitorPlugin] 모니터링 루프 종료")


def _start_monitor_thread() -> None:
    global _monitor_thread, _monitor_running
    if _monitor_running and _monitor_thread and _monitor_thread.is_alive():
        return
    _stop_event.clear()
    _monitor_running = True
    _monitor_thread = threading.Thread(
        target=_monitor_loop, daemon=True, name="ari-sysmon"
    )
    _monitor_thread.start()


def _enforce_overlay_topmost(overlay) -> None:
    if overlay is None:
        return
    try:
        overlay.show()
        overlay.raise_()
    except Exception as exc:
        logging.debug("[SystemMonitorPlugin] 오버레이 최상위 설정 실패: %s", exc)


def _dispose_overlay(overlay) -> None:
    if overlay is None:
        return
    for attr in ("_update_timer", "_anim_out", "_follow_timer"):
        candidate = getattr(overlay, attr, None)
        if candidate is None:
            continue
        try:
            candidate.stop()
        except Exception:
            pass
    try:
        overlay.close()
    except Exception:
        pass
    try:
        overlay.deleteLater()
    except Exception:
        pass


def _schedule_overlay_reassertion(overlay, *, attempts: int = 6, interval_ms: int = 80) -> None:
    if overlay is None or attempts <= 0:
        return

    from PySide6.QtCore import QTimer

    def _reapply(remaining: int) -> None:
        if _active_overlay is not overlay:
            return
        try:
            overlay.raise_()
            _enforce_overlay_topmost(overlay)
        except Exception as exc:
            logging.debug("[SystemMonitorPlugin] 오버레이 최상위 재적용 실패: %s", exc)
        if remaining > 1:
            QTimer.singleShot(interval_ms, lambda: _reapply(remaining - 1))

    QTimer.singleShot(interval_ms, lambda: _reapply(attempts))


def _get_widget_screen(widget):
    from PySide6.QtWidgets import QApplication

    if widget is None:
        return QApplication.primaryScreen()

    try:
        center_global = widget.mapToGlobal(widget.rect().center())
        screen = QApplication.screenAt(center_global)
        if screen is not None:
            return screen
    except Exception as exc:
        logging.debug("[SystemMonitorPlugin] screenAt 조회 실패: %s", exc)

    current_screen = getattr(widget, "_current_screen", None)
    if current_screen is not None:
        return current_screen

    try:
        widget_screen = getattr(widget, "screen", None)
        if callable(widget_screen):
            screen = widget_screen()
            if screen is not None:
                return screen
    except Exception as exc:
        logging.debug("[SystemMonitorPlugin] widget.screen 조회 실패: %s", exc)

    try:
        window_handle_fn = getattr(widget, "windowHandle", None)
        if callable(window_handle_fn):
            window_handle = window_handle_fn()
            screen_fn = getattr(window_handle, "screen", None)
            if callable(screen_fn):
                screen = screen_fn()
                if screen is not None:
                    return screen
    except Exception as exc:
        logging.debug("[SystemMonitorPlugin] windowHandle.screen 조회 실패: %s", exc)

    return QApplication.primaryScreen()


def _calculate_overlay_position(widget, overlay) -> tuple[int, int]:
    from PySide6.QtWidgets import QApplication

    origin = widget.mapToGlobal(widget.rect().topLeft())
    wx, wy, ww = origin.x(), origin.y(), widget.width()
    ow, oh = overlay.width(), overlay.height()
    ox = wx + (ww - ow) // 2
    oy = wy - oh - 14

    screen = _get_widget_screen(widget)
    if screen:
        sg = screen.availableGeometry()
        ox = max(sg.left() + 4, min(ox, sg.right() - ow - 4))
        oy = max(sg.top() + 4, min(oy, sg.bottom() - oh - 4))
    else:
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            ox = max(sg.left() + 4, min(ox, sg.right() - ow - 4))
            oy = max(sg.top() + 4, min(oy, sg.bottom() - oh - 4))

    return ox, oy


def _sync_overlay_position(overlay, widget) -> None:
    if overlay is None or widget is None:
        return
    try:
        ox, oy = _calculate_overlay_position(widget, overlay)
        if overlay.x() != ox or overlay.y() != oy:
            overlay.move(ox, oy)
    except Exception as exc:
        logging.debug("[SystemMonitorPlugin] 오버레이 위치 갱신 실패: %s", exc)


def _get_system_stats() -> dict:
    result = {"cpu": 0.0, "ram": 0.0, "battery_pct": -1, "battery_plugged": True}
    try:
        import psutil
        result["cpu"] = float(psutil.cpu_percent(interval=None))
        result["ram"] = float(psutil.virtual_memory().percent)
        bat = psutil.sensors_battery()
        if bat:
            result["battery_pct"] = int(bat.percent)
            result["battery_plugged"] = bool(bat.power_plugged)
    except Exception as exc:
        logging.debug("[SystemMonitorPlugin] stats 획득 실패: %s", exc)
    return result


def _show_system_overlay(widget) -> None:
    """캐릭터 위에 실시간 시스템 현황 오버레이를 표시한다."""
    global _active_overlay

    try:
        import psutil  # noqa: F401
    except ImportError:
        from i18n.translator import _
        if widget:
            widget.say(_("⚠ psutil이 설치되지 않아 시스템 모니터를 사용할 수 없어요."), duration=5000)
        return

    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    )
    from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
    from PySide6.QtGui import QFont, QPainter, QColor, QPainterPath, QLinearGradient
    from i18n.translator import _

    # ── 기존 오버레이 닫기 ────────────────────────────────────────────────
    if _active_overlay is not None:
        try:
            _dispose_overlay(_active_overlay)
        except Exception:
            pass
        _active_overlay = None

    # ── 오버레이 위젯 ────────────────────────────────────────────────────
    class SystemMonitorOverlay(QWidget):
        def __init__(self):
            super().__init__(None)
            # BypassWindowManagerHint 제거 — Windows에서 show 직후 Z-order 소실 원인
            self.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
                | Qt.Tool
                | Qt.WindowDoesNotAcceptFocus
            )
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setAttribute(Qt.WA_ShowWithoutActivating)
            self.setFixedWidth(260)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(18, 14, 18, 14)
            layout.setSpacing(10)

            title = QLabel(_("💻 시스템 현황"))
            fnt = QFont()
            fnt.setPointSize(11)
            fnt.setBold(True)
            title.setFont(fnt)
            title.setStyleSheet("color: #e0f0ff; background: transparent;")
            layout.addWidget(title)

            sep = QLabel()
            sep.setFixedHeight(1)
            sep.setStyleSheet("background: rgba(100,180,255,40);")
            layout.addWidget(sep)

            self.cpu_label, self.cpu_bar = self._make_row(layout, _("🔴 CPU"), "#4fc3f7", "#0288d1")
            self.ram_label, self.ram_bar = self._make_row(layout, _("🟢 메모리"), "#81c784", "#388e3c")
            self.bat_label, self.bat_bar = self._make_row(layout, _("🔋 배터리"), "#ffb74d", "#f57c00")

        def _make_row(self, parent_layout, name, color_light, color_dark):
            row = QHBoxLayout()
            row.setSpacing(10)

            label = QLabel(f"{name}  --%")
            label.setFixedWidth(120)
            label.setStyleSheet("color: #cce8ff; font-size: 9pt; background: transparent;")
            row.addWidget(label)

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(False)
            bar.setFixedHeight(10)
            bar.setStyleSheet(f"""
                QProgressBar {{
                    background: rgba(255,255,255,20);
                    border-radius: 5px;
                    border: none;
                }}
                QProgressBar::chunk {{
                    background: qlineargradient(
                        x1:0, y1:0, x2:1, y2:0,
                        stop:0 {color_dark}, stop:1 {color_light}
                    );
                    border-radius: 5px;
                }}
            """)
            row.addWidget(bar)
            parent_layout.addLayout(row)
            return label, bar

        def refresh_stats(self):
            stats = _get_system_stats()

            cpu = stats["cpu"]
            self.cpu_label.setText(_("🔴 CPU   {value:.0f}%", value=cpu))
            self.cpu_bar.setValue(int(cpu))

            ram = stats["ram"]
            self.ram_label.setText(_("🟢 메모리  {value:.0f}%", value=ram))
            self.ram_bar.setValue(int(ram))

            bat_pct = stats["battery_pct"]
            if bat_pct >= 0:
                icon = "🔌" if stats["battery_plugged"] else "🔋"
                self.bat_label.setText(_("{icon} 배터리  {value}%", icon=icon, value=bat_pct))
                self.bat_bar.setValue(bat_pct)
            else:
                self.bat_label.setText(_("🔋 배터리  없음"))
                self.bat_bar.setValue(0)

        def paintEvent(self, _event):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(0.0, 0.0, float(self.width()), float(self.height()), 14.0, 14.0)
            grad = QLinearGradient(0, 0, 0, self.height())
            grad.setColorAt(0, QColor(15, 30, 55, 245))
            grad.setColorAt(1, QColor(8, 18, 35, 252))
            p.fillPath(path, grad)
            p.setPen(QColor(80, 160, 255, 55))
            p.drawPath(path)

    # ── 생성 + 모듈 레벨 참조 ────────────────────────────────────────────
    overlay = SystemMonitorOverlay()
    _active_overlay = overlay

    # priming (첫 cpu_percent 호출)
    try:
        import psutil
        psutil.cpu_percent(interval=None)
    except Exception:
        pass

    # ── 레이아웃 강제 계산 후 위치 결정 ────────────────────────────────
    overlay.layout().activate()
    overlay.adjustSize()

    overlay.setWindowOpacity(1.0)
    _sync_overlay_position(overlay, widget)
    overlay.show()
    overlay.refresh_stats()
    overlay.raise_()
    _enforce_overlay_topmost(overlay)
    _schedule_overlay_reassertion(overlay)

    overlay._follow_timer = QTimer(overlay)
    overlay._follow_timer.timeout.connect(lambda: _sync_overlay_position(overlay, widget))
    overlay._follow_timer.start(50)

    # ── 1초마다 통계 갱신 ────────────────────────────────────────────────
    overlay._update_timer = QTimer(overlay)
    overlay._update_timer.timeout.connect(overlay.refresh_stats)
    overlay._update_timer.start(1000)

    # ── 8초 후 페이드아웃 ────────────────────────────────────────────────
    def _start_fade_out():
        global _active_overlay
        if _active_overlay is None:
            return
        try:
            overlay._update_timer.stop()
        except Exception:
            pass
        overlay_ref = overlay
        overlay_ref._anim_out = QPropertyAnimation(overlay_ref, b"windowOpacity")
        overlay_ref._anim_out.setDuration(600)
        overlay_ref._anim_out.setStartValue(1.0)
        overlay_ref._anim_out.setEndValue(0.0)

        def _cleanup():
            global _active_overlay
            if _active_overlay is overlay_ref:
                _dispose_overlay(overlay_ref)
                _active_overlay = None

        overlay_ref._anim_out.finished.connect(_cleanup)
        overlay_ref._anim_out.start()

    QTimer.singleShot(8000, _start_fade_out)
    ox, oy = overlay.x(), overlay.y()
    logging.info("[SystemMonitorPlugin] 시스템 오버레이 표시 완료 (pos=%d,%d)", ox, oy)


def _on_show_system_monitor():
    from PySide6.QtCore import QTimer
    widget = _widget_ref
    if not widget:
        return
    # 메뉴가 완전히 닫힌 후 표시 — 메뉴 닫힘 이벤트가 Z-order를 덮어쓰지 않도록
    QTimer.singleShot(80, lambda: _show_system_overlay(widget))


def register(context):
    from i18n.translator import _

    global _widget_ref
    _widget_ref = getattr(context, "character_widget", None)

    _start_monitor_thread()

    if callable(getattr(context, "register_menu_action", None)):
        context.register_menu_action(_("💻 시스템 모니터"), _on_show_system_monitor)

    logging.info("[SystemMonitorPlugin] 로드 완료")
    return {
        "message": "system_monitor_plugin loaded",
        "has_widget": _widget_ref is not None,
    }

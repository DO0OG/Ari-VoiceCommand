"""친밀도(호감도) 시스템 플러그인."""
from __future__ import annotations

import logging
import secrets
import threading
import time
from typing import Optional


PLUGIN_INFO = {
    "name": "affinity_plugin",
    "version": "1.2.0",
    "api_version": "1.0",
    "description": "사용자와의 상호작용을 추적하여 친밀도 레벨을 관리한다",
}

LEVEL_THRESHOLDS = [0, 50, 200, 500, 1000]
_RNG = secrets.SystemRandom()
_widget_ref = None
_affinity_manager: Optional["AffinityManager"] = None
# GC 방지: 오버레이 위젯을 모듈 레벨에서 참조 유지
_active_overlay = None


def _get_widget():
    return _widget_ref


def _get_level_names():
    from i18n.translator import _

    return [_("초면"), _("지인"), _("친구"), _("친한친구"), _("절친")]


def _get_level_up_messages():
    from i18n.translator import _

    return {
        1: [_("앞으로 잘 부탁드려요."), _("조금 익숙해졌네요.")],
        2: [_("이제 편해졌네요."), _("함께하니 좋아요.")],
        3: [_("많이 친해졌네요."), _("이제 편하게 얘기해요.")],
        4: [_("오래 알고 지냈네요."), _("이제 많이 친해진 것 같아요.")],
    }


def _get_greeting_by_level():
    from i18n.translator import _

    return {
        0: [_("네, 주인님?"), _("부르셨나요, 주인님?")],
        1: [_("네?"), _("왜요?")],
        2: [_("왜요?"), _("뭐예요?")],
        3: [_("응?"), _("왜~?")],
        4: [_("응?ㅋ"), _("왜ㅋ")],
    }


class AffinityManager:
    _SAVE_DEBOUNCE_SEC = 30.0

    def __init__(self):
        self._save_timer: Optional[threading.Timer] = None
        self._load()

    def _load(self):
        from core.config_manager import ConfigManager

        settings = ConfigManager.load_settings()
        self.points = int(settings.get("affinity_points", 0))
        self.level = int(settings.get("affinity_level", 0))
        self.total_clicks = int(settings.get("affinity_total_clicks", 0))
        self.total_pets = int(settings.get("affinity_total_pets", 0))
        self.total_chats = int(settings.get("affinity_total_chats", 0))
        self.last_login = str(settings.get("affinity_last_login", ""))

    def _save(self):
        from core.config_manager import ConfigManager

        settings = ConfigManager.load_settings()
        settings.update(
            {
                "affinity_points": self.points,
                "affinity_level": self.level,
                "affinity_total_clicks": self.total_clicks,
                "affinity_total_pets": self.total_pets,
                "affinity_total_chats": self.total_chats,
                "affinity_last_login": self.last_login,
            }
        )
        ConfigManager.save_settings(settings)

    def _schedule_save(self) -> None:
        if self._save_timer is not None:
            self._save_timer.cancel()
        t = threading.Timer(self._SAVE_DEBOUNCE_SEC, self._save)
        t.daemon = True
        self._save_timer = t
        t.start()

    def _calculate_level(self) -> int:
        for level in range(len(LEVEL_THRESHOLDS) - 1, -1, -1):
            if self.points >= LEVEL_THRESHOLDS[level]:
                return level
        return 0

    def add_points(self, points: int, reason: str = "") -> bool:
        self.points += int(points)
        if reason == "click":
            self.total_clicks += 1
        elif reason == "pet":
            self.total_pets += 1
        elif reason == "chat":
            self.total_chats += 1

        old_level = self.level
        self.level = self._calculate_level()
        leveled_up = self.level > old_level
        if leveled_up:
            self._save()
        else:
            self._schedule_save()
        return leveled_up

    def get_level(self) -> int:
        return self.level

    def get_level_name(self) -> str:
        names = _get_level_names()
        return names[min(self.level, len(names) - 1)]

    def get_level_up_message(self) -> str:
        messages = _get_level_up_messages()
        candidates = messages.get(self.level, [])
        return _RNG.choice(candidates) if candidates else ""

    def get_greeting(self) -> str:
        greetings = _get_greeting_by_level()
        return _RNG.choice(greetings.get(self.level, greetings[0]))

    def record_daily_login(self) -> bool:
        from datetime import date

        today = date.today().isoformat()
        if self.last_login == today:
            return False
        self.last_login = today
        leveled_up = self.add_points(10, "login")
        if not leveled_up:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
            self._save()
        return leveled_up


def _call_original_say(widget, text: str, duration: int = 5000) -> None:
    original_say = getattr(widget, "_affinity_original_say", None)
    if callable(original_say):
        original_say(text, duration)
    else:
        widget.say(text, duration)


def _notify_level_up() -> None:
    widget = _get_widget()
    if widget is None or _affinity_manager is None:
        return

    message = _affinity_manager.get_level_up_message()
    if not message:
        return

    def _delayed_feedback():
        time.sleep(0.8)
        try:
            _call_original_say(widget, message, 3500)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(500, _on_show_affinity)
        except Exception as exc:
            logging.debug("[AffinityPlugin] 레벨업 알림 표시 실패: %s", exc)

    threading.Thread(
        target=_delayed_feedback,
        daemon=True,
        name="ari-affinity-level-up",
    ).start()


def _enforce_overlay_topmost(overlay) -> None:
    """Qt 레벨에서 오버레이를 재상단으로 올린다."""
    if overlay is None:
        return
    try:
        overlay.show()
        overlay.raise_()
    except Exception as exc:
        logging.debug("[AffinityPlugin] 오버레이 최상위 설정 실패: %s", exc)


def _dispose_overlay(overlay) -> None:
    if overlay is None:
        return
    for attr in ("_anim_bar", "_anim_out", "_follow_timer"):
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
            logging.debug("[AffinityPlugin] 오버레이 최상위 재적용 실패: %s", exc)
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
        logging.debug("[AffinityPlugin] screenAt 조회 실패: %s", exc)

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
        logging.debug("[AffinityPlugin] widget.screen 조회 실패: %s", exc)

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
        logging.debug("[AffinityPlugin] windowHandle.screen 조회 실패: %s", exc)

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
        logging.debug("[AffinityPlugin] 오버레이 위치 갱신 실패: %s", exc)


def _show_affinity_overlay(widget, level: int, level_name: str, points: int, next_threshold: int) -> None:
    """캐릭터 위에 친밀도 게이지를 표시한다 (메인 스레드에서 호출)."""
    global _active_overlay

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
    class AffinityGauge(QWidget):
        def __init__(self):
            super().__init__(None)
            # BypassWindowManagerHint 제거 — Windows에서 이 플래그는
            # 창 관리자가 Z-order를 무시하게 만들어 show 후 즉시 가려지는 원인
            self.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
                | Qt.Tool
                | Qt.WindowDoesNotAcceptFocus
            )
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setAttribute(Qt.WA_ShowWithoutActivating)
            self.setFixedWidth(240)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(18, 14, 18, 14)
            layout.setSpacing(10)

            # ── 헤더 ─────────────────────────────────────────
            header = QHBoxLayout()
            header.setSpacing(8)

            heart = QLabel("♥")
            heart.setStyleSheet(
                "color: #ff5e7e; font-size: 20pt; font-weight: bold; background: transparent;"
            )
            header.addWidget(heart)

            info = QVBoxLayout()
            info.setSpacing(2)

            title = QLabel(_("친밀도 · Lv.{level} {level_name}", level=level, level_name=level_name))
            fnt = QFont()
            fnt.setPointSize(12)
            fnt.setBold(True)
            title.setFont(fnt)
            title.setStyleSheet("color: #ffffff; background: transparent;")
            info.addWidget(title)

            max_val = str(next_threshold) if next_threshold > 0 else _("최대")
            pts = QLabel(_("{points} / {max_val} 포인트", points=points, max_val=max_val))
            pts.setStyleSheet("color: #d1c4e9; font-size: 9pt; background: transparent;")
            info.addWidget(pts)

            header.addLayout(info)
            header.addStretch()
            layout.addLayout(header)

            # ── 게이지 바 ────────────────────────────────────
            self.bar = QProgressBar()
            bar_max = next_threshold if next_threshold > 0 else max(1, points)
            self.bar.setRange(0, bar_max)
            self.bar.setValue(0)
            self.bar.setTextVisible(False)
            self.bar.setFixedHeight(12)
            self.bar.setStyleSheet("""
                QProgressBar {
                    background: rgba(255,255,255,30);
                    border-radius: 6px;
                    border: none;
                }
                QProgressBar::chunk {
                    background: qlineargradient(
                        x1:0, y1:0, x2:1, y2:0,
                        stop:0 #ff758c, stop:1 #ff7eb3
                    );
                    border-radius: 6px;
                }
            """)
            layout.addWidget(self.bar)

        def paintEvent(self, _event):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(0.0, 0.0, float(self.width()), float(self.height()), 14.0, 14.0)
            grad = QLinearGradient(0, 0, 0, self.height())
            grad.setColorAt(0, QColor(50, 20, 75, 245))
            grad.setColorAt(1, QColor(25, 12, 40, 252))
            p.fillPath(path, grad)
            p.setPen(QColor(255, 120, 180, 60))
            p.drawPath(path)

    # ── 생성 + 레이아웃 강제 계산 ───────────────────────────────────────
    overlay = AffinityGauge()
    _active_overlay = overlay

    # layout().activate() 없이 sizeHint()를 호출하면 -1 반환 → 크기 0
    overlay.layout().activate()
    overlay.adjustSize()

    overlay.setWindowOpacity(1.0)
    _sync_overlay_position(overlay, widget)
    overlay.show()
    overlay.raise_()
    _enforce_overlay_topmost(overlay)
    _schedule_overlay_reassertion(overlay)

    overlay._follow_timer = QTimer(overlay)
    overlay._follow_timer.timeout.connect(lambda: _sync_overlay_position(overlay, widget))
    overlay._follow_timer.start(50)

    # ── 게이지 바 채우기 애니메이션 ──────────────────────────────────────
    target_val = min(points, next_threshold) if next_threshold > 0 else points
    overlay._anim_bar = QPropertyAnimation(overlay.bar, b"value")
    overlay._anim_bar.setDuration(1200)
    overlay._anim_bar.setStartValue(0)
    overlay._anim_bar.setEndValue(max(0, target_val))
    overlay._anim_bar.setEasingCurve(QEasingCurve.OutQuart)
    overlay._anim_bar.start()

    # ── 5초 후 페이드아웃 (setWindowOpacity) ─────────────────────────────
    def _start_fade_out():
        global _active_overlay
        if _active_overlay is None:
            return
        overlay_ref = _active_overlay
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

    QTimer.singleShot(5000, _start_fade_out)
    ox, oy = overlay.x(), overlay.y()
    logging.info("[AffinityPlugin] 오버레이 표시: Lv.%d %s, %dpt (pos=%d,%d)", level, level_name, points, ox, oy)


def _on_show_affinity():
    """메뉴에서 '💝 친밀도 확인' 클릭 시 호출."""
    from PySide6.QtCore import QTimer

    widget = _get_widget()
    if not widget or not _affinity_manager:
        logging.warning("[AffinityPlugin] _on_show_affinity: widget=%s, manager=%s", widget, _affinity_manager)
        return

    level = _affinity_manager.get_level()
    level_name = _affinity_manager.get_level_name()
    points = _affinity_manager.points
    next_idx = level + 1
    next_threshold = LEVEL_THRESHOLDS[next_idx] if next_idx < len(LEVEL_THRESHOLDS) else 0

    # 메뉴가 완전히 닫힌 후 표시 — 메뉴 닫힘 이벤트가 Z-order를 덮어쓰지 않도록
    QTimer.singleShot(80, lambda: _show_affinity_overlay(widget, level, level_name, points, next_threshold))


def register(context):
    from i18n.translator import _

    global _widget_ref, _affinity_manager

    _widget_ref = getattr(context, "character_widget", None)
    _affinity_manager = AffinityManager()

    if _widget_ref:
        _widget_ref._affinity_manager = _affinity_manager
        _widget_ref._affinity_on_level_up = _notify_level_up
        if _affinity_manager.record_daily_login():
            _notify_level_up()

    if callable(getattr(context, "register_menu_action", None)):
        context.register_menu_action(_("💝 친밀도 확인"), _on_show_affinity)

    logging.info("[AffinityPlugin] 로드 완료 (포인트=%d, 레벨=%d)", _affinity_manager.points, _affinity_manager.level)
    return {
        "message": "affinity_plugin loaded",
        "has_widget": _widget_ref is not None,
    }

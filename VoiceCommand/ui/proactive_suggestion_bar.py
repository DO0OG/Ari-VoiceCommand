from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout
from ui.theme import (
    FONT_KO, FONT_SIZE_SMALL, COLOR_PRIMARY, COLOR_MUTED,
    COLOR_BG_SUGGESTION, COLOR_BG_CHIP_PRIMARY,
)
from ui import theme as theme_module
from i18n.translator import _


# ── 선제적 제안 바 ────────────────────────────────────────────────────────────

class ProactiveSuggestionBar(QFrame):
    """시간 패턴·명령 빈도 기반 제안 칩을 표시하는 바."""

    suggestion_clicked = Signal(str)

    def __init__(self, ctx_manager=None, parent=None):
        super().__init__(parent)
        self._ctx = ctx_manager
        self._shown_suggestions = None
        # 긴 제안 문구가 채팅창의 최소 폭을 넓히지 않게 한다.
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._build_ui()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_suggestions)
        # 창이 표시될 때만 타이머 가동 (showEvent/hideEvent에서 제어)
        self._refresh_suggestions()

    def _build_ui(self) -> None:
        self.setStyleSheet(f"""
            QFrame {{ background: {COLOR_BG_SUGGESTION};
                      border-bottom: 1px solid rgba(74,144,226,40); }}
        """)
        lay = QVBoxLayout(self)
        # 부모 없이 잠깐 표시될 때 칩 폭이 최소 크기로 굳지 않게 한다.
        lay.setSizeConstraint(QVBoxLayout.SetNoConstraint)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(2)

        hint_lbl = QLabel(_("💡 자주 쓰는 명령"))
        hint_lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
        hint_lbl.setStyleSheet(f"color: {COLOR_MUTED};")
        lay.addWidget(hint_lbl)

        self._chips_row = QHBoxLayout()
        self._chips_row.setSpacing(6)
        self._chips_row.setAlignment(Qt.AlignLeft)
        lay.addLayout(self._chips_row)

    def _refresh_suggestions(self, force: bool = False) -> None:
        suggestions = self._build_suggestions()[:4]
        # 내용이 같으면 칩을 다시 만들지 않아 주기적인 깜박임을 막는다.
        if not force and suggestions == self._shown_suggestions:
            return
        self._shown_suggestions = suggestions
        # 기존 칩 제거
        while self._chips_row.count():
            item = self._chips_row.takeAt(0)
            if item and item.widget():
                item.widget().hide()
                item.widget().deleteLater()

        if not suggestions:
            self.hide()
            return

        for text, goal in suggestions:
            btn = QPushButton(text)
            btn.setProperty("full_text", text)
            btn.setToolTip(text)
            btn.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(26)
            btn.setStyleSheet(f"""
                QPushButton {{ background: {COLOR_BG_CHIP_PRIMARY}; color: {COLOR_PRIMARY};
                               border-radius: 13px; border: none; padding: 0 12px; }}
                QPushButton:hover {{ background: {COLOR_PRIMARY}; color: white; }}
            """)
            _goal = goal
            btn.clicked.connect(lambda checked=False, g=_goal: self.suggestion_clicked.emit(g))
            self._chips_row.addWidget(btn)

        self._fit_chips()
        self.show()

    def _fit_chips(self) -> None:
        """칩 문구를 바 폭에 맞춰 말줄임으로 자른다."""
        count = self._chips_row.count()
        if not count:
            return
        margins = self.layout().contentsMargins()
        available = self.width() - margins.left() - margins.right()
        chip_width = max(48, (available - self._chips_row.spacing() * (count - 1)) // count)
        for index in range(count):
            btn = self._chips_row.itemAt(index).widget()
            if btn is None:
                continue
            full_text = str(btn.property("full_text") or "")
            metrics = QFontMetrics(btn.font())
            # 좌우 padding 12px씩을 뺀 폭 안에 들어가게 하고, 짧은 문구는 제 폭만 쓴다.
            btn.setText(metrics.elidedText(full_text, Qt.ElideRight, chip_width - 24))
            btn.setFixedWidth(min(chip_width, metrics.horizontalAdvance(full_text) + 24))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_chips()

    def _build_suggestions(self) -> list:
        try:
            from agent.speech_scheduler import get_speech_scheduler
        except (ImportError, OSError, RuntimeError, TypeError, ValueError):
            scheduler = None
        else:
            scheduler = get_speech_scheduler()
        if scheduler is not None:
            suggestions = []
            for item in scheduler.get_proactive_suggestions():
                text = str(item.get("text", "")).strip()
                goal = str(item.get("goal", text)).strip()
                if text and goal:
                    suggestions.append((text, goal))
            return suggestions[:4]
        if not self._ctx:
            return []
        suggestions = []
        time_cmds = self._ctx.get_time_based_suggestions(limit=2)
        if time_cmds:
            for cmd in time_cmds:
                suggestions.append((f"⏰ {cmd}", cmd))
        for cmd in self._ctx.get_predicted_next_commands()[:2]:
            if not any(cmd == s[1] for s in suggestions):
                suggestions.append((f"→ {cmd}", cmd))
        return suggestions[:4]

    def start_timer(self) -> None:
        self._refresh_timer.start(theme_module.SUGGESTION_REFRESH)

    def stop_timer(self) -> None:
        self._refresh_timer.stop()

    def refresh_theme(self) -> None:
        timer_active = self._refresh_timer.isActive()
        self._refresh_timer.setInterval(theme_module.SUGGESTION_REFRESH)
        self.setStyleSheet(f"""
            QFrame {{ background: {theme_module.COLOR_BG_SUGGESTION};
                      border-bottom: 1px solid rgba(74,144,226,40); }}
        """)
        if timer_active:
            self._refresh_timer.start()
        self._refresh_suggestions(force=True)



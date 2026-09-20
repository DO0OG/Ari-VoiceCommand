from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from ui.theme import (
    FONT_KO, FONT_SIZE_SMALL, COLOR_PRIMARY, COLOR_MUTED,
    COLOR_BG_SUGGESTION, COLOR_BG_CHIP_PRIMARY, SUGGESTION_REFRESH,
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

    def _refresh_suggestions(self) -> None:
        # 기존 칩 제거
        while self._chips_row.count():
            item = self._chips_row.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        suggestions = self._build_suggestions()
        if not suggestions:
            self.hide()
            return

        for text, goal in suggestions[:4]:
            btn = QPushButton(text)
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

        self.show()

    def _build_suggestions(self) -> list:
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

    def update_context_manager(self, ctx_manager) -> None:
        self._ctx = ctx_manager
        self._refresh_suggestions()

    def start_timer(self) -> None:
        self._refresh_timer.start(SUGGESTION_REFRESH)

    def stop_timer(self) -> None:
        self._refresh_timer.stop()

    def refresh_theme(self) -> None:
        self.setStyleSheet(f"""
            QFrame {{ background: {theme_module.COLOR_BG_SUGGESTION};
                      border-bottom: 1px solid rgba(74,144,226,40); }}
        """)
        self._refresh_suggestions()



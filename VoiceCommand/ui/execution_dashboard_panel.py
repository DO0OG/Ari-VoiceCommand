from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from ui.common import clear_layout
from ui.theme import (
    FONT_KO, FONT_SIZE_SMALL, COLOR_PRIMARY, COLOR_MUTED,
    COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER, COLOR_BG_DASHBOARD,
    DASHBOARD_AUTO_HIDE,
)
from ui import theme as theme_module
from i18n.translator import _


# 단계 상태별 아이콘
_STEP_ICON = {
    "pending": "⏳", "running": "⚙️",
    "done": "✅", "failed": "❌", "fixed": "🔧",
}


# ── 실행 대시보드 패널 ───────────────────────────────────────────────────────

class ExecutionDashboardPanel(QFrame):
    """에이전트 실행 중 step-by-step 진행 상황을 표시하는 접이식 패널."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._steps: dict = {}
        self._build_ui()
        self.hide()

    def _build_ui(self) -> None:
        self.setStyleSheet(f"""
            QFrame {{ background: {COLOR_BG_DASHBOARD};
                      border-bottom: 1px solid rgba(74,144,226,60); }}
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 8, 14, 8)
        outer.setSpacing(4)

        header = QHBoxLayout()
        self._title_lbl = QLabel(_("🤖 실행 중..."))
        self._title_lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL + 1, QFont.Bold))
        self._title_lbl.setStyleSheet(f"color: {COLOR_PRIMARY};")
        header.addWidget(self._title_lbl)
        header.addStretch()

        self._iter_lbl = QLabel("")
        self._iter_lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
        self._iter_lbl.setStyleSheet(f"color: {COLOR_MUTED};")
        header.addWidget(self._iter_lbl)
        outer.addLayout(header)

        self._steps_widget = QWidget()
        self._steps_lay = QVBoxLayout(self._steps_widget)
        self._steps_lay.setContentsMargins(0, 2, 0, 0)
        self._steps_lay.setSpacing(2)
        outer.addWidget(self._steps_widget)

        self._summary_lbl = QLabel("")
        self._summary_lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
        self._summary_lbl.setWordWrap(True)
        self._summary_lbl.setStyleSheet("color: #555;")
        outer.addWidget(self._summary_lbl)

    # ── Progress 이벤트 처리 ──────────────────────────────────────────────────

    def on_progress(self, event_type: str, **kwargs) -> None:
        """오케스트레이터 progress 이벤트 처리 (메인 스레드에서 호출)."""
        if event_type == "plan_ready":
            self._steps.clear()
            steps     = kwargs.get("steps", [])
            iteration = kwargs.get("iteration", 0)
            self._title_lbl.setText(_("🤖 계획 {count}단계").format(count=len(steps)))
            self._iter_lbl.setText(_("시도 {count}회").format(count=iteration + 1))
            for s in steps:
                self._steps[s["id"]] = {"desc": s["desc"], "type": s["type"], "status": "pending"}
            self._rebuild_steps()
            self._summary_lbl.setText("")
            self.show()

        elif event_type == "step_start":
            sid = kwargs.get("step_id")
            if sid in self._steps:
                self._steps[sid]["status"] = "running"
                self._rebuild_steps()

        elif event_type == "step_done":
            sid       = kwargs.get("step_id")
            success   = kwargs.get("success", True)
            was_fixed = kwargs.get("was_fixed", False)
            if sid in self._steps:
                self._steps[sid]["status"] = ("fixed" if was_fixed
                                              else ("done" if success else "failed"))
                self._rebuild_steps()

        elif event_type == "verify_start":
            self._title_lbl.setText(_("🔍 검증 중..."))

        elif event_type in ("achieved", "failed", "not_achieved"):
            summary = kwargs.get("summary", "")
            icon    = "✅" if event_type == "achieved" else "⚠️"
            label   = _("완료") if event_type == "achieved" else _("미완료")
            self._title_lbl.setText(f"{icon} {label}")
            self._summary_lbl.setText(summary[:120])
            if event_type == "achieved":
                QTimer.singleShot(DASHBOARD_AUTO_HIDE, self.hide)

        elif event_type == "replan":
            iteration = kwargs.get("iteration", 0)
            reason    = kwargs.get("reason", "")
            self._iter_lbl.setText(_("재계획 (시도 {count}회)").format(count=iteration + 2))
            self._summary_lbl.setText(f"♻️ {reason[:80]}")
            self._steps.clear()
            self._rebuild_steps()

    def _rebuild_steps(self) -> None:
        clear_layout(self._steps_lay)
        _step_color = {
            "running": COLOR_PRIMARY, "done": COLOR_SUCCESS,
            "failed": COLOR_DANGER,   "fixed": COLOR_WARNING,
        }
        for sid in sorted(self._steps):
            info   = self._steps[sid]
            status = info["status"]
            icon   = _STEP_ICON.get(status, "⏳")
            color  = _step_color.get(status, COLOR_MUTED)
            lbl = QLabel(f"{icon} {info['desc'][:60]}")
            lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
            lbl.setStyleSheet(f"color: {color};")
            self._steps_lay.addWidget(lbl)

    def reset(self) -> None:
        self._steps.clear()
        self._rebuild_steps()
        self._title_lbl.setText(_("🤖 실행 중..."))
        self._iter_lbl.setText("")
        self._summary_lbl.setText("")
        self.hide()

    def refresh_theme(self) -> None:
        self.setStyleSheet(f"""
            QFrame {{ background: {theme_module.COLOR_BG_DASHBOARD};
                      border-bottom: 1px solid rgba(74,144,226,60); }}
        """)
        self._title_lbl.setFont(QFont(theme_module.FONT_KO, theme_module.FONT_SIZE_SMALL + 1, QFont.Bold))
        self._title_lbl.setStyleSheet(f"color: {theme_module.COLOR_PRIMARY};")
        self._iter_lbl.setFont(QFont(theme_module.FONT_KO, theme_module.FONT_SIZE_SMALL))
        self._iter_lbl.setStyleSheet(f"color: {theme_module.COLOR_MUTED};")
        self._summary_lbl.setFont(QFont(theme_module.FONT_KO, theme_module.FONT_SIZE_SMALL))
        self._rebuild_steps()



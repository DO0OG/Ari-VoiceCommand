from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget
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

    # 계획 확인 중 사용자가 누른 결과 (True: 실행, False: 취소)
    plan_decision = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._steps: dict = {}
        self._targets: dict = {}  # step_id → (("읽기", [...]), ("쓰기", [...])), 계획 확인 때만 보인다
        self._awaiting_approval = False
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

        # 계획 확인 중에만 보이는 실행·취소 버튼
        self._approval_widget = QWidget()
        approval_lay = QHBoxLayout(self._approval_widget)
        approval_lay.setContentsMargins(0, 4, 0, 0)
        self._run_btn = QPushButton(_("실행"))
        self._cancel_btn = QPushButton(_("취소"))
        self._run_btn.clicked.connect(lambda: self._decide(True))
        self._cancel_btn.clicked.connect(lambda: self._decide(False))
        approval_lay.addStretch()
        approval_lay.addWidget(self._cancel_btn)
        approval_lay.addWidget(self._run_btn)
        outer.addWidget(self._approval_widget)
        self._approval_widget.hide()

    def _decide(self, approved: bool) -> None:
        # 한 번 누르면 버튼을 닫아 같은 계획에 결정이 두 번 가지 않게 한다.
        if not self._awaiting_approval:
            return
        self._end_approval()
        self._title_lbl.setText(_("🤖 실행 중...") if approved else _("⛔ 실행 취소"))
        self.plan_decision.emit(approved)

    def _end_approval(self) -> None:
        self._awaiting_approval = False
        self._approval_widget.hide()
        self._rebuild_steps()

    # ── Progress 이벤트 처리 ──────────────────────────────────────────────────

    def on_progress(self, event_type: str, **kwargs) -> None:
        """오케스트레이터 progress 이벤트 처리 (메인 스레드에서 호출)."""
        if event_type == "plan_ready":
            steps     = kwargs.get("steps", [])
            iteration = kwargs.get("iteration", 0)
            self._title_lbl.setText(_("🤖 계획 {count}단계").format(count=len(steps)))
            self._iter_lbl.setText(_("시도 {count}회").format(count=iteration + 1))
            self._load_steps(steps)
            self._summary_lbl.setText("")
            self.show()

        elif event_type == "plan_approval_request":
            # 스킬 단계처럼 plan_ready 없이 실행되는 계획도 있어 요청에 담긴 단계로 다시 채운다.
            self._load_steps(kwargs.get("steps", []))
            self._awaiting_approval = True
            self._title_lbl.setText(_("🤖 이 계획을 실행할까요?"))
            self._approval_widget.show()
            self._rebuild_steps()
            self.show()

        elif event_type == "plan_declined":
            self._end_approval()
            self._title_lbl.setText(_("⛔ 실행 취소"))
            self._summary_lbl.setText(_("계획을 승인받지 못해 아무 단계도 실행하지 않았습니다."))

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
                QTimer.singleShot(DASHBOARD_AUTO_HIDE, self._auto_hide)

        elif event_type == "replan":
            iteration = kwargs.get("iteration", 0)
            reason    = kwargs.get("reason", "")
            self._iter_lbl.setText(_("재계획 (시도 {count}회)").format(count=iteration + 2))
            self._summary_lbl.setText(f"♻️ {reason[:80]}")
            self._steps.clear()
            self._rebuild_steps()

    def _auto_hide(self) -> None:
        # 이전 실행의 숨김 타이머가 새 승인 요청의 버튼을 가리지 않게 한다.
        if not self._awaiting_approval:
            self.hide()

    def _load_steps(self, steps: list) -> None:
        self._steps.clear()
        self._targets.clear()
        for s in steps:
            # 오케스트레이터는 ActionStep을 asdict()로 넘긴다.
            self._steps[s["step_id"]] = {
                "desc": s.get("description_kr", ""),
                "type": s.get("step_type", ""),
                "status": "pending",
            }
            self._targets[s["step_id"]] = (list(s.get("reads") or []), list(s.get("writes") or []))
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
            text = f"{icon} {info['desc'][:60]}"
            if self._awaiting_approval:
                reads, writes = self._targets.get(sid, ([], []))
                for label, targets in ((_("읽기"), reads), (_("쓰기"), writes)):
                    if targets:
                        text += f"\n    {label}: {', '.join(str(t) for t in targets)[:120]}"
            lbl = QLabel(text)
            lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
            lbl.setStyleSheet(f"color: {color};")
            # 긴 단계 설명이 채팅창의 최소 폭을 넓히지 않게 줄바꿈한다.
            lbl.setWordWrap(True)
            lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            self._steps_lay.addWidget(lbl)

    def reset(self) -> None:
        self._awaiting_approval = False
        self._approval_widget.hide()
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



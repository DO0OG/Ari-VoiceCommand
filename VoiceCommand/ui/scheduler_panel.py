"""
스케줄러 관리 패널 (Scheduler Panel)
예약 작업 목록 조회, 추가, 삭제, 활성화 토글 UI입니다.
FloatingPanel 기반 클래스를 사용해 구조를 공유합니다.
"""
import logging
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from ui.common import (
    FloatingPanel, clear_layout, create_input_field,
    create_icon_button, show_temp_status,
)
from ui.theme import (
    FONT_KO, FONT_SIZE_NORMAL, FONT_SIZE_SMALL,
    COLOR_PRIMARY, COLOR_SUCCESS, COLOR_DANGER, COLOR_MUTED,
    COLOR_BG_WHITE, COLOR_BORDER_CARD,
    SCROLLBAR_THIN_STYLE, primary_btn_style,
    WINDOW_W_SCHEDULER, WINDOW_H_SCHEDULER,
)

logger = logging.getLogger(__name__)


class TaskRow(QFrame):
    """예약 작업 한 행 위젯."""

    toggle_requested  = Signal(str)
    delete_requested  = Signal(str)
    run_now_requested = Signal(str)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task_id = task.task_id
        self._build_ui(task)

    def _build_ui(self, task) -> None:
        self.setStyleSheet(f"""
            QFrame {{ background: {COLOR_BG_WHITE}; border-radius: 10px;
                      border: 1px solid {COLOR_BORDER_CARD}; }}
            QFrame:hover {{ border: 1px solid {COLOR_PRIMARY}; }}
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(4)

        # 이름 + 액션 버튼 행
        top = QHBoxLayout()
        name_lbl = QLabel(f"📋 {task.name}")
        name_lbl.setFont(QFont(FONT_KO, FONT_SIZE_NORMAL, QFont.Bold))
        top.addWidget(name_lbl)
        top.addStretch()

        top.addWidget(create_icon_button(
            "▶", "지금 실행", 28, COLOR_SUCCESS,
            lambda: self.run_now_requested.emit(self.task_id)
        ))
        toggle_color = COLOR_PRIMARY if task.enabled else COLOR_MUTED
        toggle_icon  = "⏸" if task.enabled else "▷"
        top.addWidget(create_icon_button(
            toggle_icon, "활성화/비활성화", 28, toggle_color,
            lambda: self.toggle_requested.emit(self.task_id)
        ))
        top.addWidget(create_icon_button(
            "✕", "삭제", 28, COLOR_DANGER,
            lambda: self.delete_requested.emit(self.task_id)
        ))
        outer.addLayout(top)

        # 목표 텍스트 (축약)
        goal_lbl = QLabel(task.goal[:60] + ("…" if len(task.goal) > 60 else ""))
        goal_lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
        goal_lbl.setStyleSheet("color: #555;")
        outer.addWidget(goal_lbl)

        # 스케줄 + 다음 실행 시각
        try:
            next_str = datetime.fromisoformat(task.next_run).strftime("%m/%d %H:%M")
        except Exception:
            next_str = task.next_run
        info_color = COLOR_PRIMARY if task.enabled else COLOR_MUTED
        info_lbl = QLabel(f"🕐 {task.schedule_expr}  →  다음 {next_str}")
        info_lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
        info_lbl.setStyleSheet(f"color: {info_color};")
        outer.addWidget(info_lbl)

        # 마지막 실행 결과
        if task.last_run:
            try:
                last_str = datetime.fromisoformat(task.last_run).strftime("%m/%d %H:%M")
            except Exception:
                last_str = task.last_run
            snippet = task.last_result[:50] + ("…" if len(task.last_result) > 50 else "")
            result_lbl = QLabel(f"✅ 마지막: {last_str}  |  {snippet}")
            result_lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
            result_lbl.setStyleSheet(f"color: {COLOR_SUCCESS};")
            outer.addWidget(result_lbl)


class SchedulerPanel(FloatingPanel):
    """예약 작업 관리 패널."""

    def __init__(self, scheduler=None, parent=None):
        super().__init__("📅  예약 작업 관리", WINDOW_W_SCHEDULER, WINDOW_H_SCHEDULER, parent)
        self._scheduler = scheduler
        self._build_content()
        self._connect_signals()
        self._refresh_list()

    # ── 콘텐츠 구성 ───────────────────────────────────────────────────────────

    def _build_content(self) -> None:
        # 작업 목록 스크롤 영역
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(SCROLLBAR_THIN_STYLE)
        self._scroll = scroll

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setAlignment(Qt.AlignTop)
        self._list_layout.setSpacing(8)
        self._list_layout.setContentsMargins(12, 12, 12, 8)
        scroll.setWidget(self._list_widget)
        self.content_layout.addWidget(scroll)

        # 작업 추가 폼
        form = QFrame()
        form.setStyleSheet(f"""
            QFrame {{ background: white; border-top: 1px solid #eee;
                      border-bottom-left-radius: 14px;
                      border-bottom-right-radius: 14px; }}
        """)
        form_lay = QVBoxLayout(form)
        form_lay.setContentsMargins(14, 12, 14, 14)
        form_lay.setSpacing(8)

        add_title = QLabel("새 작업 추가")
        add_title.setFont(QFont(FONT_KO, FONT_SIZE_SMALL, QFont.Bold))
        add_title.setStyleSheet(f"color: {COLOR_PRIMARY};")
        form_lay.addWidget(add_title)

        self._name_input  = create_input_field("작업 이름 (예: 뉴스 요약)")
        self._goal_input  = create_input_field("목표 (예: 최신 뉴스를 요약해서 저장해줘)")
        self._sched_input = create_input_field("스케줄 (예: 매일 09:00  /  매주 월요일 09:00  /  30분마다)")
        for w in (self._name_input, self._goal_input, self._sched_input):
            form_lay.addWidget(w)

        add_btn = QPushButton("+ 작업 추가")
        add_btn.setFixedHeight(36)
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setFont(QFont(FONT_KO, FONT_SIZE_SMALL, QFont.Bold))
        add_btn.setStyleSheet(primary_btn_style())
        add_btn.clicked.connect(self._on_add)
        form_lay.addWidget(add_btn)

        self._status_lbl = QLabel("")
        self._status_lbl.setFont(QFont(FONT_KO, FONT_SIZE_SMALL))
        self._status_lbl.setStyleSheet(f"color: {COLOR_MUTED};")
        form_lay.addWidget(self._status_lbl)

        self.content_layout.addWidget(form)

    # ── 시그널 연결 ───────────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        if not self._scheduler:
            return
        self._scheduler.tasks_changed.connect(self._refresh_list)
        self._scheduler.task_triggered.connect(
            lambda _, goal: show_temp_status(self._status_lbl, f"▶ 실행 중: {goal[:30]}…")
        )
        self._scheduler.task_completed.connect(
            lambda _, result, ok: show_temp_status(
                self._status_lbl,
                f"{'✅' if ok else '⚠️'} 완료: {result[:40]}"
            )
        )

    # ── 이벤트 핸들러 ────────────────────────────────────────────────────────

    def _on_add(self) -> None:
        name  = self._name_input.text().strip()
        goal  = self._goal_input.text().strip()
        sched = self._sched_input.text().strip()
        if not (name and goal and sched):
            show_temp_status(self._status_lbl, "⚠️ 이름·목표·스케줄을 모두 입력해주세요.")
            return
        if not self._scheduler:
            show_temp_status(self._status_lbl, "⚠️ 스케줄러가 연결되지 않았습니다.")
            return
        try:
            self._scheduler.add_task(name, goal, sched)
            for w in (self._name_input, self._goal_input, self._sched_input):
                w.clear()
            show_temp_status(self._status_lbl, f"✅ '{name}' 등록 완료")
        except Exception as e:
            show_temp_status(self._status_lbl, f"⚠️ 등록 실패: {e}")

    def _refresh_list(self) -> None:
        clear_layout(self._list_layout)
        tasks = self._scheduler.list_tasks() if self._scheduler else []
        if not tasks:
            empty = QLabel("등록된 예약 작업이 없습니다.")
            empty.setFont(QFont(FONT_KO, FONT_SIZE_NORMAL))
            empty.setStyleSheet(f"color: {COLOR_MUTED}; padding: 20px;")
            empty.setAlignment(Qt.AlignCenter)
            self._list_layout.addWidget(empty)
            return
        for task in sorted(tasks, key=lambda t: t.next_run):
            row = TaskRow(task)
            row.toggle_requested.connect(lambda tid: self._scheduler and self._scheduler.toggle_task(tid))
            row.delete_requested.connect(lambda tid: self._scheduler and self._scheduler.remove_task(tid))
            row.run_now_requested.connect(self._on_run_now)
            self._list_layout.addWidget(row)

    def _on_run_now(self, task_id: str) -> None:
        if self._scheduler and self._scheduler.run_task_now(task_id):
            show_temp_status(self._status_lbl, "▶ 즉시 실행 요청됨")

    def refresh_theme(self) -> None:
        name_text = self._name_input.text() if hasattr(self, "_name_input") else ""
        goal_text = self._goal_input.text() if hasattr(self, "_goal_input") else ""
        sched_text = self._sched_input.text() if hasattr(self, "_sched_input") else ""
        self.refresh_shell_theme()
        clear_layout(self.content_layout)
        self._build_content()
        self._name_input.setText(name_text)
        self._goal_input.setText(goal_text)
        self._sched_input.setText(sched_text)
        self._refresh_list()

"""예약 작업 목록을 표 형태로 확인하고 취소하는 다이얼로그."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHBoxLayout, QHeaderView, QMessageBox,
)

from i18n.translator import _


class ScheduledTasksDialog(QDialog):
    """예약 작업 목록 확인·취소 다이얼로그."""

    def __init__(self, scheduler, parent=None):
        super().__init__(parent)
        self._scheduler = scheduler
        self.setWindowTitle(_("예약 작업 관리"))
        self.resize(640, 420)
        self._build_ui()
        self._refresh()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(5000)

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels([_("작업 내용"), _("실행 예정 시각"), _("남은 시간")])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._table.setWordWrap(True)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self._table)

        btn_layout = QHBoxLayout()
        self._btn_cancel_task = QPushButton(_("선택 작업 취소"))
        self._btn_cancel_task.clicked.connect(self._cancel_selected)
        self._btn_refresh = QPushButton(_("새로 고침"))
        self._btn_refresh.clicked.connect(self._refresh)
        btn_layout.addWidget(self._btn_cancel_task)
        btn_layout.addStretch()
        btn_layout.addWidget(self._btn_refresh)
        layout.addLayout(btn_layout)

    def _refresh(self):
        tasks = self._scheduler.list_tasks() if self._scheduler and hasattr(self._scheduler, "list_tasks") else []
        self._table.setRowCount(len(tasks))
        now = datetime.now()
        for row, task in enumerate(sorted(tasks, key=lambda item: item.next_run)):
            try:
                scheduled_at = datetime.fromisoformat(task.next_run)
                scheduled_text = scheduled_at.strftime("%Y-%m-%d %H:%M:%S")
                remaining_seconds = max(0.0, (scheduled_at - now).total_seconds())
            except Exception:
                scheduled_text = task.next_run
                remaining_seconds = 0.0
            self._table.setItem(row, 0, QTableWidgetItem(task.goal))
            self._table.setItem(row, 1, QTableWidgetItem(scheduled_text))
            self._table.setItem(row, 2, QTableWidgetItem(_format_remaining(remaining_seconds)))
            self._table.item(row, 0).setData(Qt.UserRole, task.task_id)
        self._table.resizeRowsToContents()
        self._btn_cancel_task.setEnabled(bool(tasks))

    def _cancel_selected(self):
        row = self._table.currentRow()
        if row < 0:
            return
        task_item = self._table.item(row, 0)
        task_id = task_item.data(Qt.UserRole)
        task_desc = task_item.text()
        reply = QMessageBox.question(
            self,
            _("작업 취소"),
            _("'{task}' 작업을 취소하시겠습니까?").format(task=task_desc),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes and self._scheduler:
            self._scheduler.cancel_task(task_id)
            self._refresh()

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)


def _format_remaining(seconds: float) -> str:
    if seconds <= 0:
        return _("곧 실행")
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if hours:
        parts.append(_("{n}시간").format(n=hours))
    if minutes:
        parts.append(_("{n}분").format(n=minutes))
    if secs:
        parts.append(_("{n}초").format(n=secs))
    return " ".join(parts) + " " + _("후")

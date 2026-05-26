"""에이전트 실행 진행 상황 대시보드."""

from __future__ import annotations

import json

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QLabel, QListWidget, QPushButton, QPlainTextEdit, QVBoxLayout

from i18n.translator import _


class AgentDashboard(QDialog):
    def __init__(self, orchestrator, goal: str, parent=None):
        super().__init__(parent)
        self.orchestrator = orchestrator
        self.setWindowTitle(_("에이전트 대시보드"))
        self.setMinimumSize(520, 420)

        layout = QVBoxLayout(self)
        self.goal_label = QLabel(goal)
        self.goal_label.setWordWrap(True)
        layout.addWidget(self.goal_label)

        self.steps = QListWidget()
        layout.addWidget(self.steps)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)

        self.stop_btn = QPushButton(_("중지"))
        self.stop_btn.clicked.connect(self.orchestrator.interrupt)
        layout.addWidget(self.stop_btn)

    def handle_progress(self, event_type: str, **payload) -> None:
        if event_type == "plan_ready":
            self.steps.clear()
            for step in payload.get("steps", []):
                desc = step.get("description_kr") or step.get("content") or str(step.get("step_id", ""))
                self.steps.addItem(f"⏳ {desc}")
        elif event_type in {"achieved", "interrupted", "not_achieved", "replan", "verify_start"}:
            self.output.appendPlainText(f"{event_type}: {json.dumps(payload, ensure_ascii=False, default=str)}")
        else:
            self.output.appendPlainText(f"{event_type}: {json.dumps(payload, ensure_ascii=False, default=str)}")

        if event_type == "achieved":
            QTimer.singleShot(3000, self.accept)

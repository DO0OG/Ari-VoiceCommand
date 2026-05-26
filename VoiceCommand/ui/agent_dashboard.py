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

        # step_id → QListWidget 행 인덱스 매핑
        self._step_row: dict[str, int] = {}

    def handle_progress(self, event_type: str, **payload) -> None:
        if event_type == "plan_ready":
            self.steps.clear()
            self._step_row.clear()
            for idx, step in enumerate(payload.get("steps", [])):
                step_id = str(step.get("step_id", idx))
                desc = step.get("description_kr") or step.get("content") or step_id
                self.steps.addItem(f"⏳ {desc}")
                self._step_row[step_id] = idx

        elif event_type == "step_start":
            step_id = str(payload.get("step_id", ""))
            row = self._step_row.get(step_id)
            if row is not None:
                item = self.steps.item(row)
                if item:
                    text = item.text()
                    if text.startswith("⏳ "):
                        item.setText("🔄 " + text[3:])

        elif event_type == "step_done":
            step_id = str(payload.get("step_id", ""))
            row = self._step_row.get(step_id)
            if row is not None:
                item = self.steps.item(row)
                if item:
                    text = item.text()
                    icon = "✅" if payload.get("success", True) else "❌"
                    for prefix in ("⏳ ", "🔄 ", "✅ ", "❌ "):
                        if text.startswith(prefix):
                            item.setText(icon + " " + text[len(prefix):])
                            break
                    else:
                        item.setText(icon + " " + text)

        elif event_type in {"achieved", "interrupted", "not_achieved", "replan", "verify_start"}:
            self.output.appendPlainText(f"{event_type}: {json.dumps(payload, ensure_ascii=False, default=str)}")

        else:
            self.output.appendPlainText(f"{event_type}: {json.dumps(payload, ensure_ascii=False, default=str)}")

        if event_type == "achieved":
            QTimer.singleShot(3000, self.accept)

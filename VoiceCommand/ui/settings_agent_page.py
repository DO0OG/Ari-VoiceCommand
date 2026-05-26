"""에이전트 실행 설정 페이지."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QGroupBox, QLabel, QLineEdit, QSlider, QSpinBox, QVBoxLayout, QWidget

from i18n.translator import _


class _AgentSettingsPage(QWidget):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        layout = QVBoxLayout(self)

        group = QGroupBox(_("에이전트 실행"))
        box = QVBoxLayout(group)

        self.timeout_label = QLabel("")
        self.timeout_slider = QSlider(Qt.Horizontal)
        self.timeout_slider.setRange(30, 600)
        self.timeout_slider.setSingleStep(10)
        self.timeout_slider.setPageStep(30)
        self.timeout_slider.setValue(int(settings.get("agent_timeout_seconds", 120)))
        self.timeout_slider.valueChanged.connect(self._update_timeout_label)
        box.addWidget(QLabel(_("전체 실행 타임아웃 (초)")))
        box.addWidget(self.timeout_slider)
        box.addWidget(self.timeout_label)

        self.dashboard_checkbox = QCheckBox(_("에이전트 대시보드 사용"))
        self.dashboard_checkbox.setChecked(bool(settings.get("agent_dashboard_enabled", True)))
        box.addWidget(self.dashboard_checkbox)

        self.audit_checkbox = QCheckBox(_("도구 실행 감사 로그 기록"))
        self.audit_checkbox.setChecked(bool(settings.get("audit_log_enabled", True)))
        box.addWidget(self.audit_checkbox)

        self.mcp_checkbox = QCheckBox(_("로컬 MCP 서버 사용"))
        self.mcp_checkbox.setChecked(bool(settings.get("mcp_server_enabled", False)))
        box.addWidget(self.mcp_checkbox)

        self.subagent_spin = QSpinBox()
        self.subagent_spin.setRange(1, 8)
        self.subagent_spin.setValue(int(settings.get("max_subagents", 3)))
        box.addWidget(QLabel(_("settings.agent.max_subagents")))
        box.addWidget(self.subagent_spin)

        self.google_checkbox = QCheckBox(_("settings.agent.google_tools"))
        self.google_checkbox.setChecked(bool(settings.get("google_calendar_enabled", False)))
        box.addWidget(self.google_checkbox)
        self.google_client_id = QLineEdit(str(settings.get("google_client_id", "") or ""))
        self.google_client_id.setPlaceholderText(_("settings.agent.google_client_id"))
        box.addWidget(self.google_client_id)
        self.google_client_secret = QLineEdit(str(settings.get("google_client_secret", "") or ""))
        self.google_client_secret.setPlaceholderText(_("settings.agent.google_client_secret"))
        self.google_client_secret.setEchoMode(QLineEdit.Password)
        box.addWidget(self.google_client_secret)

        self.image_checkbox = QCheckBox(_("settings.agent.image_generation"))
        self.image_checkbox.setChecked(bool(settings.get("image_generation_enabled", False)))
        box.addWidget(self.image_checkbox)
        self.image_provider = QLineEdit(str(settings.get("image_gen_provider", "openai") or "openai"))
        box.addWidget(self.image_provider)

        layout.addWidget(group)
        layout.addStretch(1)
        self._update_timeout_label(self.timeout_slider.value())

    def _update_timeout_label(self, value: int) -> None:
        self.timeout_label.setText(_("{seconds}초").format(seconds=int(value)))

    def get_values(self) -> dict:
        return {
            "agent_timeout_seconds": int(self.timeout_slider.value()),
            "agent_dashboard_enabled": self.dashboard_checkbox.isChecked(),
            "audit_log_enabled": self.audit_checkbox.isChecked(),
            "mcp_server_enabled": self.mcp_checkbox.isChecked(),
            "max_subagents": int(self.subagent_spin.value()),
            "google_calendar_enabled": self.google_checkbox.isChecked(),
            "google_client_id": self.google_client_id.text().strip(),
            "google_client_secret": self.google_client_secret.text().strip(),
            "image_generation_enabled": self.image_checkbox.isChecked(),
            "image_gen_provider": self.image_provider.text().strip() or "openai",
        }

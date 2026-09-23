"""에이전트 실행 설정 페이지."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from i18n.translator import _


def _live_decision_engine():
    """Return the running local decision engine without importing the app core."""
    state = getattr(sys.modules.get("core.VoiceCommand"), "_state", None)
    registry = getattr(state, "command_registry", None)
    for command in getattr(registry, "commands", ()) or ():
        engine = getattr(command, "_decision_engine", None)
        if engine is not None:
            return engine
    return None


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
        layout.addWidget(self._build_local_decision_group(settings))
        layout.addStretch(1)
        self._update_timeout_label(self.timeout_slider.value())

    def _build_local_decision_group(self, settings: dict) -> QGroupBox:
        group = QGroupBox(_("빠른 로컬 처리"))
        box = QVBoxLayout(group)
        mode = settings.get("local_decision_mode", "off")
        if mode not in ("off", "shadow", "fast"):
            mode = "off"
        direct = settings.get("local_decision_direct_execution") is True

        self.local_decision_checkbox = QCheckBox(_("간단한 명령을 로컬에서 바로 처리"))
        self.local_decision_checkbox.setChecked(mode == "fast" and direct)
        box.addWidget(self.local_decision_checkbox)
        note = QLabel(_("사람 검수와 실사용 검증을 마치기 전까지 기본값은 꺼짐입니다."))
        note.setWordWrap(True)
        box.addWidget(note)

        box.addWidget(QLabel(_("고급: 동작 모드")))
        self.local_decision_mode = QComboBox()
        for value, label in (("off", _("끄기")), ("shadow", _("기록만 (진단용)")), ("fast", _("빠른 처리"))):
            self.local_decision_mode.addItem(label, value)
        self.local_decision_mode.setCurrentIndex(self.local_decision_mode.findData(mode))
        box.addWidget(self.local_decision_mode)
        # One toggle writes both stored values; the advanced list follows it.
        self.local_decision_checkbox.toggled.connect(self._on_local_decision_toggled)
        self.local_decision_mode.currentIndexChanged.connect(
            lambda _index: self.local_decision_checkbox.setChecked(
                self.local_decision_mode.currentData() == "fast"
            )
        )

        self.local_decision_status = QLabel("")
        box.addWidget(self.local_decision_status)
        reload_button = QPushButton(_("모델 다시 불러오기"))
        reload_button.clicked.connect(self._reload_local_decision)
        box.addWidget(reload_button)
        self._refresh_local_decision_status()
        return group

    def _on_local_decision_toggled(self, checked: bool) -> None:
        current = self.local_decision_mode.currentData()
        # Unchecking only leaves fast; a diagnostic shadow choice made in the list stays.
        if checked and current != "fast":
            target = "fast"
        elif not checked and current == "fast":
            target = "off"
        else:
            return
        self.local_decision_mode.setCurrentIndex(self.local_decision_mode.findData(target))

    def _refresh_local_decision_status(self) -> None:
        engine = _live_decision_engine()
        health = engine.health() if engine is not None else {"state": "not_loaded", "error_code": ""}
        if health.get("state") == "ready":
            text = _("로컬 판단 모델: 준비됨")
        elif health.get("state") == "error":
            text = _("로컬 판단 모델: 오류 ({code})").format(code=health.get("error_code") or "-")
        else:
            text = _("로컬 판단 모델: 아직 불러오지 않음")
        self.local_decision_status.setText(text)

    def _reload_local_decision(self) -> None:
        engine = _live_decision_engine()
        if engine is not None:
            engine.reload()
        self._refresh_local_decision_status()

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
            "local_decision_mode": self.local_decision_mode.currentData() or "off",
            "local_decision_direct_execution": self.local_decision_mode.currentData() == "fast",
        }

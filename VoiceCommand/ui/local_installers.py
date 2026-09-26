"""설정창용 로컬 설치 UI 컴포넌트."""
from __future__ import annotations

import logging
from typing import Callable, Iterable

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QLabel,
    QHBoxLayout,
)

from i18n.translator import _
from ui.common import create_muted_label


def installer_btn_style() -> str:
    return """
        QPushButton {
            background-color: #1f6feb;
            color: white;
            font-weight: bold;
            font-size: 13px;
            border: none;
            border-radius: 10px;
            padding: 10px 16px;
        }
        QPushButton:hover {
            background-color: #2b7fff;
        }
        QPushButton:pressed {
            background-color: #195ec8;
        }
    """


class OllamaInstallerThread(QThread):
    done = Signal(bool, str, dict)

    def __init__(self, install_dir: str, models_dir: str, models: Iterable[str]):
        super().__init__()
        self.install_dir = install_dir.strip()
        self.models_dir = models_dir.strip()
        self.models = list(models)

    def run(self):
        try:
            from core.ollama_installer import install_ollama

            result = install_ollama(
                install_dir=self.install_dir or None,
                models_dir=self.models_dir or None,
                models=self.models,
            )
            model_text = ", ".join(result.get("installed_models", [])) or _("모델 설치 없음")
            self.done.emit(True, _("✓ Ollama 설치 완료 ({models})").format(models=model_text), result)
        except Exception as exc:
            self.done.emit(False, _("✗ Ollama 설치 실패: {error}").format(error=exc), {})


class CosyVoiceInstallerThread(QThread):
    done = Signal(bool, str, str)

    def __init__(self, install_dir: str):
        super().__init__()
        self.install_dir = install_dir.strip()

    def run(self):
        try:
            from core.cosyvoice_installer import install_cosyvoice

            installed_path = install_cosyvoice(self.install_dir)
            self.done.emit(True, _("✓ CosyVoice3 설치 완료"), installed_path)
        except Exception as exc:
            self.done.emit(False, _("✗ CosyVoice3 설치 실패: {error}").format(error=exc), "")


class OllamaInstallDialog(QDialog):
    def __init__(self, parent=None, installed: bool = False):
        super().__init__(parent)
        self._installed = installed
        self.setWindowTitle(_("Ollama 모델 받기") if installed else _("Ollama 설치"))
        self.setMinimumWidth(520)
        self._build_ui()

    def _build_ui(self):
        from core.ollama_installer import COMMON_OLLAMA_MODELS

        layout = QVBoxLayout(self)
        if self._installed:
            layout.addWidget(create_muted_label(
                _("Ollama가 이미 설치되어 있습니다. 받을 모델을 선택하세요.")
            ))
        else:
            layout.addWidget(create_muted_label(
                _("Ollama를 설치하고, 사용할 모델을 함께 받아옵니다. ") +
                _("모델은 여러 개 선택할 수 있고, 설치 후 바로 설정값에 반영됩니다.")
            ))

        layout.addWidget(QLabel(_("권장 모델 선택:")))
        self.model_list = QListWidget()
        for option in COMMON_OLLAMA_MODELS:
            item = QListWidgetItem(f"{option.label}  [{option.model}]  -  {option.summary}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if option.model == "llama3.2:3b" else Qt.CheckState.Unchecked)
            item.setData(Qt.UserRole, option.model)
            self.model_list.addItem(item)
        self.model_list.setMinimumHeight(160)
        layout.addWidget(self.model_list)

        layout.addWidget(QLabel(_("추가 모델명 (쉼표로 여러 개 입력 가능):")))
        self.custom_models_input = QLineEdit()
        self.custom_models_input.setPlaceholderText(_("예: qwen2.5-coder:7b, mistral-small"))
        layout.addWidget(self.custom_models_input)

        if self._installed:
            # 이미 설치돼 있으면 설치 단계를 건너뛰므로 설치 경로는 묻지 않는다.
            self.install_dir_input = QLineEdit()
        else:
            layout.addWidget(QLabel(_("Ollama 설치 경로 (선택):")))
            self.install_dir_input = self._build_path_input(
                layout,
                placeholder=_("비워두면 Ollama 기본 경로 사용"),
                title=_("Ollama 설치 폴더 선택"),
            )

        layout.addWidget(QLabel(_("모델 저장 경로 (선택):")))
        self.models_dir_input = self._build_path_input(
            layout,
            placeholder=_("비워두면 기본 모델 경로 사용"),
            title=_("Ollama 모델 폴더 선택"),
        )

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_path_input(self, layout: QVBoxLayout, placeholder: str, title: str) -> QLineEdit:

        row = QHBoxLayout()
        path_input = QLineEdit()
        path_input.setPlaceholderText(placeholder)
        row.addWidget(path_input)
        browse_btn = QPushButton(_("찾아보기"))
        browse_btn.setFixedWidth(72)
        browse_btn.clicked.connect(lambda: self._browse_dir(path_input, title))
        row.addWidget(browse_btn)
        layout.addLayout(row)
        return path_input

    def _browse_dir(self, target_input: QLineEdit, title: str):
        path = QFileDialog.getExistingDirectory(self, title, target_input.text() or "C:/")
        if path:
            target_input.setText(path)

    def selected_models(self) -> list[str]:
        from core.ollama_installer import normalize_models

        selected = []
        for index in range(self.model_list.count()):
            item = self.model_list.item(index)
            if item.checkState() == Qt.Checked:
                selected.append(item.data(Qt.UserRole))
        custom = self.custom_models_input.text().strip()
        if custom:
            selected.extend(part.strip() for part in custom.split(","))
        return normalize_models(selected)


class LocalInstallDetectThread(QThread):
    """이미 설치된 Ollama와 CosyVoice3를 UI 스레드 밖에서 찾는다."""

    done = Signal(object)

    def __init__(self, configured_cosyvoice_dir: str):
        super().__init__()
        self.configured_cosyvoice_dir = configured_cosyvoice_dir.strip()

    def run(self):
        result = {"ollama_path": "", "ollama_models": None, "cosyvoice_dir": ""}
        try:
            from core.ollama_installer import find_ollama_executable, list_installed_models

            result["ollama_path"] = find_ollama_executable() or ""
            if result["ollama_path"]:
                result["ollama_models"] = list_installed_models()
        except Exception as exc:
            logging.debug("Ollama 설치 확인 실패: %s", exc)
        try:
            from core.cosyvoice_installer import find_cosyvoice_dir

            result["cosyvoice_dir"] = find_cosyvoice_dir(self.configured_cosyvoice_dir)
        except Exception as exc:
            logging.debug("CosyVoice 설치 확인 실패: %s", exc)
        self.done.emit(result)


class LocalInstallSection(QGroupBox):
    ollama_install_requested = Signal()
    cosyvoice_install_requested = Signal()
    ollama_locate_requested = Signal()
    detection_finished = Signal(object)

    def __init__(self, parent=None, cosyvoice_dir_provider: Callable[[], str] | None = None):
        super().__init__(_("로컬 설치"), parent)
        self._cosyvoice_dir_provider = cosyvoice_dir_provider or (lambda: "")
        self._detect_thread: LocalInstallDetectThread | None = None
        self.ollama_path = ""
        self.cosyvoice_dir = ""
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(create_muted_label(
            _("로컬에서 직접 실행할 엔진을 먼저 설치한 뒤, 아래 설정에서 경로와 모델을 조정할 수 있습니다.")
        ))
        self.redetect_btn = QPushButton(_("다시 찾기"))
        self.redetect_btn.clicked.connect(self.start_detection)
        layout.addWidget(self.redetect_btn)

        layout.addWidget(self._build_card(
            title="Ollama",
            description=_("로컬 LLM 엔진 설치와 모델 다운로드를 한 번에 진행합니다."),
            button_text=_("Ollama 설치/모델 받기"),
            click_handler=self.ollama_install_requested.emit,
        ))
        layout.addWidget(self._build_card(
            title="CosyVoice3",
            description=_("로컬 TTS 엔진과 기본 모델을 설치하고 설정 경로를 자동으로 맞춥니다."),
            button_text=_("CosyVoice 설치"),
            click_handler=self.cosyvoice_install_requested.emit,
        ))

    def _build_card(self, title: str, description: str, button_text: str, click_handler) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.addWidget(create_muted_label(description))
        status = create_muted_label("")
        layout.addWidget(status)
        button = QPushButton(button_text)
        button.setMinimumHeight(42)
        button.setStyleSheet(installer_btn_style())
        button.clicked.connect(click_handler)
        layout.addWidget(button)
        if title == "Ollama":
            self.ollama_install_btn = button
            self.ollama_status = status
            self.ollama_models_label = create_muted_label("")
            layout.insertWidget(layout.indexOf(status) + 1, self.ollama_models_label)
            self.ollama_locate_btn = QPushButton(_("위치 지정"))
            self.ollama_locate_btn.clicked.connect(self.ollama_locate_requested.emit)
            layout.addWidget(self.ollama_locate_btn)
        else:
            self.cosyvoice_install_btn = button
            self.cosyvoice_status = status
        return group

    # ── 설치 상태 확인 ─────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self.start_detection()

    def start_detection(self):
        """설치 상태를 백그라운드에서 다시 확인한다. 이미 확인 중이면 무시한다."""
        if self._detect_thread is not None:
            return
        self.ollama_status.setText(_("확인 중..."))
        self.ollama_models_label.setText("")
        self.cosyvoice_status.setText(_("확인 중..."))
        self.redetect_btn.setEnabled(False)
        self._detect_thread = LocalInstallDetectThread(self._cosyvoice_dir_provider())
        self._detect_thread.done.connect(self._on_detected)
        self._detect_thread.start()

    def stop_detection(self):
        """창이 닫힐 때 확인 스레드가 끝나기를 잠시 기다린다."""
        if self._detect_thread is not None and self._detect_thread.isRunning():
            self._detect_thread.wait(3000)

    def _on_detected(self, result: dict):
        thread, self._detect_thread = self._detect_thread, None
        if thread is not None:
            thread.wait()
            thread.deleteLater()
        self.redetect_btn.setEnabled(True)
        self.ollama_path = result.get("ollama_path") or ""
        self.cosyvoice_dir = result.get("cosyvoice_dir") or ""
        self.ollama_status.setText(_status_text(self.ollama_path))
        self.ollama_models_label.setText(_models_text(self.ollama_path, result.get("ollama_models")))
        self.ollama_install_btn.setText(_("모델 받기") if self.ollama_path else _("Ollama 설치/모델 받기"))
        self.cosyvoice_status.setText(_status_text(self.cosyvoice_dir))
        self.detection_finished.emit(result)


def _status_text(path: str) -> str:
    return _("설치됨: {path}", path=path) if path else _("설치되지 않음")


def _models_text(ollama_path: str, models: list[str] | None) -> str:
    if not ollama_path:
        return ""
    if models is None:
        return _("Ollama 서버가 응답하지 않아 설치된 모델을 확인하지 못했습니다.")
    if not models:
        return _("설치된 모델이 없습니다.")
    return _("설치된 모델: {models}", models=", ".join(models))

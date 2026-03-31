"""설정창용 로컬 설치 UI 컴포넌트."""
from __future__ import annotations

from typing import Iterable

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
)

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
            model_text = ", ".join(result.get("installed_models", [])) or "모델 설치 없음"
            self.done.emit(True, f"✓ Ollama 설치 완료 ({model_text})", result)
        except Exception as exc:
            self.done.emit(False, f"✗ Ollama 설치 실패: {exc}", {})


class CosyVoiceInstallerThread(QThread):
    done = Signal(bool, str, str)

    def __init__(self, install_dir: str):
        super().__init__()
        self.install_dir = install_dir.strip()

    def run(self):
        try:
            from core.cosyvoice_installer import install_cosyvoice

            installed_path = install_cosyvoice(self.install_dir)
            self.done.emit(True, "✓ CosyVoice3 설치 완료", installed_path)
        except Exception as exc:
            self.done.emit(False, f"✗ CosyVoice3 설치 실패: {exc}", "")


class OllamaInstallDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ollama 설치")
        self.setMinimumWidth(520)
        self._build_ui()

    def _build_ui(self):
        from core.ollama_installer import COMMON_OLLAMA_MODELS

        layout = QVBoxLayout(self)
        layout.addWidget(create_muted_label(
            "Ollama를 설치하고, 사용할 모델을 함께 받아옵니다. "
            "모델은 여러 개 선택할 수 있고, 설치 후 바로 설정값에 반영됩니다."
        ))

        layout.addWidget(QLabel("권장 모델 선택:"))
        self.model_list = QListWidget()
        for option in COMMON_OLLAMA_MODELS:
            item = QListWidgetItem(f"{option.label}  [{option.model}]  -  {option.summary}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if option.model == "llama3.2:3b" else Qt.Unchecked)
            item.setData(Qt.UserRole, option.model)
            self.model_list.addItem(item)
        self.model_list.setMinimumHeight(160)
        layout.addWidget(self.model_list)

        layout.addWidget(QLabel("추가 모델명 (쉼표로 여러 개 입력 가능):"))
        self.custom_models_input = QLineEdit()
        self.custom_models_input.setPlaceholderText("예: qwen2.5-coder:7b, mistral-small")
        layout.addWidget(self.custom_models_input)

        layout.addWidget(QLabel("Ollama 설치 경로 (선택):"))
        self.install_dir_input = self._build_path_input(
            layout,
            placeholder="비워두면 Ollama 기본 경로 사용",
            title="Ollama 설치 폴더 선택",
        )

        layout.addWidget(QLabel("모델 저장 경로 (선택):"))
        self.models_dir_input = self._build_path_input(
            layout,
            placeholder="비워두면 기본 모델 경로 사용",
            title="Ollama 모델 폴더 선택",
        )

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_path_input(self, layout: QVBoxLayout, placeholder: str, title: str) -> QLineEdit:
        from PySide6.QtWidgets import QHBoxLayout

        row = QHBoxLayout()
        path_input = QLineEdit()
        path_input.setPlaceholderText(placeholder)
        row.addWidget(path_input)
        browse_btn = QPushButton("찾아보기")
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


class LocalInstallSection(QGroupBox):
    ollama_install_requested = Signal()
    cosyvoice_install_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("로컬 설치", parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(create_muted_label(
            "로컬에서 직접 실행할 엔진을 먼저 설치한 뒤, 아래 설정에서 경로와 모델을 조정할 수 있습니다."
        ))

        layout.addWidget(self._build_card(
            title="Ollama",
            description="로컬 LLM 엔진 설치와 모델 다운로드를 한 번에 진행합니다.",
            button_text="Ollama 설치/모델 받기",
            click_handler=self.ollama_install_requested.emit,
        ))
        layout.addWidget(self._build_card(
            title="CosyVoice3",
            description="로컬 TTS 엔진과 기본 모델을 설치하고 설정 경로를 자동으로 맞춥니다.",
            button_text="CosyVoice 설치",
            click_handler=self.cosyvoice_install_requested.emit,
        ))

    def _build_card(self, title: str, description: str, button_text: str, click_handler) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.addWidget(create_muted_label(description))
        button = QPushButton(button_text)
        button.setMinimumHeight(42)
        button.setStyleSheet(installer_btn_style())
        button.clicked.connect(click_handler)
        layout.addWidget(button)
        if title == "Ollama":
            self.ollama_install_btn = button
        else:
            self.cosyvoice_install_btn = button
        return group

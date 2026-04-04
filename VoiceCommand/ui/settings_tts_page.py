"""
TTS 설정 페이지 위젯
"""
import logging
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QTextEdit, QPushButton, QComboBox, QGroupBox,
    QScrollArea, QProgressDialog, QMessageBox, QFileDialog,
)
from PySide6.QtCore import Qt

from ui.theme import SCROLLBAR_STYLE, secondary_btn_style
from ui.common import create_muted_label
from ui.local_installers import (
    CosyVoiceInstallerThread,
    LocalInstallSection,
    OllamaInstallDialog,
    OllamaInstallerThread,
)

# ── TTS 엔진 정의 ──────────────────────────────────────────────────────────────

TTS_MODES = [
    ("Fish Audio (API)",    "fish"),
    ("로컬 (CosyVoice3)",   "local"),
    ("OpenAI TTS",          "openai_tts"),
    ("ElevenLabs",          "elevenlabs"),
    ("Edge TTS (무료)",     "edge"),
]


class _TTSSettingsPage(QWidget):
    """TTS 엔진 설정 탭 위젯."""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._tts_groups: dict[str, QGroupBox] = {}
        self._ollama_install_thread: OllamaInstallerThread | None = None
        self._ollama_progress_dialog: QProgressDialog | None = None
        self._cosyvoice_install_thread: CosyVoiceInstallerThread | None = None
        self._cosyvoice_progress_dialog: QProgressDialog | None = None
        self._init_ui()

    # ── UI 구성 ───────────────────────────────────────────────────────────────

    def _init_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet(SCROLLBAR_STYLE)

        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setSpacing(15)

        # 로컬 설치 섹션
        self.local_install_section = LocalInstallSection(self)
        self.local_install_section.ollama_install_requested.connect(self._open_ollama_installer)
        self.local_install_section.cosyvoice_install_requested.connect(self._install_cosyvoice)
        vbox.addWidget(self.local_install_section)

        # TTS 설정 그룹
        tts_group = QGroupBox("음성 합성 (TTS) 설정")
        tts_vbox = QVBoxLayout(tts_group)

        tts_vbox.addWidget(QLabel("TTS 엔진 선택:"))
        self.tts_mode_combo = QComboBox()
        for label, data in TTS_MODES:
            self.tts_mode_combo.addItem(label, data)
        self._set_combo(self.tts_mode_combo, self._settings.get("tts_mode", "fish"))
        self.tts_mode_combo.currentIndexChanged.connect(self._on_tts_changed)
        tts_vbox.addWidget(self.tts_mode_combo)

        # Fish Audio 설정
        fish_grp = QGroupBox("Fish Audio 설정")
        fl = QVBoxLayout(fish_grp)
        fl.addWidget(QLabel("API Key:"))
        self.fish_key_input = QLineEdit(self._settings.get("fish_api_key", ""))
        self.fish_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        fl.addWidget(self.fish_key_input)
        fl.addWidget(QLabel("Reference ID:"))
        self.fish_ref_input = QLineEdit(self._settings.get("fish_reference_id", ""))
        fl.addWidget(self.fish_ref_input)
        tts_vbox.addWidget(fish_grp)
        self._tts_groups["fish"] = fish_grp

        # CosyVoice3 설정
        cv_grp = QGroupBox("CosyVoice3 설정 (로컬 GPU)")
        cvl = QVBoxLayout(cv_grp)
        cvl.addWidget(QLabel("CosyVoice 설치 경로 (비워두면 자동 감지):"))
        dir_row = QHBoxLayout()
        self.cosyvoice_dir_input = QLineEdit(self._settings.get("cosyvoice_dir", ""))
        self.cosyvoice_dir_input.setPlaceholderText("예: C:/CosyVoice")
        dir_row.addWidget(self.cosyvoice_dir_input)
        browse_btn = QPushButton("찾아보기")
        browse_btn.setFixedWidth(72)
        browse_btn.setStyleSheet(secondary_btn_style())
        browse_btn.clicked.connect(self._browse_cosyvoice_dir)
        dir_row.addWidget(browse_btn)
        detect_btn = QPushButton("자동 감지")
        detect_btn.setFixedWidth(72)
        detect_btn.setStyleSheet(secondary_btn_style())
        detect_btn.clicked.connect(self._detect_cosyvoice_dir)
        dir_row.addWidget(detect_btn)
        cvl.addLayout(dir_row)
        self.cosyvoice_dir_status = create_muted_label("")
        cvl.addWidget(self.cosyvoice_dir_status)
        cvl.addWidget(QLabel("Reference WAV 텍스트 (Cross-lingual 시 비움):"))
        self.cosyvoice_ref_text = QTextEdit()
        self.cosyvoice_ref_text.setPlainText(self._settings.get("cosyvoice_reference_text", ""))
        self.cosyvoice_ref_text.setMaximumHeight(60)
        cvl.addWidget(self.cosyvoice_ref_text)
        cvl.addWidget(QLabel("말하기 속도 (0.7 ~ 1.2):"))
        self.cosyvoice_speed_input = QLineEdit(str(self._settings.get("cosyvoice_speed", 0.9)))
        cvl.addWidget(self.cosyvoice_speed_input)
        tts_vbox.addWidget(cv_grp)
        self._tts_groups["local"] = cv_grp

        # OpenAI TTS 설정
        oai_grp = QGroupBox("OpenAI TTS 설정")
        oail = QVBoxLayout(oai_grp)
        oail.addWidget(QLabel("API Key (선택):"))
        self.openai_tts_key_input = QLineEdit(self._settings.get("openai_tts_api_key", ""))
        self.openai_tts_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_tts_key_input.setPlaceholderText("비워두면 AI 설정을 따릅니다.")
        oail.addWidget(self.openai_tts_key_input)
        row = QHBoxLayout()
        row.addWidget(QLabel("목소리:"))
        self.openai_tts_voice_combo = QComboBox()
        for v in ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]:
            self.openai_tts_voice_combo.addItem(v, v)
        self._set_combo(self.openai_tts_voice_combo, self._settings.get("openai_tts_voice", "nova"))
        row.addWidget(self.openai_tts_voice_combo)
        row.addWidget(QLabel("모델:"))
        self.openai_tts_model_combo = QComboBox()
        for m in ["tts-1", "tts-1-hd"]:
            self.openai_tts_model_combo.addItem(m, m)
        self._set_combo(self.openai_tts_model_combo, self._settings.get("openai_tts_model", "tts-1"))
        row.addWidget(self.openai_tts_model_combo)
        oail.addLayout(row)
        tts_vbox.addWidget(oai_grp)
        self._tts_groups["openai_tts"] = oai_grp

        # ElevenLabs 설정
        el_grp = QGroupBox("ElevenLabs 설정")
        ell = QVBoxLayout(el_grp)
        ell.addWidget(QLabel("API Key:"))
        self.elevenlabs_key_input = QLineEdit(self._settings.get("elevenlabs_api_key", ""))
        self.elevenlabs_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        ell.addWidget(self.elevenlabs_key_input)
        ell.addWidget(QLabel("Voice ID:"))
        self.elevenlabs_voice_id_input = QLineEdit(self._settings.get("elevenlabs_voice_id", ""))
        ell.addWidget(self.elevenlabs_voice_id_input)
        tts_vbox.addWidget(el_grp)
        self._tts_groups["elevenlabs"] = el_grp

        # Edge TTS 설정
        edge_grp = QGroupBox("Edge TTS 설정 (무료)")
        edgel = QVBoxLayout(edge_grp)
        edgel.addWidget(QLabel("목소리 선택:"))
        self.edge_voice_combo = QComboBox()
        for vid, vlbl in [
            ("ko-KR-SunHiNeural", "SunHi (여성)"),
            ("ko-KR-InJoonNeural", "InJoon (남성)"),
            ("ko-KR-HyunsuNeural", "Hyunsu (남성)"),
        ]:
            self.edge_voice_combo.addItem(vlbl, vid)
        self._set_combo(self.edge_voice_combo, self._settings.get("edge_tts_voice", "ko-KR-SunHiNeural"))
        edgel.addWidget(self.edge_voice_combo)
        edgel.addWidget(QLabel("속도 (예: +0%, -10%):"))
        self.edge_rate_input = QLineEdit(self._settings.get("edge_tts_rate", "+0%"))
        edgel.addWidget(self.edge_rate_input)
        tts_vbox.addWidget(edge_grp)
        self._tts_groups["edge"] = edge_grp

        vbox.addWidget(tts_group)
        vbox.addStretch()

        scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._on_tts_changed()

    # ── 이벤트 핸들러 ─────────────────────────────────────────────────────────

    def _on_tts_changed(self):
        selected = self.tts_mode_combo.currentData()
        for key in [d for _, d in TTS_MODES]:
            grp = self._tts_groups.get(key)
            if grp:
                grp.setVisible(key == selected)

    def _open_ollama_installer(self):
        from PySide6.QtWidgets import QDialog
        dialog = OllamaInstallDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return

        selected_models = dialog.selected_models()
        if not selected_models:
            confirm = QMessageBox.question(
                self,
                "모델 없이 설치",
                "선택한 모델이 없습니다. Ollama 프로그램만 설치할까요?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return

        self._ollama_install_thread = OllamaInstallerThread(
            dialog.install_dir_input.text(),
            dialog.models_dir_input.text(),
            selected_models,
        )
        self._ollama_install_thread.done.connect(self._on_ollama_install_done)
        self._ollama_progress_dialog = QProgressDialog(
            "Ollama 설치를 준비 중입니다.\n설치 창이 뜨면 진행하고, 모델 다운로드는 콘솔 없이 백그라운드로 계속됩니다.",
            None, 0, 0, self,
        )
        self._ollama_progress_dialog.setWindowTitle("Ollama 설치")
        self._ollama_progress_dialog.setWindowModality(Qt.ApplicationModal)
        self._ollama_progress_dialog.setCancelButton(None)
        self._ollama_progress_dialog.setMinimumDuration(0)
        self._ollama_progress_dialog.show()
        self._ollama_install_thread.start()

    def _on_ollama_install_done(self, success: bool, message: str, result: dict):
        if self._ollama_progress_dialog is not None:
            self._ollama_progress_dialog.close()
            self._ollama_progress_dialog = None

        if success and result:
            QMessageBox.information(self, "Ollama 설치", message)
        else:
            QMessageBox.warning(self, "Ollama 설치", message)

        self._ollama_install_thread = None

    def _install_cosyvoice(self):
        target_dir = self.cosyvoice_dir_input.text().strip()
        if not target_dir:
            target_dir = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "CosyVoice")
            self.cosyvoice_dir_input.setText(target_dir)

        confirm = QMessageBox.question(
            self,
            "CosyVoice 설치",
            f"아래 경로에 CosyVoice3를 설치할까요?\n\n{target_dir}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if confirm != QMessageBox.Yes:
            return

        self._cosyvoice_install_thread = CosyVoiceInstallerThread(target_dir)
        self._cosyvoice_install_thread.done.connect(self._on_cosyvoice_install_done)
        self._cosyvoice_progress_dialog = QProgressDialog(
            "CosyVoice3 설치를 진행 중입니다.\n의존성 및 모델 다운로드로 시간이 조금 걸릴 수 있습니다.",
            None, 0, 0, self,
        )
        self._cosyvoice_progress_dialog.setWindowTitle("CosyVoice3 설치")
        self._cosyvoice_progress_dialog.setWindowModality(Qt.ApplicationModal)
        self._cosyvoice_progress_dialog.setCancelButton(None)
        self._cosyvoice_progress_dialog.setMinimumDuration(0)
        self._cosyvoice_progress_dialog.show()
        self._cosyvoice_install_thread.start()

    def _on_cosyvoice_install_done(self, success: bool, message: str, installed_path: str):
        if self._cosyvoice_progress_dialog is not None:
            self._cosyvoice_progress_dialog.close()
            self._cosyvoice_progress_dialog = None

        if success:
            self.cosyvoice_dir_input.setText(installed_path)
            self._check_cosyvoice_dir(installed_path)
            if self.tts_mode_combo.currentData() != "local":
                self._set_combo(self.tts_mode_combo, "local")
                self._on_tts_changed()
            QMessageBox.information(self, "CosyVoice3 설치", message)
        else:
            self.cosyvoice_dir_status.setText(message)
            self.cosyvoice_dir_status.setStyleSheet("color: #e74c3c;")
            QMessageBox.warning(self, "CosyVoice3 설치", message)

        self._cosyvoice_install_thread = None

    def _browse_cosyvoice_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "CosyVoice 설치 폴더 선택",
            self.cosyvoice_dir_input.text() or "C:/",
        )
        if path:
            self.cosyvoice_dir_input.setText(path)
            self._check_cosyvoice_dir(path)

    def _detect_cosyvoice_dir(self):
        try:
            from tts.cosyvoice_tts import _get_cosyvoice_dir
            path = _get_cosyvoice_dir()
        except Exception:
            path = ""
        if path:
            self.cosyvoice_dir_input.setText(path)
            self.cosyvoice_dir_status.setText(f"✓ 감지됨: {path}")
            self.cosyvoice_dir_status.setStyleSheet("color: #27ae60;")
        else:
            self.cosyvoice_dir_status.setText("✗ 자동 감지 실패 — 경로를 직접 입력하세요.")
            self.cosyvoice_dir_status.setStyleSheet("color: #e74c3c;")

    def _check_cosyvoice_dir(self, path: str):
        marker = os.path.join(path, "pretrained_models")
        if os.path.isdir(marker):
            self.cosyvoice_dir_status.setText("✓ 유효한 CosyVoice 경로")
            self.cosyvoice_dir_status.setStyleSheet("color: #27ae60;")
        else:
            self.cosyvoice_dir_status.setText("⚠ pretrained_models 폴더가 없습니다. 경로를 확인하세요.")
            self.cosyvoice_dir_status.setStyleSheet("color: #e67e22;")

    # ── 유틸리티 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _set_combo(combo: QComboBox, value: str):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    @staticmethod
    def _float(text: str, default: float) -> float:
        try:
            return float(text)
        except (ValueError, TypeError):
            return default

    # ── 공개 인터페이스 ────────────────────────────────────────────────────────

    def get_values(self) -> dict:
        """현재 TTS 설정 값을 dict로 반환."""
        return {
            "tts_mode": self.tts_mode_combo.currentData(),
            "fish_api_key": self.fish_key_input.text().strip(),
            "fish_reference_id": self.fish_ref_input.text().strip(),
            "cosyvoice_dir": self.cosyvoice_dir_input.text().strip(),
            "cosyvoice_reference_text": self.cosyvoice_ref_text.toPlainText().strip(),
            "cosyvoice_speed": self._float(self.cosyvoice_speed_input.text(), 0.9),
            "openai_tts_api_key": self.openai_tts_key_input.text().strip(),
            "openai_tts_voice": self.openai_tts_voice_combo.currentData(),
            "openai_tts_model": self.openai_tts_model_combo.currentData(),
            "elevenlabs_api_key": self.elevenlabs_key_input.text().strip(),
            "elevenlabs_voice_id": self.elevenlabs_voice_id_input.text().strip(),
            "edge_tts_voice": self.edge_voice_combo.currentData(),
            "edge_tts_rate": self.edge_rate_input.text().strip() or "+0%",
        }

    def cleanup_threads(self):
        """다이얼로그 닫힐 때 실행 중인 스레드 정리."""
        for thread in (self._ollama_install_thread, self._cosyvoice_install_thread):
            if thread and thread.isRunning():
                thread.quit()
                thread.wait(2000)

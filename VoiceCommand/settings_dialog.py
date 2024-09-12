"""
설정 창 GUI
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel,
                                QLineEdit, QTextEdit, QPushButton,
                                QComboBox, QGroupBox, QStackedWidget,
                                QWidget)
from PySide6.QtCore import Qt
from config_manager import ConfigManager
import os


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("아리 설정")
        self.setMinimumWidth(520)
        self.load_settings()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # ── Groq API ───────────────────────────────────────────────────────────
        layout.addWidget(QLabel("Groq API Key (AI 대화):"))
        self.groq_api_key_input = QLineEdit(self.settings.get("groq_api_key", ""))
        self.groq_api_key_input.setPlaceholderText("https://console.groq.com에서 무료 발급")
        layout.addWidget(self.groq_api_key_input)

        # ── TTS 모드 선택 ──────────────────────────────────────────────────────
        layout.addWidget(QLabel("TTS 모드:"))
        self.tts_mode_combo = QComboBox()
        self.tts_mode_combo.addItem("Fish Audio (API)", "fish")
        self.tts_mode_combo.addItem("로컬 (CosyVoice3)", "local")
        current_mode = self.settings.get("tts_mode", "fish")
        self.tts_mode_combo.setCurrentIndex(0 if current_mode == "fish" else 1)
        self.tts_mode_combo.currentIndexChanged.connect(self._on_tts_mode_changed)
        layout.addWidget(self.tts_mode_combo)

        # ── Fish Audio 설정 패널 ───────────────────────────────────────────────
        self.fish_group = QGroupBox("Fish Audio 설정")
        fish_layout = QVBoxLayout()
        fish_layout.addWidget(QLabel("Fish Audio API Key:"))
        self.api_key_input = QLineEdit(self.settings.get("fish_api_key", ""))
        fish_layout.addWidget(self.api_key_input)
        fish_layout.addWidget(QLabel("Reference ID:"))
        self.ref_id_input = QLineEdit(self.settings.get("fish_reference_id", ""))
        fish_layout.addWidget(self.ref_id_input)
        self.fish_group.setLayout(fish_layout)
        layout.addWidget(self.fish_group)

        # ── CosyVoice3 설정 패널 ──────────────────────────────────────────────
        self.cosyvoice_group = QGroupBox("CosyVoice3 설정 (로컬)")
        cv_layout = QVBoxLayout()
        cv_layout.addWidget(QLabel("Reference WAV 텍스트 (reference.wav에서 말한 내용):"))
        self.cosyvoice_ref_text_input = QTextEdit()
        self.cosyvoice_ref_text_input.setPlainText(
            self.settings.get("cosyvoice_reference_text", "")
        )
        self.cosyvoice_ref_text_input.setMaximumHeight(80)
        self.cosyvoice_ref_text_input.setPlaceholderText(
            "reference.wav에서 말한 내용을 입력하세요.\n비워두면 cross_lingual 모드로 대체됩니다."
        )
        cv_layout.addWidget(self.cosyvoice_ref_text_input)

        cv_layout.addWidget(QLabel("말하기 속도 (0.7=느림/차분 ~ 1.2=빠름, 기본 0.9):"))
        self.cosyvoice_speed_input = QLineEdit(
            str(self.settings.get("cosyvoice_speed", 1.0))
        )
        cv_layout.addWidget(self.cosyvoice_speed_input)
        self.cosyvoice_group.setLayout(cv_layout)
        layout.addWidget(self.cosyvoice_group)

        # 초기 패널 표시 상태 설정
        self._on_tts_mode_changed()

        # ── RP 설정 ────────────────────────────────────────────────────────────
        layout.addWidget(QLabel("성격:"))
        self.personality_input = QTextEdit()
        self.personality_input.setPlainText(self.settings.get("personality", ""))
        self.personality_input.setMaximumHeight(60)
        layout.addWidget(self.personality_input)

        layout.addWidget(QLabel("시나리오:"))
        self.scenario_input = QTextEdit()
        self.scenario_input.setPlainText(self.settings.get("scenario", ""))
        self.scenario_input.setMaximumHeight(60)
        layout.addWidget(self.scenario_input)

        layout.addWidget(QLabel("시스템 프롬프트:"))
        self.system_input = QTextEdit()
        self.system_input.setPlainText(self.settings.get("system_prompt", ""))
        self.system_input.setMaximumHeight(60)
        layout.addWidget(self.system_input)

        layout.addWidget(QLabel("이전 기록 지침:"))
        self.history_input = QTextEdit()
        self.history_input.setPlainText(self.settings.get("history_instruction", ""))
        self.history_input.setMaximumHeight(60)
        layout.addWidget(self.history_input)

        # ── 저장 버튼 ──────────────────────────────────────────────────────────
        save_btn = QPushButton("저장")
        save_btn.clicked.connect(self.save_settings)
        layout.addWidget(save_btn)

        self.setLayout(layout)

    def _on_tts_mode_changed(self):
        """TTS 모드 콤보박스 변경 시 해당 패널만 표시"""
        is_fish = self.tts_mode_combo.currentData() == "fish"
        self.fish_group.setVisible(is_fish)
        self.cosyvoice_group.setVisible(not is_fish)

    def load_settings(self):
        self.settings = ConfigManager.load_settings()

    def save_settings(self):
        self.settings = {
            "groq_api_key": self.groq_api_key_input.text(),
            "tts_mode": self.tts_mode_combo.currentData(),
            "fish_api_key": self.api_key_input.text(),
            "fish_reference_id": self.ref_id_input.text(),
            "cosyvoice_reference_text": self.cosyvoice_ref_text_input.toPlainText(),
            "cosyvoice_speed": float(self.cosyvoice_speed_input.text() or "0.9"),
            "personality": self.personality_input.toPlainText(),
            "scenario": self.scenario_input.toPlainText(),
            "system_prompt": self.system_input.toPlainText(),
            "history_instruction": self.history_input.toPlainText(),
        }

        ConfigManager.save_settings(self.settings)
        self.accept()

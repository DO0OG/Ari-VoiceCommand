"""
설정 창 GUI — 탭 기반 구성 (RP, LLM, TTS, 장치, 확장)
각 탭의 세부 구현은 settings_llm_page / settings_tts_page / settings_plugin_page 에 위임한다.
"""
import logging

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QTextEdit, QPushButton,
    QComboBox, QGroupBox, QWidget,
    QTabWidget, QMessageBox, QFrame, QSlider,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from core.config_manager import ConfigManager
from i18n.translator import _, set_language, get_language
from ui.theme import (
    FONT_KO, FONT_SIZE_NORMAL, COLOR_SUCCESS,
    TAB_STYLE, INPUT_STYLE,
    available_theme_presets, secondary_btn_style, theme_dir, load_theme_palette,
)
from ui.theme_editor import ThemeEditorDialog
from ui.common import create_muted_label
from ui.settings_llm_page import _LLMSettingsPage
from ui.settings_tts_page import _TTSSettingsPage
from ui.settings_plugin_page import _PluginSettingsPage
from ui.settings_agent_page import _AgentSettingsPage


class SettingsDialog(QDialog):
    TTS_KEYS = {
        "tts_mode", "fish_api_key", "fish_reference_id", "fish_model", "tts_volume",
        "cosyvoice_reference_text",
        "cosyvoice_speed", "cosyvoice_dir", "openai_tts_api_key", "openai_tts_voice", "openai_tts_model",
        "elevenlabs_api_key", "elevenlabs_voice_id", "edge_tts_voice", "edge_tts_rate",
    }
    LLM_KEYS = {
        "llm_provider", "llm_model",
        "llm_planner_provider", "llm_planner_model",
        "llm_execution_provider", "llm_execution_model",
        "ollama_base_url",
        "groq_api_key", "openai_api_key", "anthropic_api_key", "mistral_api_key",
        "gemini_api_key", "openrouter_api_key", "nvidia_nim_api_key", "system_prompt", "personality",
        "scenario", "history_instruction", "response_verbosity",
    }
    THEME_KEYS = {"ui_theme_preset", "ui_theme_scale", "ui_font_family"}
    CHARACTER_KEYS = {"character_scale", "character_ground_offset"}
    STT_KEYS = {
        "stt_provider", "whisper_model", "whisper_device", "whisper_compute_type",
        "wake_words", "stt_energy_threshold", "stt_dynamic_energy",
    }
    AGENT_KEYS = {"agent_timeout_seconds", "agent_dashboard_enabled", "audit_log_enabled", "mcp_server_enabled"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("아리 설정"))
        self.setMinimumWidth(600)
        self.setMinimumHeight(550)
        self.settings = ConfigManager.load_settings()
        self.original_settings = dict(self.settings)
        self.changed_keys: set = set()
        self._editor_dialog: ThemeEditorDialog | None = None
        self._init_ui()

    # ── UI 구성 ────────────────────────────────────────────────────────────────

    def _init_ui(self):
        self.setFont(QFont(FONT_KO, FONT_SIZE_NORMAL))
        self.setStyleSheet(INPUT_STYLE)
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(TAB_STYLE)
        layout.addWidget(self.tabs)

        # 1. RP 설정 탭
        self.tabs.addTab(self._create_rp_tab(), _("RP 설정"))

        # 2. LLM 설정 탭
        self._llm_page = _LLMSettingsPage(self.settings, self)
        self.tabs.addTab(self._llm_page, _("AI 설정"))

        # 3. TTS 설정 탭
        self._tts_page = _TTSSettingsPage(self.settings, self)
        self.tabs.addTab(self._tts_page, _("TTS 설정"))

        # 4. 장치 설정 탭
        self.tabs.addTab(self._create_device_tab(), _("장치 설정"))

        # 5. 확장 탭
        self._agent_page = _AgentSettingsPage(self.settings, self)
        self.tabs.addTab(self._agent_page, _("에이전트"))

        # 6. 확장 탭
        self._plugin_page = _PluginSettingsPage(self)
        self.tabs.addTab(self._plugin_page, _("확장"))

        # 하단 버튼
        btn_layout = QHBoxLayout()
        save_btn = QPushButton(_("저장"))
        save_btn.setMinimumHeight(45)
        save_btn.setMinimumWidth(120)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_SUCCESS};
                color: white;
                font-weight: bold;
                font-size: {FONT_SIZE_NORMAL + 1}px;
                border-radius: 10px;
                padding: 0 20px;
            }}
            QPushButton:hover {{
                background-color: #219150;
            }}
            QPushButton:pressed {{
                background-color: #1a7a43;
            }}
        """)
        save_btn.clicked.connect(self._save)

        cancel_btn = QPushButton(_("취소"))
        cancel_btn.setMinimumHeight(45)
        cancel_btn.setMinimumWidth(100)
        cancel_btn.setStyleSheet("""
            QPushButton {{
                background-color: #f1f3f5;
                color: #333;
                font-weight: normal;
                border-radius: 10px;
                padding: 0 15px;
            }}
            QPushButton:hover {{
                background-color: #e9ecef;
            }}
        """)
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    # ── 탭 생성 ───────────────────────────────────────────────────────────────

    def _create_rp_tab(self):
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(10)

        group = QGroupBox(_("캐릭터 페르소나 설정"))
        gvbox = QVBoxLayout(group)
        gvbox.setSpacing(8)

        rp_fields = [
            ("personality_input",  _("성격:"),           "personality",         _("예) 상냥하고 귀여운 AI 비서")),
            ("scenario_input",     _("시나리오:"),        "scenario",            _("예) 주인님을 보좌하는 역할극")),
            ("system_input",       _("시스템 프롬프트:"), "system_prompt",       _("AI에게 직접 전달할 시스템 지시문")),
            ("history_input",      _("대화 지침:"),       "history_instruction", _("이전 대화를 참고할 때의 태도")),
        ]

        for attr, label, key, ph in rp_fields:
            label_widget = QLabel(label)
            gvbox.addWidget(label_widget)
            edit = QTextEdit()
            edit.setPlainText(self.settings.get(key, ""))
            edit.setPlaceholderText(ph)
            edit.setMinimumHeight(90)
            setattr(self, attr, edit)
            gvbox.addWidget(edit, 1)

        gvbox.addWidget(QLabel(_("응답 말수:")))
        self.verbosity_combo = QComboBox()
        self.verbosity_combo.addItem(_("간결하게 (한두 문장)"), "concise")
        self.verbosity_combo.addItem(_("보통"), "normal")
        self.verbosity_combo.addItem(_("수다스럽게"), "chatty")
        self._set_combo(self.verbosity_combo, self.settings.get("response_verbosity", "concise"))
        gvbox.addWidget(self.verbosity_combo)

        vbox.addWidget(group, 1)
        return widget

    def _create_device_tab(self):
        widget = QWidget()
        vbox = QVBoxLayout(widget)

        group = QGroupBox(_("오디오 장치 설정"))
        gvbox = QVBoxLayout(group)

        gvbox.addWidget(QLabel(_("마이크 입력 장치 선택:")))
        self.mic_combo = QComboBox()
        self.mic_combo.addItem(_("시스템 기본 마이크"), "")
        try:
            import speech_recognition as sr
            mics = sr.Microphone.list_microphone_names()
            for mic in mics:
                self.mic_combo.addItem(mic, mic)
        except Exception as e:
            logging.error(f"마이크 목록 로드 오류: {e}")
        self._set_combo(self.mic_combo, self.settings.get("microphone", ""))
        gvbox.addWidget(self.mic_combo)

        gvbox.addSpacing(15)
        gvbox.addWidget(QLabel(_("스피커 출력 장치 선택:")))
        self.speaker_combo = QComboBox()
        self.speaker_combo.addItem(_("시스템 기본 스피커"), "")
        try:
            from audio.audio_manager import list_output_devices
            out_devices = list_output_devices()
            seen_names = set()
            for dev in out_devices:
                name = dev["name"]
                if name not in seen_names:
                    self.speaker_combo.addItem(name, name)
                    seen_names.add(name)
        except Exception as e:
            logging.error(f"출력 장치 목록 로드 오류: {e}")
        self._set_combo(self.speaker_combo, self.settings.get("audio_output_device", ""))
        gvbox.addWidget(self.speaker_combo)

        stt_group = QGroupBox(_("음성 인식"))
        stt_vbox = QVBoxLayout(stt_group)
        stt_vbox.addWidget(create_muted_label(_("STT 엔진, Whisper 설정, 마이크 감도, 웨이크워드를 설정합니다.")))
        stt_btn = QPushButton(_("음성 인식 설정..."))
        stt_btn.clicked.connect(self._open_stt_settings)
        stt_vbox.addWidget(stt_btn)

        vbox.addWidget(stt_group)
        vbox.addWidget(group)

        vbox.addWidget(self._create_character_group())

        theme_group = QGroupBox(_("UI 테마 설정"))
        tvbox = QVBoxLayout(theme_group)

        tvbox.addWidget(QLabel(_("테마 프리셋:")))
        self.theme_preset_combo = QComboBox()
        for preset_key, preset_name in available_theme_presets():
            self.theme_preset_combo.addItem(preset_name, preset_key)
        self._set_combo(self.theme_preset_combo, self.settings.get("ui_theme_preset", "default"))
        tvbox.addWidget(self.theme_preset_combo)

        tvbox.addWidget(QLabel(_("글꼴 배율 (0.9 ~ 1.35):")))
        self.theme_scale_input = QLineEdit(str(self.settings.get("ui_theme_scale", 1.0)))
        self.theme_scale_input.setPlaceholderText(_("예: 1.0"))
        tvbox.addWidget(self.theme_scale_input)

        tvbox.addWidget(QLabel(_("글꼴 패밀리 재정의 (선택):")))
        self.theme_font_input = QLineEdit(self.settings.get("ui_font_family", ""))
        self.theme_font_input.setPlaceholderText(_("비워두면 테마 기본 글꼴 사용"))
        tvbox.addWidget(self.theme_font_input)

        self.theme_preview_frame = QFrame()
        self.theme_preview_frame.setFrameShape(QFrame.Shape.StyledPanel)
        preview_layout = QVBoxLayout(self.theme_preview_frame)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        self.theme_preview_title = QLabel(_("테마 미리보기"))
        self.theme_preview_colors = QLabel("")
        self.theme_preview_colors.setWordWrap(True)
        preview_layout.addWidget(self.theme_preview_title)
        preview_layout.addWidget(self.theme_preview_colors)
        tvbox.addWidget(self.theme_preview_frame)

        preview_btn = QPushButton(_("테마 폴더 안내"))
        preview_btn.setStyleSheet(secondary_btn_style())
        preview_btn.clicked.connect(self._show_theme_hint)
        tvbox.addWidget(preview_btn)

        self.editor_toggle_btn = QPushButton(_("🎨 팔레트 직접 편집"))
        self.editor_toggle_btn.clicked.connect(self._toggle_theme_editor)
        tvbox.addWidget(self.editor_toggle_btn)

        self.theme_preset_combo.currentIndexChanged.connect(self._on_theme_preset_changed)
        self._refresh_theme_preview()

        vbox.addWidget(theme_group)

        lang_group = QGroupBox(_("언어 설정"))
        lvbox = QVBoxLayout(lang_group)
        lvbox.addWidget(QLabel(_("인터페이스 언어:")))
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("한국어", "ko")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.addItem("日本語", "ja")
        self._set_combo(self.lang_combo, get_language())
        lvbox.addWidget(self.lang_combo)
        vbox.addWidget(lang_group)

        log_btn = QPushButton(_("로그 파일 폴더 열기"))
        log_btn.setStyleSheet(secondary_btn_style())
        log_btn.clicked.connect(self._open_log_folder)
        vbox.addWidget(log_btn)

        vbox.addStretch()
        return widget

    # ── 캐릭터 표시 설정 ──────────────────────────────────────────────────────

    def _create_character_group(self) -> QGroupBox:
        """캐릭터 크기와 바닥 위치를 슬라이더로 조절한다. 움직이는 즉시 미리보기가 반영된다."""
        group = QGroupBox(_("캐릭터 표시 설정"))
        layout = QVBoxLayout(group)
        layout.addWidget(create_muted_label(
            _("슬라이더를 움직이면 화면의 아리에게 바로 반영됩니다. 취소하면 원래대로 돌아갑니다.")
        ))

        self._original_char_scale = float(self.settings.get("character_scale", 1.0))
        self._original_char_offset = int(self.settings.get("character_ground_offset", 4))

        # 크기 — 퍼센트로 보여주는 편이 배율 숫자보다 읽기 쉽다.
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel(_("크기")))
        self.char_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.char_scale_slider.setRange(30, 300)
        self.char_scale_slider.setSingleStep(5)
        self.char_scale_slider.setPageStep(10)
        self.char_scale_slider.setValue(int(round(self._original_char_scale * 100)))
        size_row.addWidget(self.char_scale_slider, 1)
        self.char_scale_value = QLabel()
        self.char_scale_value.setMinimumWidth(56)
        size_row.addWidget(self.char_scale_value)
        layout.addLayout(size_row)
        layout.addWidget(create_muted_label(_("작게 30% ↔ 크게 300% (기본 100%)")))

        # 바닥 위치 — 부호의 의미를 라벨로 드러낸다.
        offset_row = QHBoxLayout()
        offset_row.addWidget(QLabel(_("바닥 위치")))
        self.char_offset_slider = QSlider(Qt.Orientation.Horizontal)
        self.char_offset_slider.setRange(-200, 200)
        self.char_offset_slider.setSingleStep(1)
        self.char_offset_slider.setPageStep(5)
        self.char_offset_slider.setValue(self._original_char_offset)
        offset_row.addWidget(self.char_offset_slider, 1)
        self.char_offset_value = QLabel()
        self.char_offset_value.setMinimumWidth(56)
        offset_row.addWidget(self.char_offset_value)
        layout.addLayout(offset_row)
        layout.addWidget(create_muted_label(
            _("왼쪽으로 옮기면 위로, 오른쪽으로 옮기면 아래로 내려갑니다. "
              "직접 만든 이미지의 발이 바닥에서 뜨거나 파묻힐 때 맞추세요.")
        ))

        reset_btn = QPushButton(_("기본값으로 되돌리기"))
        reset_btn.setStyleSheet(secondary_btn_style())
        reset_btn.clicked.connect(self._reset_character_display)
        layout.addWidget(reset_btn)

        self.char_scale_slider.valueChanged.connect(self._on_character_display_changed)
        self.char_offset_slider.valueChanged.connect(self._on_character_display_changed)
        self._refresh_character_labels()
        return group

    def _refresh_character_labels(self):
        self.char_scale_value.setText(f"{self.char_scale_slider.value()}%")
        offset = self.char_offset_slider.value()
        self.char_offset_value.setText(f"{offset:+d}px")

    def _on_character_display_changed(self, _value=None):
        self._refresh_character_labels()
        self._apply_character_display(
            self.char_scale_slider.value() / 100.0,
            self.char_offset_slider.value(),
        )

    def _reset_character_display(self):
        defaults = ConfigManager.DEFAULT_SETTINGS
        self.char_scale_slider.setValue(int(round(float(defaults.get("character_scale", 1.0)) * 100)))
        self.char_offset_slider.setValue(int(defaults.get("character_ground_offset", 4)))

    @staticmethod
    def _apply_character_display(scale: float, ground_offset: int):
        """실행 중인 캐릭터 위젯에 표시 설정을 반영한다. 위젯이 없으면 조용히 넘어간다."""
        try:
            from core.VoiceCommand import _state
            widget = getattr(_state, "character_widget", None)
            if widget is not None and hasattr(widget, "apply_display_settings"):
                widget.apply_display_settings(scale=scale, ground_offset=ground_offset)
        except Exception as exc:
            logging.debug(f"캐릭터 표시 설정 반영 생략: {exc}")

    def _restore_character_display(self):
        """저장하지 않고 창을 닫으면 미리보기를 되돌린다."""
        if hasattr(self, "_original_char_scale"):
            self._apply_character_display(self._original_char_scale, self._original_char_offset)

    def reject(self):
        self._restore_character_display()
        super().reject()

    # ── 유틸리티 ─────────────────────────────────────────────────────────────

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

    def _open_log_folder(self):
        import os
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        from core.resource_manager import ResourceManager
        log_dir = ResourceManager.get_writable_path("logs")
        os.makedirs(log_dir, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(log_dir))

    def _open_stt_settings(self):
        from ui.stt_settings_dialog import STTSettingsDialog
        dlg = STTSettingsDialog(self)
        dlg.exec()

    def _show_theme_hint(self):
        QMessageBox.information(
            self,
            _("테마 폴더"),
            _("테마 JSON 파일은 아래 폴더에서 직접 수정할 수 있습니다.\n\n{path}\n\n저장 후 설정창에서 다시 적용하면 열린 UI에 즉시 반영됩니다.").format(path=theme_dir()),
        )

    def _refresh_theme_preview(self):
        theme_key = self.theme_preset_combo.currentData() or "default"
        palette = load_theme_palette(theme_key)
        primary = palette.colors.get("primary", "#4a90e2")
        accent = palette.colors.get("accent", "#ff7b54")
        panel = palette.colors.get("bg_panel", "#f5f7fa")
        text = palette.colors.get("text_primary", "#333333")
        self.theme_preview_frame.setStyleSheet(
            f"QFrame {{ background: {panel}; border: 1px solid {primary}; border-radius: 10px; }}"
            f"QLabel {{ color: {text}; }}"
        )
        self.theme_preview_title.setText(_("{name} 미리보기").format(name=palette.name))
        self.theme_preview_colors.setText(
            f"Primary {primary} | Accent {accent} | Font {palette.font_family}"
        )

    def _toggle_theme_editor(self):
        if self._editor_dialog is None:
            initial_palette = load_theme_palette(self.settings.get("ui_theme_preset", ""))
            self._editor_dialog = ThemeEditorDialog(initial_palette.colors, self)
            self._editor_dialog.palette_changed.connect(self._on_palette_changed)
            self._editor_dialog.theme_saved.connect(self._on_theme_saved)
        self._editor_dialog.show()
        self._editor_dialog.raise_()
        self._editor_dialog.activateWindow()

    def _on_palette_changed(self):
        if self._editor_dialog is None:
            return
        colors = self._editor_dialog.get_current_colors()
        primary = colors.get("primary", "#4a90e2")
        accent = colors.get("accent", "#ff7b54")
        self.theme_preview_colors.setText(f"Primary {primary} | Accent {accent} | Custom editing")

    def _on_theme_saved(self, theme_key: str):
        from ui.theme_runtime import apply_live_theme
        self.theme_preset_combo.blockSignals(True)
        self.theme_preset_combo.clear()
        for key, name in available_theme_presets():
            self.theme_preset_combo.addItem(name, key)
        idx = self.theme_preset_combo.findData(theme_key)
        if idx >= 0:
            self.theme_preset_combo.setCurrentIndex(idx)
        self.theme_preset_combo.blockSignals(False)
        try:
            apply_live_theme(character_widget=self.parent())
        except Exception as exc:
            logging.debug(f"실시간 테마 적용 실패: {exc}")
        self._refresh_theme_preview()

    def _on_theme_preset_changed(self, index: int):
        key = self.theme_preset_combo.currentData()
        palette = load_theme_palette(key)
        self._refresh_theme_preview()
        if self._editor_dialog is not None:
            self._editor_dialog.load_preset(palette.colors)

    # ── 저장 로직 ─────────────────────────────────────────────────────────────

    def _save(self):
        new_settings = {
            # RP
            "personality": self.personality_input.toPlainText().strip(),
            "scenario": self.scenario_input.toPlainText().strip(),
            "system_prompt": self.system_input.toPlainText().strip(),
            "history_instruction": self.history_input.toPlainText().strip(),
            "response_verbosity": self.verbosity_combo.currentData(),

            # Device / Theme / Language
            "microphone": self.mic_combo.currentData(),
            "audio_output_device": self.speaker_combo.currentData(),
            "character_scale": round(self.char_scale_slider.value() / 100.0, 2),
            "character_ground_offset": self.char_offset_slider.value(),
            "ui_theme_preset": self.theme_preset_combo.currentData(),
            "ui_theme_scale": max(0.9, min(1.35, self._float(self.theme_scale_input.text(), 1.0))),
            "ui_font_family": self.theme_font_input.text().strip(),
            "language": self.lang_combo.currentData(),
        }

        # LLM / TTS 값을 각 페이지에서 수집
        new_settings.update(self._llm_page.get_values())
        new_settings.update(self._tts_page.get_values())
        new_settings.update(self._agent_page.get_values())

        merged_settings = {**self.original_settings, **new_settings}
        self.changed_keys = {
            key for key, value in merged_settings.items()
            if self.original_settings.get(key) != value
        }
        ConfigManager.save_settings(merged_settings)

        if self.character_settings_changed():
            self._apply_character_display(
                merged_settings["character_scale"],
                merged_settings["character_ground_offset"],
            )

        if self.llm_settings_changed():
            try:
                from agent.llm_provider import reset_llm_provider
                reset_llm_provider()
            except Exception as exc:
                logging.debug(f"LLM provider reset 생략: {exc}")

        if self.theme_settings_changed():
            QMessageBox.information(
                self,
                _("테마 저장"),
                _("테마 설정이 저장되었습니다.\n열려 있는 UI에는 즉시 반영되며, TTS나 워커는 다시 시작하지 않습니다."),
            )

        selected_lang = self.lang_combo.currentData()
        if selected_lang != get_language():
            set_language(selected_lang)

        self.accept()

    def tts_settings_changed(self) -> bool:
        return any(key in self.changed_keys for key in self.TTS_KEYS)

    def llm_settings_changed(self) -> bool:
        return any(key in self.changed_keys for key in self.LLM_KEYS)

    def character_settings_changed(self) -> bool:
        return any(key in self.changed_keys for key in self.CHARACTER_KEYS)

    def theme_settings_changed(self) -> bool:
        return any(key in self.changed_keys for key in self.THEME_KEYS)

    def language_settings_changed(self) -> bool:
        return "language" in self.changed_keys

    # ── 생명주기 ──────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._llm_page.cleanup_threads()
        self._tts_page.cleanup_threads()
        self._plugin_page.cleanup_threads()
        super().closeEvent(event)

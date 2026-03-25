"""
설정 창 GUI — 탭 기반 구성 (RP, AI & TTS, 장치)
"""
import logging
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QTextEdit, QPushButton,
    QComboBox, QGroupBox, QScrollArea, QWidget,
    QTabWidget, QMessageBox, QListWidget, QListWidgetItem, QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QDesktopServices
from PySide6.QtCore import QUrl
from core.config_manager import ConfigManager
from ui.theme import (
    FONT_KO, FONT_SIZE_NORMAL, COLOR_PRIMARY, COLOR_SUCCESS,
    TAB_STYLE, SCROLLBAR_STYLE, INPUT_STYLE, primary_btn_style,
    available_theme_presets, secondary_btn_style, theme_dir, load_theme_palette,
)
from ui.common import create_muted_label

# ── 제공자 정의 ────────────────────────────────────────────────────────────────

_LLM_PROVIDERS = [
    # (표시 이름,          data 키,       settings 키,          placeholder)
    ("Groq (Llama 3.3, 무료)", "groq",       "groq_api_key",       "https://console.groq.com 에서 무료 발급"),
    ("OpenAI (GPT-4o)",        "openai",     "openai_api_key",     "https://platform.openai.com/api-keys"),
    ("Anthropic (Claude)",     "anthropic",  "anthropic_api_key",  "https://console.anthropic.com"),
    ("Mistral AI",             "mistral",    "mistral_api_key",    "https://console.mistral.ai"),
    ("Google Gemini",          "gemini",     "gemini_api_key",     "https://aistudio.google.com/app/apikey"),
    ("OpenRouter (멀티모델)",   "openrouter", "openrouter_api_key", "https://openrouter.ai/keys"),
]

_TTS_MODES = [
    ("Fish Audio (API)",    "fish"),
    ("로컬 (CosyVoice3)",   "local"),
    ("OpenAI TTS",          "openai_tts"),
    ("ElevenLabs",          "elevenlabs"),
    ("Edge TTS (무료)",     "edge"),
]


class SettingsDialog(QDialog):
    TTS_KEYS = {
        "tts_mode", "fish_api_key", "fish_reference_id", "cosyvoice_reference_text",
        "cosyvoice_speed", "openai_tts_api_key", "openai_tts_voice", "openai_tts_model",
        "elevenlabs_api_key", "elevenlabs_voice_id", "edge_tts_voice", "edge_tts_rate",
    }
    LLM_KEYS = {
        "llm_provider", "llm_model", "llm_planner_model", "llm_execution_model",
        "groq_api_key", "openai_api_key", "anthropic_api_key", "mistral_api_key",
        "gemini_api_key", "openrouter_api_key", "system_prompt", "personality",
        "scenario", "history_instruction",
    }
    THEME_KEYS = {"ui_theme_preset", "ui_theme_scale", "ui_font_family"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("아리 설정")
        self.setMinimumWidth(600)
        self.setMinimumHeight(550)
        self.settings = ConfigManager.load_settings()
        self.original_settings = dict(self.settings)
        self.changed_keys = set()
        self._llm_key_inputs = {}   # data 키 → QLineEdit
        self._tts_groups = {}       # data 키 → QGroupBox
        self._init_ui()

    # ── UI 구성 ────────────────────────────────────────────────────────────────

    def _init_ui(self):
        self.setFont(QFont(FONT_KO, FONT_SIZE_NORMAL))
        self.setStyleSheet(INPUT_STYLE)
        layout = QVBoxLayout(self)

        # 탭 위젯 생성
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(TAB_STYLE)
        layout.addWidget(self.tabs)

        # 1. RP 설정 탭
        self.tabs.addTab(self._create_rp_tab(), "RP 설정")

        # 2. AI & TTS 설정 탭
        self.tabs.addTab(self._create_ai_tts_tab(), "AI & TTS 설정")

        # 3. 장치 설정 탭
        self.tabs.addTab(self._create_device_tab(), "장치 설정")

        # 4. 확장 설정 탭
        self.tabs.addTab(self._create_extensions_tab(), "확장")

        # 하단 버튼
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("저장")
        save_btn.setMinimumHeight(45)
        save_btn.setMinimumWidth(120)
        # COLOR_SUCCESS를 사용하여 성공(저장) 버튼 스타일 적용 (강조 버전)
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
        
        cancel_btn = QPushButton("취소")
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

        # 초기 패널 상태 업데이트
        self._on_llm_changed()
        self._on_tts_changed()

    # ── 탭 생성 ───────────────────────────────────────────────────────────────

    def _create_rp_tab(self):
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        
        group = QGroupBox("캐릭터 페르소나 설정")
        gvbox = QVBoxLayout(group)

        # 설정 항목들
        rp_fields = [
            ("personality_input",     "성격:",          "personality",          "예) 상냥하고 귀여운 AI 비서"),
            ("scenario_input",        "시나리오:",      "scenario",             "예) 주인님을 보좌하는 역할극"),
            ("system_input",          "시스템 프롬프트:", "system_prompt",        "AI에게 직접 전달할 시스템 지시문"),
            ("history_input",         "대화 지침:",      "history_instruction",  "이전 대화를 참고할 때의 태도"),
        ]

        for attr, label, key, ph in rp_fields:
            gvbox.addWidget(QLabel(label))
            edit = QTextEdit()
            edit.setPlainText(self.settings.get(key, ""))
            edit.setPlaceholderText(ph)
            edit.setMaximumHeight(80)
            setattr(self, attr, edit)
            gvbox.addWidget(edit)

        vbox.addWidget(group)
        vbox.addStretch()
        return widget

    def _create_ai_tts_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet(SCROLLBAR_STYLE)
        
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setSpacing(15)

        # 1. AI (LLM) 설정
        llm_group = QGroupBox("AI (LLM) 엔진 설정")
        llm_vbox = QVBoxLayout(llm_group)

        llm_vbox.addWidget(QLabel("제공자 선택:"))
        self.llm_provider_combo = QComboBox()
        for label, data, _key, _ph in _LLM_PROVIDERS:
            self.llm_provider_combo.addItem(label, data)
        self._set_combo(self.llm_provider_combo, self.settings.get("llm_provider", "groq"))
        self.llm_provider_combo.currentIndexChanged.connect(self._on_llm_changed)
        llm_vbox.addWidget(self.llm_provider_combo)

        llm_vbox.addWidget(QLabel("모델 이름 (비워두면 기본값):"))
        self.llm_model_input = QLineEdit(self.settings.get("llm_model", ""))
        self.llm_model_input.setPlaceholderText("예: gpt-4o, llama-3.3-70b-versatile...")
        llm_vbox.addWidget(self.llm_model_input)

        llm_vbox.addWidget(QLabel("플래너 모델 (선택):"))
        self.llm_planner_model_input = QLineEdit(self.settings.get("llm_planner_model", ""))
        self.llm_planner_model_input.setPlaceholderText("비워두면 기본 모델과 동일")
        llm_vbox.addWidget(self.llm_planner_model_input)

        llm_vbox.addWidget(QLabel("실행/수정 모델 (선택):"))
        self.llm_execution_model_input = QLineEdit(self.settings.get("llm_execution_model", ""))
        self.llm_execution_model_input.setPlaceholderText("비워두면 기본 모델과 동일")
        llm_vbox.addWidget(self.llm_execution_model_input)

        # API Key 입력 필드들 (동적 표시)
        for _label, data, key, placeholder in _LLM_PROVIDERS:
            sub = QGroupBox(f"{_label} API Key")
            sub_vbox = QVBoxLayout(sub)
            inp = QLineEdit(self.settings.get(key, ""))
            inp.setPlaceholderText(placeholder)
            inp.setEchoMode(QLineEdit.EchoMode.Password)
            sub_vbox.addWidget(inp)
            llm_vbox.addWidget(sub)
            self._llm_key_inputs[data] = inp
            self._tts_groups[f"_llm_{data}"] = sub

        vbox.addWidget(llm_group)

        # 2. TTS 설정
        tts_group = QGroupBox("음성 합성 (TTS) 설정")
        tts_vbox = QVBoxLayout(tts_group)

        tts_vbox.addWidget(QLabel("TTS 엔진 선택:"))
        self.tts_mode_combo = QComboBox()
        for label, data in _TTS_MODES:
            self.tts_mode_combo.addItem(label, data)
        self._set_combo(self.tts_mode_combo, self.settings.get("tts_mode", "fish"))
        self.tts_mode_combo.currentIndexChanged.connect(self._on_tts_changed)
        tts_vbox.addWidget(self.tts_mode_combo)

        # --- Fish Audio 설정 ---
        fish_grp = QGroupBox("Fish Audio 설정")
        fl = QVBoxLayout(fish_grp)
        fl.addWidget(QLabel("API Key:"))
        self.fish_key_input = QLineEdit(self.settings.get("fish_api_key", ""))
        self.fish_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        fl.addWidget(self.fish_key_input)
        fl.addWidget(QLabel("Reference ID:"))
        self.fish_ref_input = QLineEdit(self.settings.get("fish_reference_id", ""))
        fl.addWidget(self.fish_ref_input)
        tts_vbox.addWidget(fish_grp)
        self._tts_groups["fish"] = fish_grp

        # --- CosyVoice3 설정 ---
        cv_grp = QGroupBox("CosyVoice3 설정 (로컬 GPU)")
        cvl = QVBoxLayout(cv_grp)
        cvl.addWidget(QLabel("Reference WAV 텍스트 (Cross-lingual 시 비움):"))
        self.cosyvoice_ref_text = QTextEdit()
        self.cosyvoice_ref_text.setPlainText(self.settings.get("cosyvoice_reference_text", ""))
        self.cosyvoice_ref_text.setMaximumHeight(60)
        cvl.addWidget(self.cosyvoice_ref_text)
        cvl.addWidget(QLabel("말하기 속도 (0.7 ~ 1.2):"))
        self.cosyvoice_speed_input = QLineEdit(str(self.settings.get("cosyvoice_speed", 0.9)))
        cvl.addWidget(self.cosyvoice_speed_input)
        tts_vbox.addWidget(cv_grp)
        self._tts_groups["local"] = cv_grp

        # --- OpenAI TTS 설정 ---
        oai_grp = QGroupBox("OpenAI TTS 설정")
        oail = QVBoxLayout(oai_grp)
        oail.addWidget(QLabel("API Key (선택):"))
        self.openai_tts_key_input = QLineEdit(self.settings.get("openai_tts_api_key", ""))
        self.openai_tts_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_tts_key_input.setPlaceholderText("비워두면 AI 설정을 따릅니다.")
        oail.addWidget(self.openai_tts_key_input)
        
        row = QHBoxLayout()
        row.addWidget(QLabel("목소리:"))
        self.openai_tts_voice_combo = QComboBox()
        for v in ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]:
            self.openai_tts_voice_combo.addItem(v, v)
        self._set_combo(self.openai_tts_voice_combo, self.settings.get("openai_tts_voice", "nova"))
        row.addWidget(self.openai_tts_voice_combo)
        
        row.addWidget(QLabel("모델:"))
        self.openai_tts_model_combo = QComboBox()
        for m in ["tts-1", "tts-1-hd"]:
            self.openai_tts_model_combo.addItem(m, m)
        self._set_combo(self.openai_tts_model_combo, self.settings.get("openai_tts_model", "tts-1"))
        row.addWidget(self.openai_tts_model_combo)
        oail.addLayout(row)
        tts_vbox.addWidget(oai_grp)
        self._tts_groups["openai_tts"] = oai_grp

        # --- ElevenLabs 설정 ---
        el_grp = QGroupBox("ElevenLabs 설정")
        ell = QVBoxLayout(el_grp)
        ell.addWidget(QLabel("API Key:"))
        self.elevenlabs_key_input = QLineEdit(self.settings.get("elevenlabs_api_key", ""))
        self.elevenlabs_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        ell.addWidget(self.elevenlabs_key_input)
        ell.addWidget(QLabel("Voice ID:"))
        self.elevenlabs_voice_id_input = QLineEdit(self.settings.get("elevenlabs_voice_id", ""))
        ell.addWidget(self.elevenlabs_voice_id_input)
        tts_vbox.addWidget(el_grp)
        self._tts_groups["elevenlabs"] = el_grp

        # --- Edge TTS 설정 ---
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
        self._set_combo(self.edge_voice_combo, self.settings.get("edge_tts_voice", "ko-KR-SunHiNeural"))
        edgel.addWidget(self.edge_voice_combo)
        edgel.addWidget(QLabel("속도 (예: +0%, -10%):"))
        self.edge_rate_input = QLineEdit(self.settings.get("edge_tts_rate", "+0%"))
        edgel.addWidget(self.edge_rate_input)
        tts_vbox.addWidget(edge_grp)
        self._tts_groups["edge"] = edge_grp

        vbox.addWidget(tts_group)
        vbox.addStretch()
        
        scroll.setWidget(container)
        return scroll

    def _create_device_tab(self):
        widget = QWidget()
        vbox = QVBoxLayout(widget)

        group = QGroupBox("오디오 장치 설정")
        gvbox = QVBoxLayout(group)

        # 마이크 선택
        gvbox.addWidget(QLabel("마이크 입력 장치 선택:"))
        self.mic_combo = QComboBox()
        self.mic_combo.addItem("시스템 기본 마이크", "")
        
        try:
            import speech_recognition as sr
            mics = sr.Microphone.list_microphone_names()
            for mic in mics:
                self.mic_combo.addItem(mic, mic)
        except Exception as e:
            logging.error(f"마이크 목록 로드 오류: {e}")
            
        self._set_combo(self.mic_combo, self.settings.get("microphone", ""))
        gvbox.addWidget(self.mic_combo)

        # 스피커 안내
        gvbox.addSpacing(30)
        gvbox.addWidget(QLabel("스피커 출력 장치:"))
        info = create_muted_label("현재 시스템의 '기본 재생 장치'를 통해 소리가 출력됩니다.")
        gvbox.addWidget(info)

        vbox.addWidget(group)

        theme_group = QGroupBox("UI 테마 설정")
        tvbox = QVBoxLayout(theme_group)

        tvbox.addWidget(QLabel("테마 프리셋:"))
        self.theme_preset_combo = QComboBox()
        for preset_key, preset_name in available_theme_presets():
            self.theme_preset_combo.addItem(preset_name, preset_key)
        self._set_combo(self.theme_preset_combo, self.settings.get("ui_theme_preset", "default"))
        tvbox.addWidget(self.theme_preset_combo)

        tvbox.addWidget(QLabel("글꼴 배율 (0.9 ~ 1.35):"))
        self.theme_scale_input = QLineEdit(str(self.settings.get("ui_theme_scale", 1.0)))
        self.theme_scale_input.setPlaceholderText("예: 1.0")
        tvbox.addWidget(self.theme_scale_input)

        tvbox.addWidget(QLabel("글꼴 패밀리 재정의 (선택):"))
        self.theme_font_input = QLineEdit(self.settings.get("ui_font_family", ""))
        self.theme_font_input.setPlaceholderText("비워두면 테마 기본 글꼴 사용")
        tvbox.addWidget(self.theme_font_input)

        self.theme_preview_frame = QFrame()
        self.theme_preview_frame.setFrameShape(QFrame.Shape.StyledPanel)
        preview_layout = QVBoxLayout(self.theme_preview_frame)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        self.theme_preview_title = QLabel("테마 미리보기")
        self.theme_preview_colors = QLabel("")
        self.theme_preview_colors.setWordWrap(True)
        preview_layout.addWidget(self.theme_preview_title)
        preview_layout.addWidget(self.theme_preview_colors)
        tvbox.addWidget(self.theme_preview_frame)

        preview_btn = QPushButton("테마 폴더 안내")
        preview_btn.setStyleSheet(secondary_btn_style())
        preview_btn.clicked.connect(self._show_theme_hint)
        tvbox.addWidget(preview_btn)

        self.theme_preset_combo.currentIndexChanged.connect(self._refresh_theme_preview)
        self._refresh_theme_preview()

        vbox.addWidget(theme_group)
        vbox.addStretch()
        return widget

    def _create_extensions_tab(self):
        widget = QWidget()
        vbox = QVBoxLayout(widget)

        plugin_group = QGroupBox("사용자 플러그인")
        pvbox = QVBoxLayout(plugin_group)

        try:
            from core.resource_manager import ResourceManager
            plugin_dir = ResourceManager.ensure_plugin_files()
        except Exception:
            plugin_dir = os.path.join(os.getcwd(), "plugins")

        pvbox.addWidget(QLabel("플러그인 폴더:"))
        self.plugin_dir_input = QLineEdit(plugin_dir)
        self.plugin_dir_input.setReadOnly(True)
        pvbox.addWidget(self.plugin_dir_input)

        self.plugin_list = QListWidget()
        pvbox.addWidget(self.plugin_list)

        btn_row = QHBoxLayout()
        open_btn = QPushButton("플러그인 폴더 열기")
        open_btn.setStyleSheet(secondary_btn_style())
        open_btn.clicked.connect(self._open_plugin_folder)
        reload_btn = QPushButton("플러그인 목록 새로고침")
        reload_btn.setStyleSheet(secondary_btn_style())
        reload_btn.clicked.connect(self._refresh_plugin_list)
        btn_row.addWidget(open_btn)
        btn_row.addWidget(reload_btn)
        pvbox.addLayout(btn_row)

        vbox.addWidget(plugin_group)
        vbox.addStretch()
        self._refresh_plugin_list()
        return widget

    # ── 유틸리티 및 이벤트 ───────────────────────────────────────────────────────

    @staticmethod
    def _set_combo(combo: QComboBox, value: str):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    def _on_llm_changed(self):
        selected = self.llm_provider_combo.currentData()
        for _label, data, _key, _ph in _LLM_PROVIDERS:
            grp = self._tts_groups.get(f"_llm_{data}")
            if grp:
                grp.setVisible(data == selected)

    def _on_tts_changed(self):
        selected = self.tts_mode_combo.currentData()
        for key in [d for _, d in _TTS_MODES]:
            grp = self._tts_groups.get(key)
            if grp:
                grp.setVisible(key == selected)

    def _show_theme_hint(self):
        QMessageBox.information(
            self,
            "테마 폴더",
            f"테마 JSON 파일은 아래 폴더에서 직접 수정할 수 있습니다.\n\n{theme_dir()}\n\n저장 후 설정창에서 다시 적용하면 열린 UI에 즉시 반영됩니다.",
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
        self.theme_preview_title.setText(f"{palette.name} 미리보기")
        self.theme_preview_colors.setText(
            f"Primary {primary} | Accent {accent} | Font {palette.font_family}"
        )

    def _refresh_plugin_list(self):
        self.plugin_list.clear()
        try:
            from core.plugin_loader import get_plugin_manager
            plugins = get_plugin_manager().discover_plugins()
        except Exception as exc:
            item = QListWidgetItem(f"플러그인 목록 로드 실패: {exc}")
            self.plugin_list.addItem(item)
            return

        if not plugins:
            self.plugin_list.addItem(QListWidgetItem("플러그인이 없습니다. sample_plugin.py를 복사해 시작할 수 있습니다."))
            return
        for plugin in plugins:
            label = f"{plugin.name} ({plugin.version}) - {plugin.description or '설명 없음'}"
            self.plugin_list.addItem(QListWidgetItem(label))

    def _open_plugin_folder(self):
        path = self.plugin_dir_input.text().strip()
        if not path:
            return
        try:
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            if not opened:
                raise RuntimeError("폴더 열기 실패")
        except Exception:
            QMessageBox.information(self, "플러그인 폴더", path)

    # ── 저장 로직 ───────────────────────────────────────────────────────────────

    def _save(self):
        # LLM 키 수집
        llm_keys = {}
        for _label, data, settings_key, _ph in _LLM_PROVIDERS:
            inp = self._llm_key_inputs.get(data)
            if inp:
                llm_keys[settings_key] = inp.text().strip()

        new_settings = {
            # RP
            "personality": self.personality_input.toPlainText().strip(),
            "scenario": self.scenario_input.toPlainText().strip(),
            "system_prompt": self.system_input.toPlainText().strip(),
            "history_instruction": self.history_input.toPlainText().strip(),
            
            # LLM
            "llm_provider": self.llm_provider_combo.currentData(),
            "llm_model": self.llm_model_input.text().strip(),
            "llm_planner_model": self.llm_planner_model_input.text().strip(),
            "llm_execution_model": self.llm_execution_model_input.text().strip(),
            **llm_keys,
            
            # TTS
            "tts_mode": self.tts_mode_combo.currentData(),
            "fish_api_key": self.fish_key_input.text().strip(),
            "fish_reference_id": self.fish_ref_input.text().strip(),
            "cosyvoice_reference_text": self.cosyvoice_ref_text.toPlainText().strip(),
            "cosyvoice_speed": self._float(self.cosyvoice_speed_input.text(), 0.9),
            "openai_tts_api_key": self.openai_tts_key_input.text().strip(),
            "openai_tts_voice": self.openai_tts_voice_combo.currentData(),
            "openai_tts_model": self.openai_tts_model_combo.currentData(),
            "elevenlabs_api_key": self.elevenlabs_key_input.text().strip(),
            "elevenlabs_voice_id": self.elevenlabs_voice_id_input.text().strip(),
            "edge_tts_voice": self.edge_voice_combo.currentData(),
            "edge_tts_rate": self.edge_rate_input.text().strip() or "+0%",
            
            # Device
            "microphone": self.mic_combo.currentData(),
            "ui_theme_preset": self.theme_preset_combo.currentData(),
            "ui_theme_scale": max(0.9, min(1.35, self._float(self.theme_scale_input.text(), 1.0))),
            "ui_font_family": self.theme_font_input.text().strip(),
        }

        merged_settings = {**self.original_settings, **new_settings}
        self.changed_keys = {
            key for key, value in merged_settings.items()
            if self.original_settings.get(key) != value
        }
        ConfigManager.save_settings(merged_settings)

        if self.llm_settings_changed():
            try:
                from llm_provider import reset_llm_provider
                reset_llm_provider()
            except Exception as exc:
                logging.debug(f"LLM provider reset 생략: {exc}")

        if self.theme_settings_changed():
            QMessageBox.information(
                self,
                "테마 저장",
                "테마 설정이 저장되었습니다.\n열려 있는 UI에는 즉시 반영되며, TTS나 워커는 다시 시작하지 않습니다.",
            )

        self.accept()

    def tts_settings_changed(self) -> bool:
        return any(key in self.changed_keys for key in self.TTS_KEYS)

    def llm_settings_changed(self) -> bool:
        return any(key in self.changed_keys for key in self.LLM_KEYS)

    def theme_settings_changed(self) -> bool:
        return any(key in self.changed_keys for key in self.THEME_KEYS)

    @staticmethod
    def _float(text: str, default: float) -> float:
        try:
            return float(text)
        except (ValueError, TypeError):
            return default

"""
설정 창 GUI — 탭 기반 구성 (RP, AI & TTS, 장치)
"""
import importlib
import logging
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QTextEdit, QPushButton,
    QComboBox, QGroupBox, QScrollArea, QWidget,
    QTabWidget, QMessageBox, QListWidget, QListWidgetItem, QFrame,
    QFileDialog, QProgressDialog,
)
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QFont, QDesktopServices
from PySide6.QtCore import QUrl
from core.config_manager import ConfigManager
from ui.theme import (
    FONT_KO, FONT_SIZE_NORMAL, COLOR_SUCCESS,
    TAB_STYLE, SCROLLBAR_STYLE, INPUT_STYLE,
    available_theme_presets, secondary_btn_style, theme_dir, load_theme_palette,
)
from ui.theme_editor import ThemeEditorDialog
from ui.common import create_muted_label
from ui.local_installers import (
    CosyVoiceInstallerThread,
    LocalInstallSection,
    OllamaInstallDialog,
    OllamaInstallerThread,
)
from ui.marketplace_browser import MarketplaceFetchThread, MarketplaceInstallThread

# ── API 검증 스레드 ────────────────────────────────────────────────────────────

class _ValidatorThread(QThread):
    """LLM API 키 + 모델 검증을 백그라운드에서 실행하는 스레드."""
    done = Signal(bool, str)  # (success, message)

    def __init__(self, provider: str, api_key: str, model: str):
        super().__init__()
        self.provider = provider
        self.api_key = api_key
        self.model = model

    def _validate_anthropic_client(self, client, model: str) -> None:
        messages_api = getattr(client, "messages")
        create_fn = getattr(messages_api, "create")
        create_fn(
            model=model,
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )

    def _validate_openai_client(self, client, model: str) -> None:
        chat_api = getattr(client, "chat")
        completions_api = getattr(chat_api, "completions")
        create_fn = getattr(completions_api, "create")
        create_fn(
            model=model,
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )

    def run(self):
        try:
            from agent.llm_provider import _PROVIDER_CONFIG
            cfg = _PROVIDER_CONFIG.get(self.provider, _PROVIDER_CONFIG["groq"])
            model = self.model.strip() or cfg["default_model"]

            if self.provider == "anthropic":
                anthropic_module = importlib.import_module("anthropic")
                client = anthropic_module.Anthropic(api_key=self.api_key)
                self._validate_anthropic_client(client, model)
            else:
                openai_module = importlib.import_module("openai")
                kwargs: dict = {"api_key": self.api_key}
                if self.provider == "ollama":
                    kwargs["base_url"] = ConfigManager.get("ollama_base_url", "http://localhost:11434/v1")
                elif cfg["base_url"]:
                    kwargs["base_url"] = cfg["base_url"]
                client = openai_module.OpenAI(**kwargs)
                self._validate_openai_client(client, model)
            self.done.emit(True, f"✓ {model} 연결 성공")
        except Exception as e:
            if self.provider == "ollama":
                self.done.emit(False, "✗ Ollama 서버에 연결할 수 없어요. Ollama 실행 여부를 확인하세요.")
                return
            msg = str(e)
            # 핵심 오류 메시지만 표시
            for marker in ("Error code:", "status code", "error_code"):
                if marker in msg:
                    msg = msg.split("\n")[0]
                    break
            self.done.emit(False, f"✗ {msg[:80]}")


# ── 제공자 정의 ────────────────────────────────────────────────────────────────

_LLM_PROVIDERS = [
    # (표시 이름,          data 키,       settings 키,          placeholder)
    ("Groq (Llama 3.3, 무료)", "groq",       "groq_api_key",       "https://console.groq.com 에서 무료 발급"),
    ("OpenAI (GPT-4o)",        "openai",     "openai_api_key",     "https://platform.openai.com/api-keys"),
    ("Anthropic (Claude)",     "anthropic",  "anthropic_api_key",  "https://console.anthropic.com"),
    ("Mistral AI",             "mistral",    "mistral_api_key",    "https://console.mistral.ai"),
    ("Google Gemini",          "gemini",     "gemini_api_key",     "https://aistudio.google.com/app/apikey"),
    ("OpenRouter (멀티모델)",   "openrouter",   "openrouter_api_key",  "https://openrouter.ai/keys"),
    ("NVIDIA NIM",             "nvidia_nim",   "nvidia_nim_api_key",  "https://build.nvidia.com 에서 nvapi- 키 발급"),
    ("Ollama (로컬 LLM)",      "ollama",       "",                    "Ollama 설치 후 사용 가능 — API 키 불필요"),
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
        "scenario", "history_instruction",
    }
    THEME_KEYS = {"ui_theme_preset", "ui_theme_scale", "ui_font_family"}
    STT_KEYS = {
        "stt_provider", "whisper_model", "whisper_device", "whisper_compute_type",
        "wake_words", "stt_energy_threshold", "stt_dynamic_energy",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("아리 설정")
        self.setMinimumWidth(600)
        self.setMinimumHeight(550)
        self.settings = ConfigManager.load_settings()
        self.original_settings = dict(self.settings)
        self.changed_keys = set()
        self._llm_key_inputs = {}         # data 키 → QLineEdit
        self._llm_model_inputs = {}       # data 키 → QLineEdit (테스트 모델명)
        self._tts_groups = {}             # data 키 → QGroupBox
        self._role_provider_combos = {}   # role 키 → QComboBox
        self._validator_threads = {}      # data 키 → _ValidatorThread
        self._validate_labels = {}        # data 키 → QLabel
        self._ollama_install_thread: OllamaInstallerThread | None = None
        self._ollama_progress_dialog: QProgressDialog | None = None
        self._cosyvoice_install_thread: CosyVoiceInstallerThread | None = None
        self._cosyvoice_progress_dialog: QProgressDialog | None = None
        self._market_fetch_thread: MarketplaceFetchThread | None = None
        self._market_install_thread: MarketplaceInstallThread | None = None
        self._market_items: list[dict] = []
        self._editor_dialog: ThemeEditorDialog | None = None
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

        # 1. 로컬 설치
        self.local_install_section = LocalInstallSection(self)
        self.local_install_section.ollama_install_requested.connect(self._open_ollama_installer)
        self.local_install_section.cosyvoice_install_requested.connect(self._install_cosyvoice)
        vbox.addWidget(self.local_install_section)

        # 2. AI (LLM) 설정
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
        self.ollama_hint_label = create_muted_label(
            "Ollama 사용 시 API 키는 필요 없습니다. 서버 주소는 기본적으로 "
            "http://localhost:11434/v1 를 사용합니다."
        )
        llm_vbox.addWidget(self.ollama_hint_label)
        llm_vbox.addWidget(QLabel("Ollama 서버 주소:"))
        self.ollama_url_input = QLineEdit(self.settings.get("ollama_base_url", "http://localhost:11434/v1"))
        self.ollama_url_input.setPlaceholderText("http://localhost:11434/v1")
        llm_vbox.addWidget(self.ollama_url_input)

        llm_vbox.addWidget(QLabel("플래너 제공자 (선택):"))
        self._role_provider_combos["llm_planner_provider"] = self._make_role_provider_combo(
            self.settings.get("llm_planner_provider", "")
        )
        llm_vbox.addWidget(self._role_provider_combos["llm_planner_provider"])

        llm_vbox.addWidget(QLabel("플래너 모델 (선택):"))
        self.llm_planner_model_input = QLineEdit(self.settings.get("llm_planner_model", ""))
        self.llm_planner_model_input.setPlaceholderText("비워두면 기본 모델과 동일")
        llm_vbox.addWidget(self.llm_planner_model_input)

        llm_vbox.addWidget(QLabel("실행/수정 제공자 (선택):"))
        self._role_provider_combos["llm_execution_provider"] = self._make_role_provider_combo(
            self.settings.get("llm_execution_provider", "")
        )
        llm_vbox.addWidget(self._role_provider_combos["llm_execution_provider"])

        llm_vbox.addWidget(QLabel("실행/수정 모델 (선택):"))
        self.llm_execution_model_input = QLineEdit(self.settings.get("llm_execution_model", ""))
        self.llm_execution_model_input.setPlaceholderText("비워두면 기본 모델과 동일")
        llm_vbox.addWidget(self.llm_execution_model_input)

        vbox.addWidget(llm_group)

        # API Key 입력 그룹 (모든 제공자 항상 표시)
        api_group = QGroupBox("제공자별 API Key")
        api_vbox = QVBoxLayout(api_group)
        api_vbox.addWidget(create_muted_label(
            "사용할 제공자의 API Key와 모델명을 입력한 뒤 [검증]으로 연결을 확인하세요."
        ))
        for _label, data, key, placeholder in _LLM_PROVIDERS:
            from agent.llm_provider import _PROVIDER_CONFIG
            default_model = _PROVIDER_CONFIG.get(data, {}).get("default_model", "")

            api_vbox.addWidget(QLabel(f"{_label}:"))

            # API 키 행
            key_row = QHBoxLayout()
            key_inp = QLineEdit(self.settings.get(key, "") if key else "")
            key_inp.setPlaceholderText(placeholder)
            key_inp.setEchoMode(QLineEdit.EchoMode.Password)
            key_row.addWidget(key_inp)
            validate_btn = QPushButton("검증")
            validate_btn.setFixedWidth(54)
            validate_btn.setStyleSheet(secondary_btn_style())
            key_row.addWidget(validate_btn)
            api_vbox.addLayout(key_row)

            # 모델 행 — 해당 제공자에 설정된 모델명을 초기값으로 채움
            model_row = QHBoxLayout()
            prefilled_model = self._get_model_for_provider(data)
            model_inp = QLineEdit(prefilled_model)
            model_inp.setPlaceholderText(f"모델명 (기본: {default_model})")
            model_row.addWidget(model_inp)
            status_lbl = QLabel("")
            status_lbl.setWordWrap(True)
            status_lbl.setFixedWidth(220)
            model_row.addWidget(status_lbl)
            api_vbox.addLayout(model_row)

            self._llm_key_inputs[data] = key_inp
            self._llm_model_inputs[data] = model_inp
            self._validate_labels[data] = status_lbl

            # 클로저 캡처용 기본값
            validate_btn.clicked.connect(
                lambda checked=False, d=data: self._run_validation(d)
            )

        vbox.addWidget(api_group)

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

        # CosyVoice 설치 경로
        cvl.addWidget(QLabel("CosyVoice 설치 경로 (비워두면 자동 감지):"))
        dir_row = QHBoxLayout()
        self.cosyvoice_dir_input = QLineEdit(self.settings.get("cosyvoice_dir", ""))
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

        stt_group = QGroupBox("음성 인식")
        stt_vbox = QVBoxLayout(stt_group)
        stt_vbox.addWidget(create_muted_label("STT 엔진, Whisper 설정, 마이크 감도, 웨이크워드를 설정합니다."))
        stt_btn = QPushButton("음성 인식 설정...")
        stt_btn.clicked.connect(self._open_stt_settings)
        stt_vbox.addWidget(stt_btn)

        vbox.addWidget(stt_group)

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

        self.editor_toggle_btn = QPushButton("🎨 팔레트 직접 편집")
        self.editor_toggle_btn.clicked.connect(self._toggle_theme_editor)
        tvbox.addWidget(self.editor_toggle_btn)

        self.theme_preset_combo.currentIndexChanged.connect(self._on_theme_preset_changed)
        self._refresh_theme_preview()

        vbox.addWidget(theme_group)
        vbox.addStretch()
        return widget

    def _create_extensions_tab(self):
        widget = QWidget()
        vbox = QVBoxLayout(widget)

        marketplace_group = QGroupBox("마켓플레이스")
        mvbox = QVBoxLayout(marketplace_group)
        mvbox.addWidget(create_muted_label(
            "설정창 안에서 플러그인을 검색하고 바로 설치할 수 있습니다."
        ))

        search_row = QHBoxLayout()
        self.market_search_input = QLineEdit()
        self.market_search_input.setPlaceholderText("플러그인 검색")
        search_row.addWidget(self.market_search_input)
        market_search_btn = QPushButton("검색")
        market_search_btn.setStyleSheet(secondary_btn_style())
        market_search_btn.clicked.connect(self._refresh_marketplace_list)
        search_row.addWidget(market_search_btn)
        mvbox.addLayout(search_row)

        self.marketplace_list = QListWidget()
        mvbox.addWidget(self.marketplace_list)

        self.marketplace_status_label = create_muted_label("")
        mvbox.addWidget(self.marketplace_status_label)

        market_btn_row = QHBoxLayout()
        self.market_install_btn = QPushButton("선택 플러그인 설치")
        self.market_install_btn.setStyleSheet(secondary_btn_style())
        self.market_install_btn.clicked.connect(self._install_selected_marketplace_plugin)
        market_refresh_btn = QPushButton("목록 새로고침")
        market_refresh_btn.setStyleSheet(secondary_btn_style())
        market_refresh_btn.clicked.connect(self._refresh_marketplace_list)
        market_open_btn = QPushButton("웹 마켓플레이스 열기")
        market_open_btn.setStyleSheet(secondary_btn_style())
        market_open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://ari-voice-command.vercel.app/marketplace"))
        )
        market_btn_row.addWidget(self.market_install_btn)
        market_btn_row.addWidget(market_refresh_btn)
        market_btn_row.addWidget(market_open_btn)
        mvbox.addLayout(market_btn_row)

        vbox.addWidget(marketplace_group)

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
        self._refresh_marketplace_list()
        return widget

    # ── 유틸리티 및 이벤트 ───────────────────────────────────────────────────────

    def _make_role_provider_combo(self, current_value: str) -> QComboBox:
        """역할별 제공자 선택 콤보박스 생성 (기본 + 7개 제공자)."""
        combo = QComboBox()
        combo.addItem("(기본 제공자와 동일)", "")
        for label, data, _key, _ph in _LLM_PROVIDERS:
            combo.addItem(label, data)
        self._set_combo(combo, current_value)
        return combo

    @staticmethod
    def _set_combo(combo: QComboBox, value: str):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    def _get_model_for_provider(self, provider_key: str) -> str:
        """현재 설정에서 해당 제공자에 할당된 모델명을 반환 (우선순위: 기본 > 플래너 > 실행)."""
        s = self.settings
        if s.get("llm_provider") == provider_key:
            return s.get("llm_model", "")
        if s.get("llm_planner_provider") == provider_key:
            return s.get("llm_planner_model", "")
        if s.get("llm_execution_provider") == provider_key:
            return s.get("llm_execution_model", "")
        return ""

    def _on_llm_changed(self):
        provider = self.llm_provider_combo.currentData()
        is_ollama = provider == "ollama"
        self.ollama_hint_label.setVisible(is_ollama)
        self.ollama_url_input.setVisible(is_ollama)

    def _open_ollama_installer(self):
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
            None,
            0,
            0,
            self,
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
            self._set_combo(self.llm_provider_combo, "ollama")
            self.ollama_url_input.setText(result.get("base_url", "http://localhost:11434/v1"))
            installed_models = result.get("installed_models") or []
            if installed_models and not self.llm_model_input.text().strip():
                self.llm_model_input.setText(installed_models[0])
                model_input = self._llm_model_inputs.get("ollama")
                if model_input and not model_input.text().strip():
                    model_input.setText(installed_models[0])
            self._on_llm_changed()
            QMessageBox.information(self, "Ollama 설치", message)
        else:
            QMessageBox.warning(self, "Ollama 설치", message)

        self._ollama_install_thread = None

    def _run_validation(self, provider: str):
        api_key = self._llm_key_inputs[provider].text().strip()
        lbl = self._validate_labels[provider]
        if provider != "ollama" and not api_key:
            lbl.setText("⚠ API Key를 입력하세요.")
            lbl.setStyleSheet("color: #e67e22;")
            return
        if provider == "ollama":
            api_key = "ollama"

        model = self._llm_model_inputs[provider].text().strip()
        if not model:
            from agent.llm_provider import _PROVIDER_CONFIG
            model = _PROVIDER_CONFIG.get(provider, {}).get("default_model", "")
            lbl.setText(f"검증 중... (기본 모델: {model})")
        else:
            lbl.setText("검증 중...")
        lbl.setStyleSheet("color: #888;")

        # 이전 스레드 정리
        old = self._validator_threads.get(provider)
        if old and old.isRunning():
            old.quit()

        thread = _ValidatorThread(provider, api_key, model)
        thread.done.connect(lambda ok, msg, p=provider: self._on_validation_done(p, ok, msg))
        self._validator_threads[provider] = thread
        thread.start()

    def _on_validation_done(self, provider: str, success: bool, message: str):
        lbl = self._validate_labels.get(provider)
        if not lbl:
            return
        lbl.setText(message)
        lbl.setStyleSheet(f"color: {'#27ae60' if success else '#e74c3c'}; font-weight: bold;")

    def _on_tts_changed(self):
        selected = self.tts_mode_combo.currentData()
        for key in [d for _, d in _TTS_MODES]:
            grp = self._tts_groups.get(key)
            if grp:
                grp.setVisible(key == selected)

    def _open_stt_settings(self):
        from ui.stt_settings_dialog import STTSettingsDialog
        dlg = STTSettingsDialog(self)
        dlg.exec()

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

    def _installed_plugin_names(self) -> set[str]:
        try:
            from core.plugin_loader import get_plugin_manager
            return {plugin.name for plugin in get_plugin_manager().discover_plugins()}
        except Exception:
            return set()

    def _refresh_marketplace_list(self):
        if self._market_fetch_thread and self._market_fetch_thread.isRunning():
            return

        self.marketplace_status_label.setText("마켓플레이스 목록을 불러오는 중...")
        self.marketplace_status_label.setStyleSheet("color: #888;")
        self.market_install_btn.setEnabled(False)
        self.marketplace_list.clear()

        self._market_fetch_thread = MarketplaceFetchThread(
            search=self.market_search_input.text(),
        )
        self._market_fetch_thread.done.connect(self._on_marketplace_fetch_done)
        self._market_fetch_thread.start()

    def _on_marketplace_fetch_done(self, success: bool, items: object, message: str):
        self._market_fetch_thread = None
        self.marketplace_list.clear()
        self._market_items = list(items) if isinstance(items, list) else []

        if not success:
            self.marketplace_status_label.setText(f"목록 로드 실패: {message}")
            self.marketplace_status_label.setStyleSheet("color: #e74c3c;")
            self.market_install_btn.setEnabled(False)
            return

        installed_names = self._installed_plugin_names()
        for item in self._market_items:
            name = str(item.get("name", "이름 없음"))
            version = str(item.get("version", "0.0.0"))
            install_count = int(item.get("install_count", 0) or 0)
            desc = str(item.get("description", "") or "설명 없음")
            status = "설치됨" if name in installed_names else "설치 가능"
            label = f"{name} v{version} [{status}] ({install_count} installs)\n{desc}"
            list_item = QListWidgetItem(label)
            list_item.setData(Qt.UserRole, item)
            self.marketplace_list.addItem(list_item)

        if self._market_items:
            self.marketplace_status_label.setText(f"{len(self._market_items)}개 플러그인을 불러왔습니다.")
            self.marketplace_status_label.setStyleSheet("color: #27ae60;")
            self.market_install_btn.setEnabled(True)
        else:
            self.marketplace_status_label.setText("표시할 플러그인이 없습니다.")
            self.marketplace_status_label.setStyleSheet("color: #888;")
            self.market_install_btn.setEnabled(False)

    def _install_selected_marketplace_plugin(self):
        item = self.marketplace_list.currentItem()
        if item is None:
            QMessageBox.information(self, "마켓플레이스", "설치할 플러그인을 먼저 선택하세요.")
            return

        payload = item.data(Qt.UserRole) or {}
        plugin_id = str(payload.get("id", "") or "")
        plugin_name = str(payload.get("name", "") or "플러그인")
        if not plugin_id:
            QMessageBox.warning(self, "마켓플레이스", "선택한 플러그인의 ID를 찾지 못했습니다.")
            return

        confirm = QMessageBox.question(
            self,
            "플러그인 설치",
            f"{plugin_name} 플러그인을 설치할까요?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if confirm != QMessageBox.Yes:
            return

        self.market_install_btn.setEnabled(False)
        self.marketplace_status_label.setText(f"{plugin_name} 설치 중...")
        self.marketplace_status_label.setStyleSheet("color: #888;")

        self._market_install_thread = MarketplaceInstallThread(plugin_id)
        self._market_install_thread.done.connect(self._on_marketplace_install_done)
        self._market_install_thread.start()

    def _on_marketplace_install_done(self, success: bool, message: str):
        self._market_install_thread = None
        if success:
            self.marketplace_status_label.setText(message)
            self.marketplace_status_label.setStyleSheet("color: #27ae60;")
            self._refresh_plugin_list()
            self._refresh_marketplace_list()
            QMessageBox.information(self, "마켓플레이스", message)
        else:
            self.market_install_btn.setEnabled(True)
            self.marketplace_status_label.setText(message)
            self.marketplace_status_label.setStyleSheet("color: #e74c3c;")
            QMessageBox.warning(self, "마켓플레이스", message)

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
            if inp and settings_key:
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
            "llm_planner_provider": self._role_provider_combos["llm_planner_provider"].currentData(),
            "llm_planner_model": self.llm_planner_model_input.text().strip(),
            "llm_execution_provider": self._role_provider_combos["llm_execution_provider"].currentData(),
            "llm_execution_model": self.llm_execution_model_input.text().strip(),
            "ollama_base_url": self.ollama_url_input.text().strip() or "http://localhost:11434/v1",
            **llm_keys,
            
            # TTS
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
                from agent.llm_provider import reset_llm_provider
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

    def _browse_cosyvoice_dir(self):
        path = QFileDialog.getExistingDirectory(self, "CosyVoice 설치 폴더 선택",
                                                self.cosyvoice_dir_input.text() or "C:/")
        if path:
            self.cosyvoice_dir_input.setText(path)
            self._check_cosyvoice_dir(path)

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
            None,
            0,
            0,
            self,
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
        """입력된 경로에 CosyVoice 구조가 있는지 확인 후 상태 표시."""
        import os
        marker = os.path.join(path, "pretrained_models")
        if os.path.isdir(marker):
            self.cosyvoice_dir_status.setText("✓ 유효한 CosyVoice 경로")
            self.cosyvoice_dir_status.setStyleSheet("color: #27ae60;")
        else:
            self.cosyvoice_dir_status.setText("⚠ pretrained_models 폴더가 없습니다. 경로를 확인하세요.")
            self.cosyvoice_dir_status.setStyleSheet("color: #e67e22;")

    def closeEvent(self, event):
        for thread in self._validator_threads.values():
            if thread.isRunning():
                thread.quit()
                thread.wait(1000)
        for thread in (
            self._ollama_install_thread,
            self._cosyvoice_install_thread,
            self._market_fetch_thread,
            self._market_install_thread,
        ):
            if thread and thread.isRunning():
                thread.quit()
                thread.wait(1000)
        super().closeEvent(event)

    @staticmethod
    def _float(text: str, default: float) -> float:
        try:
            return float(text)
        except (ValueError, TypeError):
            return default

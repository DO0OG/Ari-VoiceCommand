"""
LLM 제공자 설정 페이지 위젯
"""
import importlib

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QGroupBox,
    QScrollArea, QCheckBox,
)
from PySide6.QtCore import QThread, Signal

from core.config_manager import ConfigManager
from i18n.translator import _
from ui.theme import SCROLLBAR_STYLE, secondary_btn_style
from ui.common import create_muted_label

# ── 제공자 정의 ────────────────────────────────────────────────────────────────

LLM_PROVIDERS = [
    # (표시 이름,          data 키,       settings 키,          placeholder)
    (_("Groq (Llama 3.3, 무료)"), "groq",       "groq_api_key",       _("https://console.groq.com 에서 무료 발급")),
    (_("OpenAI (GPT-4o)"),        "openai",     "openai_api_key",     _("https://platform.openai.com/api-keys")),
    (_("Anthropic (Claude)"),     "anthropic",  "anthropic_api_key",  _("https://console.anthropic.com")),
    (_("Mistral AI"),             "mistral",    "mistral_api_key",    _("https://console.mistral.ai")),
    (_("Google Gemini"),          "gemini",     "gemini_api_key",     _("https://aistudio.google.com/app/apikey")),
    (_("OpenRouter (멀티모델)"),   "openrouter",   "openrouter_api_key",  _("https://openrouter.ai/keys")),
    (_("NVIDIA NIM"),             "nvidia_nim",   "nvidia_nim_api_key",  _("https://build.nvidia.com 에서 nvapi- 키 발급")),
    (_("Ollama (로컬 LLM)"),      "ollama",       "",                    _("Ollama 설치 후 사용 가능 — API 키 불필요")),
]


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
            for marker in ("Error code:", "status code", "error_code"):
                if marker in msg:
                    msg = msg.split("\n")[0]
                    break
            self.done.emit(False, f"✗ {msg[:80]}")


# ── LLM 설정 페이지 ────────────────────────────────────────────────────────────

class _LLMSettingsPage(QWidget):
    """LLM 제공자 설정 탭 위젯."""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._llm_key_inputs: dict[str, QLineEdit] = {}
        self._llm_model_inputs: dict[str, QLineEdit] = {}
        self._validate_labels: dict[str, QLabel] = {}
        self._validator_threads: dict[str, _ValidatorThread] = {}
        self._role_provider_combos: dict[str, QComboBox] = {}
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

        # AI (LLM) 설정 그룹
        llm_group = QGroupBox(_("AI (LLM) 엔진 설정"))
        llm_vbox = QVBoxLayout(llm_group)

        llm_vbox.addWidget(QLabel(_("제공자 선택:")))
        self.llm_provider_combo = QComboBox()
        for label, data, _key, _ph in LLM_PROVIDERS:
            self.llm_provider_combo.addItem(label, data)
        self._set_combo(self.llm_provider_combo, self._settings.get("llm_provider", "groq"))
        self.llm_provider_combo.currentIndexChanged.connect(self._on_llm_changed)
        llm_vbox.addWidget(self.llm_provider_combo)

        llm_vbox.addWidget(QLabel(_("모델 이름 (비워두면 기본값):")))
        self.llm_model_input = QLineEdit(self._settings.get("llm_model", ""))
        self.llm_model_input.setPlaceholderText(_("예: gpt-4o, llama-3.3-70b-versatile..."))
        llm_vbox.addWidget(self.llm_model_input)

        self.ollama_hint_label = create_muted_label(
            _("Ollama 사용 시 API 키는 필요 없습니다. 서버 주소는 기본적으로 ") +
            "http://localhost:11434/v1 " + _("를 사용합니다.")
        )
        llm_vbox.addWidget(self.ollama_hint_label)
        llm_vbox.addWidget(QLabel(_("Ollama 서버 주소:")))
        self.ollama_url_input = QLineEdit(self._settings.get("ollama_base_url", "http://localhost:11434/v1"))
        self.ollama_url_input.setPlaceholderText("http://localhost:11434/v1")
        llm_vbox.addWidget(self.ollama_url_input)

        self.llm_router_checkbox = QCheckBox(_("작업 유형별 자동 라우팅 사용"))
        self.llm_router_checkbox.setChecked(bool(self._settings.get("llm_router_enabled", True)))
        self.llm_router_checkbox.setToolTip(
            _("분석/계획과 실행/수정 요청을 구분해 역할별 제공자·모델 설정을 우선 사용합니다.")
        )
        llm_vbox.addWidget(self.llm_router_checkbox)

        llm_vbox.addWidget(QLabel(_("플래너 제공자 (선택):")))
        self._role_provider_combos["llm_planner_provider"] = self._make_role_provider_combo(
            self._settings.get("llm_planner_provider", "")
        )
        llm_vbox.addWidget(self._role_provider_combos["llm_planner_provider"])

        llm_vbox.addWidget(QLabel(_("플래너 모델 (선택):")))
        self.llm_planner_model_input = QLineEdit(self._settings.get("llm_planner_model", ""))
        self.llm_planner_model_input.setPlaceholderText(_("비워두면 기본 모델과 동일"))
        llm_vbox.addWidget(self.llm_planner_model_input)

        llm_vbox.addWidget(QLabel(_("실행/수정 제공자 (선택):")))
        self._role_provider_combos["llm_execution_provider"] = self._make_role_provider_combo(
            self._settings.get("llm_execution_provider", "")
        )
        llm_vbox.addWidget(self._role_provider_combos["llm_execution_provider"])

        llm_vbox.addWidget(QLabel(_("실행/수정 모델 (선택):")))
        self.llm_execution_model_input = QLineEdit(self._settings.get("llm_execution_model", ""))
        self.llm_execution_model_input.setPlaceholderText(_("비워두면 기본 모델과 동일"))
        llm_vbox.addWidget(self.llm_execution_model_input)

        vbox.addWidget(llm_group)

        # 제공자별 API Key 그룹
        api_group = QGroupBox(_("제공자별 API Key"))
        api_vbox = QVBoxLayout(api_group)
        api_vbox.addWidget(create_muted_label(
            _("사용할 제공자의 API Key와 모델명을 입력한 뒤 [검증]으로 연결을 확인하세요.")
        ))
        for _label, data, key, placeholder in LLM_PROVIDERS:
            from agent.llm_provider import _PROVIDER_CONFIG
            default_model = _PROVIDER_CONFIG.get(data, {}).get("default_model", "")

            api_vbox.addWidget(QLabel(f"{_label}:"))

            # API 키 행
            key_row = QHBoxLayout()
            key_inp = QLineEdit(self._settings.get(key, "") if key else "")
            key_inp.setPlaceholderText(placeholder)
            key_inp.setEchoMode(QLineEdit.EchoMode.Password)
            key_row.addWidget(key_inp)
            validate_btn = QPushButton(_("검증"))
            validate_btn.setFixedWidth(54)
            validate_btn.setStyleSheet(secondary_btn_style())
            key_row.addWidget(validate_btn)
            api_vbox.addLayout(key_row)

            # 모델 행
            model_row = QHBoxLayout()
            prefilled_model = self._get_model_for_provider(data)
            model_inp = QLineEdit(prefilled_model)
            model_inp.setPlaceholderText(_("모델명 (기본: {model})").format(model=default_model))
            model_row.addWidget(model_inp)
            status_lbl = QLabel("")
            status_lbl.setWordWrap(True)
            status_lbl.setFixedWidth(220)
            model_row.addWidget(status_lbl)
            api_vbox.addLayout(model_row)

            self._llm_key_inputs[data] = key_inp
            self._llm_model_inputs[data] = model_inp
            self._validate_labels[data] = status_lbl

            validate_btn.clicked.connect(
                lambda checked=False, d=data: self._run_validation(d)
            )

        vbox.addWidget(api_group)
        vbox.addStretch()

        scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._on_llm_changed()

    # ── 유틸리티 ──────────────────────────────────────────────────────────────

    def _make_role_provider_combo(self, current_value: str) -> QComboBox:
        combo = QComboBox()
        combo.addItem(_("(기본 제공자와 동일)"), "")
        for label, data, _key, _ph in LLM_PROVIDERS:
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
        s = self._settings
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

    def _run_validation(self, provider: str):
        api_key = self._llm_key_inputs[provider].text().strip()
        lbl = self._validate_labels[provider]
        if provider != "ollama" and not api_key:
            lbl.setText(_("⚠ API Key를 입력하세요."))
            lbl.setStyleSheet("color: #e67e22;")
            return
        if provider == "ollama":
            api_key = "ollama"

        model = self._llm_model_inputs[provider].text().strip()
        if not model:
            from agent.llm_provider import _PROVIDER_CONFIG
            model = _PROVIDER_CONFIG.get(provider, {}).get("default_model", "")
            lbl.setText(_("검증 중... (기본 모델: {model})").format(model=model))
        else:
            lbl.setText(_("검증 중..."))
        lbl.setStyleSheet("color: #888;")

        old = self._validator_threads.get(provider)
        if old and old.isRunning():
            old.quit()
            old.wait(2000)

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

    # ── 공개 인터페이스 ────────────────────────────────────────────────────────

    def apply_ollama_result(self, base_url: str, installed_models: list[str]):
        """Ollama 설치 완료 후 SettingsDialog에서 호출."""
        self._set_combo(self.llm_provider_combo, "ollama")
        self.ollama_url_input.setText(base_url or "http://localhost:11434/v1")
        if installed_models and not self.llm_model_input.text().strip():
            self.llm_model_input.setText(installed_models[0])
            model_input = self._llm_model_inputs.get("ollama")
            if model_input and not model_input.text().strip():
                model_input.setText(installed_models[0])
        self._on_llm_changed()

    def get_values(self) -> dict:
        """현재 LLM 설정 값을 dict로 반환."""
        llm_keys = {}
        for _label, data, settings_key, _ph in LLM_PROVIDERS:
            inp = self._llm_key_inputs.get(data)
            if inp and settings_key:
                llm_keys[settings_key] = inp.text().strip()

        return {
            "llm_provider": self.llm_provider_combo.currentData(),
            "llm_model": self.llm_model_input.text().strip(),
            "llm_router_enabled": self.llm_router_checkbox.isChecked(),
            "llm_planner_provider": self._role_provider_combos["llm_planner_provider"].currentData(),
            "llm_planner_model": self.llm_planner_model_input.text().strip(),
            "llm_execution_provider": self._role_provider_combos["llm_execution_provider"].currentData(),
            "llm_execution_model": self.llm_execution_model_input.text().strip(),
            "ollama_base_url": self.ollama_url_input.text().strip() or "http://localhost:11434/v1",
            **llm_keys,
        }

    def cleanup_threads(self):
        """다이얼로그 닫힐 때 실행 중인 검증 스레드 정리."""
        for thread in self._validator_threads.values():
            if thread.isRunning():
                thread.quit()
                thread.wait(2000)

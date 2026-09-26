"""
LLM 제공자 설정 페이지 위젯
"""
import importlib
import uuid

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QGroupBox,
    QScrollArea, QCheckBox, QDialog, QFormLayout, QDialogButtonBox,
    QMessageBox,
)
from PySide6.QtCore import QThread, Signal, Qt

from core.config_manager import ConfigManager
from core.custom_llm_providers import (
    custom_api_key_name,
    get_custom_providers,
    normalize_custom_provider_settings,
)
from i18n.translator import _
from ui.theme import SCROLLBAR_STYLE, secondary_btn_style
from ui.common import create_muted_label

_live_validator_threads: set[QThread] = set()

# ── 제공자 정의 ────────────────────────────────────────────────────────────────

def _llm_providers():
    # (표시 이름, data 키, settings 키, placeholder)
    return [
        (_("Groq (Llama 3.3, 무료)"), "groq",       "groq_api_key",       _("https://console.groq.com 에서 무료 발급")),
        (_("OpenAI (GPT-4o)"),        "openai",     "openai_api_key",     _("https://platform.openai.com/api-keys")),
        (_("Anthropic (Claude)"),     "anthropic",  "anthropic_api_key",  _("https://console.anthropic.com")),
        (_("Mistral AI"),             "mistral",    "mistral_api_key",    _("https://console.mistral.ai")),
        (_("Google Gemini"),          "gemini",     "gemini_api_key",     _("https://aistudio.google.com/app/apikey")),
        (_("OpenRouter (멀티모델)"),   "openrouter",   "openrouter_api_key",  _("https://openrouter.ai/keys")),
        (_("NVIDIA NIM"),             "nvidia_nim",   "nvidia_nim_api_key",  _("https://build.nvidia.com 에서 nvapi- 키 발급")),
        (_("Ollama (로컬 LLM)"),      "ollama",       "",                    _("Ollama 설치 후 사용 가능 — API 키 불필요")),
    ]


# ── 사용자 지정 제공자 입력 ────────────────────────────────────────────────────

def _valid_custom_base_url(value: str) -> bool:
    key = "custom_" + "0" * 32
    candidate = {key: {"label": "validation", "base_url": value.strip(), "default_model": ""}}
    return key in get_custom_providers({"custom_llm_providers": candidate})


class _CustomProviderDialog(QDialog):
    def __init__(self, provider: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("사용자 지정 제공자 설정"))
        self._provider = provider or {}

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.label_input = QLineEdit(self._provider.get("label", ""))
        self.label_input.setPlaceholderText(_("예: My LLM"))
        self.base_url_input = QLineEdit(self._provider.get("base_url", ""))
        self.base_url_input.setPlaceholderText("https://example.com/v1")
        form.addRow(_("표시 이름"), self.label_input)
        form.addRow(_("기본 URL"), self.base_url_input)
        layout.addLayout(form)
        layout.addWidget(QLabel(_("API 키와 기본 모델은 제공자별 설정 목록에서 수정할 수 있습니다.")))

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #e74c3c;")
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(_("저장"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(_("취소"))
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_if_valid(self):
        if not self.label_input.text().strip():
            self.error_label.setText(_("표시 이름을 입력하세요."))
            return
        if not _valid_custom_base_url(self.base_url_input.text()):
            self.error_label.setText(_("기본 URL은 사용자 정보, 쿼리 또는 프래그먼트가 없는 http 또는 https 주소여야 합니다."))
            return
        self.accept()

    def get_values(self) -> dict:
        return {
            "label": self.label_input.text().strip(),
            "base_url": self.base_url_input.text().strip(),
        }


# ── API 검증 스레드 ────────────────────────────────────────────────────────────

class _ValidatorThread(QThread):
    """LLM API 키 + 모델 검증을 백그라운드에서 실행하는 스레드."""
    done = Signal(bool, str)  # (success, message)

    def __init__(self, provider: str, api_key: str, model: str, *, base_url: str = "", custom: bool = False):
        super().__init__()
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.custom = custom

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
            max_tokens=5,
            messages=[{"role": "user", "content": "hi"}],
        )

    def run(self):
        cfg = {}
        try:
            from agent.llm_provider import _PROVIDER_CONFIG
            cfg = {} if self.custom else _PROVIDER_CONFIG.get(self.provider, _PROVIDER_CONFIG["groq"])
            model = self.model.strip() or cfg.get("default_model", "")
            if not model:
                self.done.emit(False, _("기본 모델을 입력하세요."))
                return

            if self.provider == "anthropic":
                anthropic_module = importlib.import_module("anthropic")
                client = anthropic_module.Anthropic(api_key=self.api_key, timeout=10, max_retries=0)
                self._validate_anthropic_client(client, model)
            else:
                openai_module = importlib.import_module("openai")
                kwargs: dict = {"api_key": self.api_key or "not-needed", "timeout": 10, "max_retries": 0}
                if self.provider == "ollama":
                    kwargs["base_url"] = ConfigManager.get("ollama_base_url", "http://localhost:11434/v1")
                elif self.custom:
                    kwargs["base_url"] = self.base_url
                elif cfg["base_url"]:
                    kwargs["base_url"] = cfg["base_url"]
                if self.provider == "openrouter":
                    kwargs["default_headers"] = {
                        "HTTP-Referer": "https://github.com/Ari-Assistant",
                        "X-Title": "Ari Voice Assistant",
                    }
                client = openai_module.OpenAI(**kwargs)
                self._validate_openai_client(client, model)
            message = _("✓ {model} 연결 성공").format(model=model) if self.custom else f"✓ {model} 연결 성공"
            self.done.emit(True, message)
        except Exception as e:
            if self.custom:
                self.done.emit(False, _("연결에 실패했습니다. URL, 모델, API 키를 확인해 주세요."))
                return
            if self.provider == "ollama":
                self.done.emit(False, "✗ Ollama 서버에 연결할 수 없어요. Ollama 실행 여부를 확인하세요.")
                return
            msg = str(e)
            status_code = getattr(e, "status_code", None)
            if status_code == 404 or "404" in msg:
                label = cfg.get("label", self.provider)
                self.done.emit(
                    False,
                    f"✗ 모델 '{model}'을(를) {label}에서 찾을 수 없습니다. 모델명을 확인해 주세요.",
                )
                return
            if status_code == 401 or "401" in msg or "Unauthorized" in msg:
                self.done.emit(False, "✗ API Key가 유효하지 않습니다. 키를 확인해 주세요.")
                return
            for marker in ("Error code:", "status code", "error_code"):
                if marker in msg:
                    msg = msg.split("\n")[0]
                    break
            self.done.emit(False, f"✗ {msg[:100]}")


# ── LLM 설정 페이지 ────────────────────────────────────────────────────────────

class _LLMSettingsPage(QWidget):
    """LLM 제공자 설정 탭 위젯."""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = dict(settings)
        normalize_custom_provider_settings(self._settings)
        self._custom_providers = get_custom_providers(self._settings)
        self._original_custom_provider_ids = set(self._custom_providers)
        self._llm_key_inputs: dict[str, QLineEdit] = {}
        self._llm_model_inputs: dict[str, QLineEdit] = {}
        self._validate_labels: dict[str, QLabel] = {}
        self._validator_threads: dict[str, _ValidatorThread] = {}
        self._retired_validator_threads: set[_ValidatorThread] = set()
        self._validation_generation: dict[str, int] = {}
        self._role_provider_combos: dict[str, QComboBox] = {}
        self._provider_setting_widgets: dict[str, QWidget] = {}
        self._provider_title_labels: dict[str, QLabel] = {}
        self._custom_list_widgets: list[QWidget] = []
        self._init_ui()

    def _provider_options(self):
        return _llm_providers() + [
            (provider.get("label", provider_id), provider_id, custom_api_key_name(provider_id), _("선택 사항"))
            for provider_id, provider in self._custom_providers.items()
        ]

    def _provider_config(self, provider: str) -> dict:
        if provider in self._custom_providers:
            return self._custom_providers[provider]
        from agent.llm_provider import _PROVIDER_CONFIG
        return _PROVIDER_CONFIG.get(provider, {})

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
        for label, data, _key, _ph in self._provider_options():
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

        custom_group = QGroupBox(_("사용자 지정 OpenAI 호환 제공자"))
        custom_vbox = QVBoxLayout(custom_group)
        custom_vbox.addWidget(create_muted_label(
            _("OpenAI 호환 서버의 이름과 기본 URL을 등록합니다. API 키와 기본 모델은 아래에서 설정합니다.")
        ))
        self._custom_provider_list_layout = QVBoxLayout()
        custom_vbox.addLayout(self._custom_provider_list_layout)
        add_custom_btn = QPushButton(_("제공자 추가"))
        add_custom_btn.setStyleSheet(secondary_btn_style())
        add_custom_btn.clicked.connect(self._add_custom_provider)
        custom_vbox.addWidget(add_custom_btn)
        self._refresh_custom_provider_list()
        vbox.addWidget(custom_group)

        # 제공자별 API Key 그룹
        api_group = QGroupBox(_("제공자별 API Key"))
        # 사용자 지정 제공자를 추가·삭제할 때 이 목록에 행을 넣고 뺀다.
        self._api_vbox = api_vbox = QVBoxLayout(api_group)
        api_vbox.addWidget(create_muted_label(
            _("사용할 제공자의 API Key와 모델명을 입력한 뒤 [검증]으로 연결을 확인하세요.")
        ))
        for label, data, key, placeholder in self._provider_options():
            self._add_provider_settings_row(api_vbox, label, data, key, placeholder)

        vbox.addWidget(api_group)
        vbox.addStretch()

        scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._on_llm_changed()

    def _add_provider_settings_row(self, layout, label: str, provider: str, key: str, placeholder: str):
        row = QWidget()
        row_vbox = QVBoxLayout(row)
        row_vbox.setContentsMargins(0, 8, 0, 4)
        title = QLabel(label)
        title.setTextFormat(Qt.TextFormat.PlainText)
        row_vbox.addWidget(title)

        key_row = QHBoxLayout()
        key_input = QLineEdit(self._settings.get(key, "") if key else "")
        key_input.setPlaceholderText(placeholder)
        key_input.setEchoMode(QLineEdit.EchoMode.Password)
        key_row.addWidget(key_input)
        validate_btn = QPushButton(_("검증"))
        validate_btn.setFixedWidth(54)
        validate_btn.setStyleSheet(secondary_btn_style())
        key_row.addWidget(validate_btn)
        row_vbox.addLayout(key_row)

        model_row = QHBoxLayout()
        config = self._provider_config(provider)
        if provider in self._custom_providers:
            prefilled_model = config.get("default_model", "")
        else:
            prefilled_model = self._get_model_for_provider(provider)
        model_input = QLineEdit(prefilled_model)
        model_input.setPlaceholderText(_("모델명 (기본: {model})").format(model=config.get("default_model", "")))
        model_row.addWidget(model_input)
        status = QLabel("")
        status.setWordWrap(True)
        status.setFixedWidth(220)
        model_row.addWidget(status)
        row_vbox.addLayout(model_row)
        layout.addWidget(row)

        self._provider_setting_widgets[provider] = row
        self._provider_title_labels[provider] = title
        self._llm_key_inputs[provider] = key_input
        self._llm_model_inputs[provider] = model_input
        self._validate_labels[provider] = status
        validate_btn.clicked.connect(lambda checked=False, p=provider: self._run_validation(p))

    def _refresh_custom_provider_list(self):
        for widget in self._custom_list_widgets:
            self._custom_provider_list_layout.removeWidget(widget)
            widget.deleteLater()
        self._custom_list_widgets.clear()
        for provider_id, provider in self._custom_providers.items():
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            label = QLabel(provider.get("label", provider_id))
            label.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(label, 1)
            edit_btn = QPushButton(_("수정"))
            edit_btn.setStyleSheet(secondary_btn_style())
            edit_btn.clicked.connect(lambda checked=False, p=provider_id: self._edit_custom_provider(p))
            layout.addWidget(edit_btn)
            delete_btn = QPushButton(_("삭제"))
            delete_btn.setStyleSheet(secondary_btn_style())
            delete_btn.clicked.connect(lambda checked=False, p=provider_id: self._confirm_delete_custom_provider(p))
            layout.addWidget(delete_btn)
            self._custom_provider_list_layout.addWidget(row)
            self._custom_list_widgets.append(row)

    def _add_custom_provider(self):
        dialog = _CustomProviderDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        provider_id = f"custom_{uuid.uuid4().hex}"
        self._custom_providers[provider_id] = {**dialog.get_values(), "default_model": ""}
        self._add_provider_settings_row(
            self._api_vbox,
            self._custom_providers[provider_id]["label"],
            provider_id,
            custom_api_key_name(provider_id),
            _("API 키 (선택 사항)"),
        )
        self._refresh_custom_provider_list()
        self._refresh_provider_combos()

    def _edit_custom_provider(self, provider_id: str):
        provider = self._custom_providers.get(provider_id)
        if provider is None:
            return
        dialog = _CustomProviderDialog(provider, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._invalidate_validation(provider_id)
        provider.update(dialog.get_values())
        title = self._provider_title_labels.get(provider_id)
        if title:
            title.setText(provider["label"])
        self._refresh_custom_provider_list()
        self._refresh_provider_combos()

    def _confirm_delete_custom_provider(self, provider_id: str):
        provider = self._custom_providers.get(provider_id)
        if provider is None:
            return
        if QMessageBox.question(
            self,
            _("제공자 삭제"),
            _("'{name}' 제공자를 삭제할까요?").format(name=provider.get("label", provider_id)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            self._remove_custom_provider(provider_id)

    def _remove_custom_provider(self, provider_id: str):
        if provider_id not in self._custom_providers:
            return
        self._invalidate_validation(provider_id)
        self._custom_providers.pop(provider_id)
        widget = self._provider_setting_widgets.pop(provider_id, None)
        if widget:
            self._api_vbox.removeWidget(widget)
            widget.deleteLater()
        self._provider_title_labels.pop(provider_id, None)
        self._llm_key_inputs.pop(provider_id, None)
        self._llm_model_inputs.pop(provider_id, None)
        self._validate_labels.pop(provider_id, None)

        if self.llm_provider_combo.currentData() == provider_id:
            self.llm_model_input.clear()
        for combo_key, combo in self._role_provider_combos.items():
            if combo.currentData() == provider_id:
                combo.setCurrentIndex(combo.findData(""))
                if combo_key == "llm_planner_provider":
                    self.llm_planner_model_input.clear()
                else:
                    self.llm_execution_model_input.clear()
        self._refresh_custom_provider_list()
        self._refresh_provider_combos()

    def _refresh_provider_combos(self):
        main_provider = self.llm_provider_combo.currentData()
        role_providers = {key: combo.currentData() for key, combo in self._role_provider_combos.items()}
        combos = [(self.llm_provider_combo, main_provider, "groq")]
        combos.extend(
            (combo, role_providers[key], "")
            for key, combo in self._role_provider_combos.items()
        )
        options = self._provider_options()
        for combo, selected, fallback in combos:
            is_role = combo is not self.llm_provider_combo
            combo.blockSignals(True)
            combo.clear()
            if is_role:
                combo.addItem(_("(기본 제공자와 동일)"), "")
            for label, provider_id, _key, _placeholder in options:
                combo.addItem(label, provider_id)
            values = {combo.itemData(i) for i in range(combo.count())}
            self._set_combo(combo, selected if selected in values else fallback)
            combo.blockSignals(False)
        self._on_llm_changed()

    # ── 유틸리티 ──────────────────────────────────────────────────────────────

    def _make_role_provider_combo(self, current_value: str) -> QComboBox:
        combo = QComboBox()
        combo.addItem(_("(기본 제공자와 동일)"), "")
        for label, data, _key, _ph in self._provider_options():
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
        custom = provider in self._custom_providers
        if provider != "ollama" and not custom and not api_key:
            lbl.setText(_("⚠ API Key를 입력하세요."))
            lbl.setStyleSheet("color: #e67e22;")
            return
        if provider == "ollama":
            api_key = "ollama"

        model = self._llm_model_inputs[provider].text().strip()
        if not model:
            if custom:
                lbl.setText(_("기본 모델을 입력하세요."))
                lbl.setStyleSheet("color: #e67e22;")
                return
            model = self._provider_config(provider).get("default_model", "")
            lbl.setText(_("검증 중... (기본 모델: {model})").format(model=model))
        else:
            lbl.setText(_("검증 중..."))
        lbl.setStyleSheet("color: #888;")

        generation = self._validation_generation.get(provider, 0) + 1
        self._validation_generation[provider] = generation
        old = self._validator_threads.get(provider)
        if old and old.isRunning():
            self._retired_validator_threads.add(old)
        elif old:
            self._validator_threads.pop(provider, None)

        config = self._provider_config(provider)
        thread = _ValidatorThread(
            provider,
            api_key,
            model,
            base_url=config.get("base_url", "") if custom else "",
            custom=custom,
        )
        thread.done.connect(
            lambda ok, msg, p=provider, g=generation: self._on_validation_done(p, ok, msg, g)
        )
        thread.finished.connect(lambda p=provider, t=thread: self._validator_finished(p, t))
        thread.finished.connect(lambda t=thread: _live_validator_threads.discard(t))
        _live_validator_threads.add(thread)
        self._validator_threads[provider] = thread
        thread.start()

    def _invalidate_validation(self, provider: str):
        self._validation_generation[provider] = self._validation_generation.get(provider, 0) + 1
        thread = self._validator_threads.pop(provider, None)
        if thread and thread.isRunning():
            self._retired_validator_threads.add(thread)

    def _validator_finished(self, provider: str, thread: _ValidatorThread):
        if self._validator_threads.get(provider) is thread:
            self._validator_threads.pop(provider, None)
        self._retired_validator_threads.discard(thread)

    def _on_validation_done(self, provider: str, success: bool, message: str, generation: int | None = None):
        if generation is not None and self._validation_generation.get(provider) != generation:
            return
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
        for _label, data, settings_key, _ph in _llm_providers():
            inp = self._llm_key_inputs.get(data)
            if inp and settings_key:
                llm_keys[settings_key] = inp.text().strip()

        custom_providers = {}
        for provider_id, provider in self._custom_providers.items():
            model_input = self._llm_model_inputs.get(provider_id)
            custom_providers[provider_id] = {
                "label": provider.get("label", provider_id),
                "base_url": provider.get("base_url", ""),
                "default_model": model_input.text().strip() if model_input else provider.get("default_model", ""),
            }
        for provider_id in self._original_custom_provider_ids | set(self._custom_providers):
            key = custom_api_key_name(provider_id)
            key_input = self._llm_key_inputs.get(provider_id)
            llm_keys[key] = key_input.text().strip() if key_input else ""

        return {
            "llm_provider": self.llm_provider_combo.currentData(),
            "llm_model": self.llm_model_input.text().strip(),
            "llm_router_enabled": self.llm_router_checkbox.isChecked(),
            "llm_planner_provider": self._role_provider_combos["llm_planner_provider"].currentData(),
            "llm_planner_model": self.llm_planner_model_input.text().strip(),
            "llm_execution_provider": self._role_provider_combos["llm_execution_provider"].currentData(),
            "llm_execution_model": self.llm_execution_model_input.text().strip(),
            "ollama_base_url": self.ollama_url_input.text().strip() or "http://localhost:11434/v1",
            "custom_llm_providers": custom_providers,
            **llm_keys,
        }

    def cleanup_threads(self):
        """다이얼로그 닫힐 때 실행 중인 검증 스레드 정리."""
        threads = set(self._validator_threads.values()) | self._retired_validator_threads
        for provider in self._validation_generation:
            self._validation_generation[provider] += 1
        for thread in threads:
            if thread.isRunning():
                thread.quit()
                thread.wait(12000)
            if not thread.isRunning():
                _live_validator_threads.discard(thread)

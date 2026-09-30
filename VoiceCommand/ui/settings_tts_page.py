"""
TTS 설정 페이지 위젯
"""
import logging
import os
import threading
from types import SimpleNamespace

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QTextEdit, QPushButton, QComboBox, QGroupBox,
    QScrollArea, QProgressDialog, QMessageBox, QFileDialog, QCheckBox,
)
from PySide6.QtCore import QObject, Qt, Signal, Slot

from i18n.translator import _
from ui.theme import SCROLLBAR_STYLE, secondary_btn_style
from ui.common import create_muted_label
from ui.local_installers import (
    CosyVoiceInstallerThread,
    LocalInstallSection,
    OllamaInstallDialog,
    OllamaInstallerThread,
)
from ui.tts_diagnostics import TTSDiagnosticPanel


class _TTSActionRelay(QObject):
    """작업 스레드 결과를 GUI 스레드로 넘긴다. 설정 창보다 오래 살아야 해서 모듈에 하나만 둔다."""

    completed = Signal(object, object, str)


_ACTION_RELAY: _TTSActionRelay | None = None


def _action_relay() -> _TTSActionRelay:
    global _ACTION_RELAY
    if _ACTION_RELAY is None:
        _ACTION_RELAY = _TTSActionRelay()
    return _ACTION_RELAY


# ── TTS 엔진 정의 ──────────────────────────────────────────────────────────────

def _tts_modes():
    return [
        (_("Fish Audio (API)"),    "fish"),
        (_("로컬 (CosyVoice3)"),   "local"),
        (_("OpenAI 호환 TTS"), "openai_compat_tts"),
        (_("OpenAI TTS"),          "openai_tts"),
        (_("ElevenLabs"),          "elevenlabs"),
        (_("Edge TTS (무료)"),     "edge"),
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
        self._tts_action_job: SimpleNamespace | None = None
        # GUI 스레드에서 릴레이를 만들고 연결해 결과가 항상 GUI 스레드에서 처리되게 한다.
        _action_relay().completed.connect(self._finish_elevenlabs_action)
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
        self._ollama_executable_path = str(self._settings.get("ollama_executable_path", "") or "")
        self.local_install_section = LocalInstallSection(
            self, cosyvoice_dir_provider=lambda: self.cosyvoice_dir_input.text()
        )
        self.local_install_section.ollama_install_requested.connect(self._open_ollama_installer)
        self.local_install_section.cosyvoice_install_requested.connect(self._install_cosyvoice)
        self.local_install_section.ollama_locate_requested.connect(self._locate_ollama)
        self.local_install_section.detection_finished.connect(self._on_local_install_detected)
        vbox.addWidget(self.local_install_section)

        # TTS 설정 그룹
        tts_group = QGroupBox(_("음성 합성 (TTS) 설정"))
        tts_vbox = QVBoxLayout(tts_group)

        tts_vbox.addWidget(QLabel(_("TTS 엔진 선택:")))
        self.tts_mode_combo = QComboBox()
        for label, data in _tts_modes():
            self.tts_mode_combo.addItem(label, data)
        self._set_combo(self.tts_mode_combo, self._settings.get("tts_mode", "fish"))
        self.tts_mode_combo.currentIndexChanged.connect(self._on_tts_changed)
        tts_vbox.addWidget(self.tts_mode_combo)

        self.tts_diagnostic_panel = TTSDiagnosticPanel(self._tts_diagnostic_values, self)
        tts_vbox.addWidget(self.tts_diagnostic_panel)
        self.tts_emotion_checkbox = QCheckBox(_("TTS 감정 조절"))
        self.tts_emotion_checkbox.setChecked(
            bool(self._settings.get("tts_emotion_enabled", True))
        )
        tts_vbox.addWidget(self.tts_emotion_checkbox)

        general_grp = QGroupBox(_("공통 TTS 설정"))
        general_layout = QVBoxLayout(general_grp)
        general_layout.addWidget(QLabel(_("재생 볼륨 배율 (0.0 ~ 2.0, 1.0 = 원본):")))
        self.tts_volume_input = QLineEdit(str(self._settings.get("tts_volume", 1.0)))
        general_layout.addWidget(self.tts_volume_input)
        tts_vbox.addWidget(general_grp)

        self._voice_cloning_group = QGroupBox(_("보이스 클로닝"))
        cloning_layout = QVBoxLayout(self._voice_cloning_group)
        cloning_layout.addWidget(QLabel(_("참조 WAV 파일 (비워두면 기본 reference.wav 사용):")))
        reference_row = QHBoxLayout()
        self.tts_reference_wav_input = QLineEdit(
            self._settings.get("tts_reference_wav", "")
        )
        reference_row.addWidget(self.tts_reference_wav_input)
        reference_button = QPushButton(_("찾아보기"))
        reference_button.clicked.connect(self._browse_reference_wav)
        reference_row.addWidget(reference_button)
        cloning_layout.addLayout(reference_row)
        cloning_layout.addWidget(QLabel(_("참조 WAV 대본:")))
        self.cosyvoice_ref_text = QTextEdit()
        self.cosyvoice_ref_text.setPlainText(
            self._settings.get("cosyvoice_reference_text", "")
        )
        self.cosyvoice_ref_text.setMaximumHeight(60)
        cloning_layout.addWidget(self.cosyvoice_ref_text)
        tts_vbox.addWidget(self._voice_cloning_group)

        # Fish Audio 설정
        fish_grp = QGroupBox(_("Fish Audio 설정"))
        fl = QVBoxLayout(fish_grp)
        fl.addWidget(QLabel(_("API Key:")))
        self.fish_key_input = QLineEdit(self._settings.get("fish_api_key", ""))
        self.fish_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        fl.addWidget(self.fish_key_input)
        fl.addWidget(QLabel(_("Reference ID:")))
        self.fish_ref_input = QLineEdit(self._settings.get("fish_reference_id", ""))
        fl.addWidget(self.fish_ref_input)
        fl.addWidget(QLabel(_("모델:")))
        self.fish_model_combo = QComboBox()
        self.fish_model_combo.setEditable(True)
        for m in ["s2.1-pro-free", "s1", "speech-1.6", "speech-1.5"]:
            self.fish_model_combo.addItem(m, m)
        self._set_combo(self.fish_model_combo,
                        self._settings.get("fish_model", "s2.1-pro-free"))
        fl.addWidget(self.fish_model_combo)
        tts_vbox.addWidget(fish_grp)
        self._tts_groups["fish"] = fish_grp

        # CosyVoice3 설정
        cv_grp = QGroupBox(_("CosyVoice3 설정 (로컬 GPU)"))
        cvl = QVBoxLayout(cv_grp)
        cvl.addWidget(QLabel(_("CosyVoice 설치 경로 (비워두면 자동 감지):")))
        dir_row = QHBoxLayout()
        self.cosyvoice_dir_input = QLineEdit(self._settings.get("cosyvoice_dir", ""))
        self.cosyvoice_dir_input.setPlaceholderText(_("예: C:/CosyVoice"))
        dir_row.addWidget(self.cosyvoice_dir_input)
        browse_btn = QPushButton(_("찾아보기"))
        browse_btn.setFixedWidth(72)
        browse_btn.setStyleSheet(secondary_btn_style())
        browse_btn.clicked.connect(self._browse_cosyvoice_dir)
        dir_row.addWidget(browse_btn)
        detect_btn = QPushButton(_("자동 감지"))
        detect_btn.setFixedWidth(72)
        detect_btn.setStyleSheet(secondary_btn_style())
        detect_btn.clicked.connect(self._detect_cosyvoice_dir)
        dir_row.addWidget(detect_btn)
        cvl.addLayout(dir_row)
        self.cosyvoice_dir_status = create_muted_label("")
        cvl.addWidget(self.cosyvoice_dir_status)
        cvl.addWidget(QLabel(_("말하기 속도 (0.7 ~ 1.2):")))
        self.cosyvoice_speed_input = QLineEdit(str(self._settings.get("cosyvoice_speed", 0.9)))
        cvl.addWidget(self.cosyvoice_speed_input)
        tts_vbox.addWidget(cv_grp)
        self._tts_groups["local"] = cv_grp

        compat_grp = QGroupBox(_("OpenAI 호환 TTS 설정"))
        compat_layout = QVBoxLayout(compat_grp)
        compat_layout.addWidget(QLabel(_("서버 URL (예: http://127.0.0.1:8880/v1):")))
        self.openai_compat_base_url_input = QLineEdit(
            self._settings.get("openai_compat_tts_base_url", "")
        )
        compat_layout.addWidget(self.openai_compat_base_url_input)
        compat_layout.addWidget(QLabel(_("API Key (선택):")))
        self.openai_compat_api_key_input = QLineEdit(
            self._settings.get("openai_compat_tts_api_key", "")
        )
        self.openai_compat_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_compat_api_key_input.setPlaceholderText(_("비워두면 not-needed를 보냅니다."))
        compat_layout.addWidget(self.openai_compat_api_key_input)
        compat_layout.addWidget(QLabel(_("모델:")))
        self.openai_compat_model_input = QLineEdit(
            self._settings.get("openai_compat_tts_model", "")
        )
        compat_layout.addWidget(self.openai_compat_model_input)
        compat_layout.addWidget(QLabel(_("목소리:")))
        self.openai_compat_voice_input = QLineEdit(
            self._settings.get("openai_compat_tts_voice", "")
        )
        compat_layout.addWidget(self.openai_compat_voice_input)
        compat_options = QHBoxLayout()
        self.openai_compat_clone_combo = QComboBox()
        self.openai_compat_clone_combo.addItem(_("기본 음성"), "none")
        self.openai_compat_clone_combo.addItem(_("참조 음성 복제"), "ref_audio")
        self._set_combo(
            self.openai_compat_clone_combo,
            self._settings.get("openai_compat_tts_clone_mode", "none"),
        )
        compat_options.addWidget(QLabel(_("클로닝:")))
        compat_options.addWidget(self.openai_compat_clone_combo)
        self.openai_compat_emotion_combo = QComboBox()
        self.openai_compat_emotion_combo.addItem(_("감정 지시문 사용"), "instructions")
        self.openai_compat_emotion_combo.addItem(_("사용 안 함"), "none")
        self._set_combo(
            self.openai_compat_emotion_combo,
            self._settings.get("openai_compat_tts_emotion_mode", "instructions"),
        )
        compat_options.addWidget(QLabel(_("감정:")))
        compat_options.addWidget(self.openai_compat_emotion_combo)
        compat_layout.addLayout(compat_options)
        tts_vbox.addWidget(compat_grp)
        self._tts_groups["openai_compat_tts"] = compat_grp

        # OpenAI TTS 설정
        oai_grp = QGroupBox(_("OpenAI TTS 설정"))
        oail = QVBoxLayout(oai_grp)
        oail.addWidget(QLabel(_("API Key (선택):")))
        self.openai_tts_key_input = QLineEdit(self._settings.get("openai_tts_api_key", ""))
        self.openai_tts_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_tts_key_input.setPlaceholderText(_("비워두면 AI 설정을 따릅니다."))
        oail.addWidget(self.openai_tts_key_input)
        row = QHBoxLayout()
        row.addWidget(QLabel(_("목소리:")))
        self.openai_tts_voice_combo = QComboBox()
        for v in ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]:
            self.openai_tts_voice_combo.addItem(v, v)
        self._set_combo(self.openai_tts_voice_combo, self._settings.get("openai_tts_voice", "nova"))
        row.addWidget(self.openai_tts_voice_combo)
        row.addWidget(QLabel(_("모델:")))
        self.openai_tts_model_combo = QComboBox()
        for m in ["tts-1", "tts-1-hd", "gpt-4o-mini-tts"]:
            self.openai_tts_model_combo.addItem(m, m)
        self._set_combo(self.openai_tts_model_combo, self._settings.get("openai_tts_model", "tts-1"))
        row.addWidget(self.openai_tts_model_combo)
        oail.addLayout(row)
        oail.addWidget(QLabel(_("승인된 조직만 사용 가능: 커스텀 보이스 ID (voice_...):")))
        self.openai_tts_custom_voice_input = QLineEdit(
            self._settings.get("openai_tts_custom_voice_id", "")
        )
        oail.addWidget(self.openai_tts_custom_voice_input)
        tts_vbox.addWidget(oai_grp)
        self._tts_groups["openai_tts"] = oai_grp

        # ElevenLabs 설정
        el_grp = QGroupBox(_("ElevenLabs 설정"))
        ell = QVBoxLayout(el_grp)
        ell.addWidget(QLabel(_("API Key:")))
        self.elevenlabs_key_input = QLineEdit(self._settings.get("elevenlabs_api_key", ""))
        self.elevenlabs_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        ell.addWidget(self.elevenlabs_key_input)
        ell.addWidget(QLabel(_("모델:")))
        self.elevenlabs_model_combo = QComboBox()
        self.elevenlabs_model_combo.setEditable(True)
        for model_id in ("eleven_multilingual_v2", "eleven_flash_v2_5", "eleven_v3"):
            self.elevenlabs_model_combo.addItem(model_id, model_id)
        self._select_or_add(
            self.elevenlabs_model_combo,
            self._settings.get("elevenlabs_model_id", "eleven_multilingual_v2"),
        )
        ell.addWidget(self.elevenlabs_model_combo)
        eleven_button_row = QHBoxLayout()
        self.elevenlabs_models_button = QPushButton(_("모델 불러오기"))
        self.elevenlabs_models_button.clicked.connect(self._load_elevenlabs_models)
        eleven_button_row.addWidget(self.elevenlabs_models_button)
        self.elevenlabs_voices_button = QPushButton(_("음성 불러오기"))
        self.elevenlabs_voices_button.clicked.connect(self._load_elevenlabs_voices)
        eleven_button_row.addWidget(self.elevenlabs_voices_button)
        ell.addLayout(eleven_button_row)
        ell.addWidget(QLabel(_("음성:")))
        self.elevenlabs_voice_combo = QComboBox()
        self.elevenlabs_voice_combo.setEditable(True)
        self._select_or_add(self.elevenlabs_voice_combo, self._settings.get("elevenlabs_voice_id", ""))
        ell.addWidget(self.elevenlabs_voice_combo)
        self.elevenlabs_clone_button = QPushButton(_("참조 음성으로 내 음성 만들기"))
        self.elevenlabs_clone_button.clicked.connect(self._create_elevenlabs_clone)
        ell.addWidget(self.elevenlabs_clone_button)
        tts_vbox.addWidget(el_grp)
        self._tts_groups["elevenlabs"] = el_grp

        # Edge TTS 설정
        edge_grp = QGroupBox(_("Edge TTS 설정 (무료)"))
        edgel = QVBoxLayout(edge_grp)
        edgel.addWidget(QLabel(_("목소리 선택:")))
        self.edge_voice_combo = QComboBox()
        for vid, vlbl in [
            ("ko-KR-SunHiNeural", _("SunHi (여성)")),
            ("ko-KR-InJoonNeural", _("InJoon (남성)")),
            ("ko-KR-HyunsuNeural", _("Hyunsu (남성)")),
        ]:
            self.edge_voice_combo.addItem(vlbl, vid)
        self._set_combo(self.edge_voice_combo, self._settings.get("edge_tts_voice", "ko-KR-SunHiNeural"))
        edgel.addWidget(self.edge_voice_combo)
        edgel.addWidget(QLabel(_("속도 (예: +0%, -10%):")))
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

    def _browse_reference_wav(self):
        selection = QFileDialog.getOpenFileName(
            self,
            _("참조 WAV 선택"),
            self.tts_reference_wav_input.text() or "",
            _("WAV 파일 (*.wav)"),
        )
        if selection[0]:
            self.tts_reference_wav_input.setText(selection[0])

    def _start_elevenlabs_action(self, button: QPushButton, action, callback):
        if self._tts_action_job is not None:
            return
        button.setEnabled(False)
        job = SimpleNamespace(button=button, callback=callback)
        self._tts_action_job = job
        relay = _action_relay()

        def run():
            try:
                result, error = action(), ""
            except Exception as exc:
                result, error = None, str(exc)
            try:
                relay.completed.emit(job, result, error)
            except RuntimeError:
                pass  # 앱 종료 중이면 결과를 버린다.

        # 데몬 스레드라 요청 중에 앱을 끝내도 종료를 막거나 Qt 스레드 파괴로 죽지 않는다.
        threading.Thread(target=run, name="ElevenLabsAction", daemon=True).start()

    @Slot(object, object, str)
    def _finish_elevenlabs_action(self, job, result, error: str):
        # 다른 설정 창의 작업이거나 창이 닫혀 정리된 작업이면 무시한다.
        if job is not self._tts_action_job:
            return
        self._tts_action_job = None
        job.button.setEnabled(True)
        job.callback(result, error)

    def _load_elevenlabs_models(self):
        api_key = self.elevenlabs_key_input.text().strip()
        if not api_key:
            QMessageBox.warning(self, _("ElevenLabs"), _("API Key를 입력하세요."))
            return

        def finish(models, error):
            if error:
                QMessageBox.warning(self, _("모델 불러오기 실패"), error)
                return
            selected = self._combo_id(self.elevenlabs_model_combo)
            self.elevenlabs_model_combo.clear()
            for model in models:
                self.elevenlabs_model_combo.addItem(model["name"], model["model_id"])
            self._select_or_add(self.elevenlabs_model_combo, selected)

        def fetch():
            from tts.tts_elevenlabs import fetch_models

            return fetch_models(api_key)

        self._start_elevenlabs_action(self.elevenlabs_models_button, fetch, finish)

    def _load_elevenlabs_voices(self):
        api_key = self.elevenlabs_key_input.text().strip()
        if not api_key:
            QMessageBox.warning(self, _("ElevenLabs"), _("API Key를 입력하세요."))
            return

        def finish(voices, error):
            if error:
                QMessageBox.warning(self, _("음성 불러오기 실패"), error)
                return
            selected = self._combo_id(self.elevenlabs_voice_combo)
            self.elevenlabs_voice_combo.clear()
            for voice in voices:
                self.elevenlabs_voice_combo.addItem(voice["name"], voice["voice_id"])
            self._select_or_add(self.elevenlabs_voice_combo, selected)

        def fetch():
            from tts.tts_elevenlabs import fetch_voices

            return fetch_voices(api_key)

        self._start_elevenlabs_action(self.elevenlabs_voices_button, fetch, finish)

    def _create_elevenlabs_clone(self):
        api_key = self.elevenlabs_key_input.text().strip()
        if not api_key:
            QMessageBox.warning(self, _("ElevenLabs"), _("API Key를 입력하세요."))
            return
        from tts.voice_reference import get_reference_wav

        reference_wav = get_reference_wav(self.get_values())
        if not os.path.isfile(reference_wav):
            QMessageBox.warning(self, _("음성 복제"), _("참조 WAV 파일을 찾을 수 없습니다."))
            return
        voice_name = os.path.splitext(os.path.basename(reference_wav))[0] or "Ari Voice"

        def finish(voice_id, error):
            if error:
                QMessageBox.warning(self, _("음성 복제 실패"), error)
                return
            self.elevenlabs_voice_combo.addItem(voice_name, voice_id)
            self.elevenlabs_voice_combo.setCurrentIndex(self.elevenlabs_voice_combo.count() - 1)

        def clone():
            from tts.tts_elevenlabs import create_voice_clone

            return create_voice_clone(api_key, reference_wav, voice_name)

        self._start_elevenlabs_action(self.elevenlabs_clone_button, clone, finish)

    # ── 이벤트 핸들러 ─────────────────────────────────────────────────────────

    def _on_tts_changed(self):
        selected = self.tts_mode_combo.currentData()
        for key in [data for _label, data in _tts_modes()]:
            grp = self._tts_groups.get(key)
            if grp:
                grp.setVisible(key == selected)
        self._voice_cloning_group.setVisible(
            selected in {"local", "openai_compat_tts", "elevenlabs"}
        )

    def _tts_diagnostic_values(self):
        selected_mode = self.tts_mode_combo.currentData()
        settings = dict(self._settings)
        dialog = self.window()
        llm_page = getattr(dialog, "_llm_page", None)
        if llm_page is not None:
            settings.update(llm_page.get_values())
        settings.update(self.get_values())
        speaker_combo = getattr(dialog, "speaker_combo", None)
        output_device_name = speaker_combo.currentData() if speaker_combo is not None else ""
        return settings, selected_mode, str(output_device_name or "")

    def _open_ollama_installer(self):
        from PySide6.QtWidgets import QDialog
        installed = bool(self.local_install_section.ollama_path)
        dialog = OllamaInstallDialog(self, installed=installed)
        if dialog.exec() != QDialog.Accepted:
            return

        selected_models = dialog.selected_models()
        if not selected_models and installed:
            QMessageBox.information(self, _("Ollama 모델 받기"), _("선택한 모델이 없습니다."))
            return
        if not selected_models:
            confirm = QMessageBox.question(
                self,
                _("모델 없이 설치"),
                _("선택한 모델이 없습니다. Ollama 프로그램만 설치할까요?"),
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
            _("Ollama 모델을 받는 중입니다.\n모델 다운로드는 콘솔 없이 백그라운드로 계속됩니다.") if installed else
            _("Ollama 설치를 준비 중입니다.\n설치 창이 뜨면 진행하고, 모델 다운로드는 콘솔 없이 백그라운드로 계속됩니다."),
            None, 0, 0, self,
        )
        self._ollama_progress_dialog.setWindowTitle(_("Ollama 모델 받기") if installed else _("Ollama 설치"))
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
            QMessageBox.information(self, _("Ollama 설치"), message)
        else:
            QMessageBox.warning(self, _("Ollama 설치"), message)

        self._ollama_install_thread = None
        self.local_install_section.start_detection()

    def _locate_ollama(self):
        """사용자가 ollama.exe를 직접 고르면 설정에 저장하고 상태를 다시 확인한다."""
        path, _filter = QFileDialog.getOpenFileName(
            self, _("ollama.exe 위치 선택"),
            os.path.dirname(self._ollama_executable_path) or "C:/",
            "ollama.exe (ollama.exe)",
        )
        if not path:
            return
        if os.path.basename(path).lower() not in {"ollama.exe", "ollama"}:
            QMessageBox.warning(self, _("위치 지정"), _("ollama.exe 파일을 선택하세요."))
            return
        self._ollama_executable_path = os.path.abspath(path)
        # 설치 작업이 저장 전에도 이 경로를 쓰도록 바로 기록한다. 설정창 저장 때도 get_values로 함께 저장된다.
        from core.config_manager import ConfigManager
        from core.ollama_installer import OLLAMA_EXECUTABLE_SETTING
        if not ConfigManager.set_value(OLLAMA_EXECUTABLE_SETTING, self._ollama_executable_path):
            logging.warning("ollama.exe 경로를 바로 저장하지 못했습니다. 설정창 저장 때 다시 저장합니다.")
        self.local_install_section.start_detection()

    def _on_local_install_detected(self, result: dict):
        path = result.get("cosyvoice_dir") or ""
        if path:
            self.cosyvoice_dir_input.setText(path)
            self._check_cosyvoice_dir(path)
        else:
            self.cosyvoice_dir_status.setText(
                _("CosyVoice 설치가 감지되지 않았습니다. 설치하거나 폴더를 지정해 주세요.")
            )
            self.cosyvoice_dir_status.setStyleSheet("color: #e67e22;")

    def _install_cosyvoice(self):
        target_dir = self.cosyvoice_dir_input.text().strip()
        if not target_dir:
            target_dir = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "CosyVoice")
            self.cosyvoice_dir_input.setText(target_dir)

        installed_dir = self.local_install_section.cosyvoice_dir
        if installed_dir:
            # 이미 설치돼 있으면 다시 설치할지 먼저 묻고, 기본 선택은 '아니요'로 둔다.
            confirm = QMessageBox.question(
                self,
                _("CosyVoice 설치"),
                _("CosyVoice3가 이미 설치되어 있습니다.\n\n{path}\n\n다시 설치할까요?", path=installed_dir),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
        else:
            confirm = QMessageBox.question(
                self,
                _("CosyVoice 설치"),
                _("아래 경로에 CosyVoice3를 설치할까요?\n\n{path}").format(path=target_dir),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
        if confirm != QMessageBox.Yes:
            return

        self._cosyvoice_install_thread = CosyVoiceInstallerThread(target_dir)
        self._cosyvoice_install_thread.done.connect(self._on_cosyvoice_install_done)
        self._cosyvoice_progress_dialog = QProgressDialog(
            _("CosyVoice3 설치를 진행 중입니다.\n의존성 및 모델 다운로드로 시간이 조금 걸릴 수 있습니다."),
            None, 0, 0, self,
        )
        self._cosyvoice_progress_dialog.setWindowTitle(_("CosyVoice3 설치"))
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
            QMessageBox.information(self, _("CosyVoice3 설치"), message)
        else:
            self.cosyvoice_dir_status.setText(message)
            self.cosyvoice_dir_status.setStyleSheet("color: #e74c3c;")
            QMessageBox.warning(self, _("CosyVoice3 설치"), message)

        self._cosyvoice_install_thread = None

    def _browse_cosyvoice_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, _("CosyVoice 설치 폴더 선택"),
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
            self.cosyvoice_dir_status.setText(_("✓ 감지됨: {path}").format(path=path))
            self.cosyvoice_dir_status.setStyleSheet("color: #27ae60;")
        else:
            self.cosyvoice_dir_status.setText(_("✗ 자동 감지 실패 — 경로를 직접 입력하세요."))
            self.cosyvoice_dir_status.setStyleSheet("color: #e74c3c;")

    def _check_cosyvoice_dir(self, path: str):
        from core.cosyvoice_installer import is_valid_cosyvoice_dir
        if is_valid_cosyvoice_dir(path):
            self.cosyvoice_dir_status.setText(_("✓ 유효한 CosyVoice 경로"))
            self.cosyvoice_dir_status.setStyleSheet("color: #27ae60;")
        else:
            self.cosyvoice_dir_status.setText(_("⚠ pretrained_models 폴더가 없습니다. 경로를 확인하세요."))
            self.cosyvoice_dir_status.setStyleSheet("color: #e67e22;")

    # ── 유틸리티 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _set_combo(combo: QComboBox, value: str):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    @staticmethod
    def _select_or_add(combo: QComboBox, value: str):
        """목록에 없는 저장 ID도 항목으로 추가해 선택을 유지한다."""
        if not value:
            return
        index = combo.findData(value)
        if index < 0:
            combo.addItem(value, value)
            index = combo.count() - 1
        combo.setCurrentIndex(index)

    @staticmethod
    def _combo_id(combo: QComboBox) -> str:
        """편집 가능 콤보에서 직접 입력한 ID를 선택 항목 데이터보다 우선한다."""
        text = combo.currentText().strip()
        data = combo.currentData()
        if data and text == combo.itemText(combo.currentIndex()):
            return data
        return text

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
            "tts_emotion_enabled": self.tts_emotion_checkbox.isChecked(),
            "fish_api_key": self.fish_key_input.text().strip(),
            "fish_reference_id": self.fish_ref_input.text().strip(),
            # 편집 가능 콤보라 사용자가 직접 입력한 모델명도 그대로 받는다.
            "fish_model": (self.fish_model_combo.currentText().strip()
                           or "s2.1-pro-free"),
            "cosyvoice_dir": self.cosyvoice_dir_input.text().strip(),
            "cosyvoice_reference_text": self.cosyvoice_ref_text.toPlainText().strip(),
            "tts_reference_wav": self.tts_reference_wav_input.text().strip(),
            "cosyvoice_speed": self._float(self.cosyvoice_speed_input.text(), 0.9),
            "tts_volume": self._float(self.tts_volume_input.text(), 1.0),
            "openai_compat_tts_base_url": self.openai_compat_base_url_input.text().strip(),
            "openai_compat_tts_api_key": self.openai_compat_api_key_input.text().strip(),
            "openai_compat_tts_model": self.openai_compat_model_input.text().strip(),
            "openai_compat_tts_voice": self.openai_compat_voice_input.text().strip(),
            "openai_compat_tts_clone_mode": self.openai_compat_clone_combo.currentData(),
            "openai_compat_tts_emotion_mode": self.openai_compat_emotion_combo.currentData(),
            "openai_tts_api_key": self.openai_tts_key_input.text().strip(),
            "openai_tts_voice": self.openai_tts_voice_combo.currentData(),
            "openai_tts_model": self.openai_tts_model_combo.currentData(),
            "openai_tts_custom_voice_id": self.openai_tts_custom_voice_input.text().strip(),
            "elevenlabs_api_key": self.elevenlabs_key_input.text().strip(),
            "elevenlabs_voice_id": self._combo_id(self.elevenlabs_voice_combo),
            "elevenlabs_model_id": (self._combo_id(self.elevenlabs_model_combo)
                                    or "eleven_multilingual_v2"),
            "edge_tts_voice": self.edge_voice_combo.currentData(),
            "edge_tts_rate": self.edge_rate_input.text().strip() or "+0%",
            "ollama_executable_path": self._ollama_executable_path,
        }

    def cleanup_threads(self):
        """다이얼로그 닫힐 때 실행 중인 스레드 정리."""
        self.local_install_section.stop_detection()
        self.tts_diagnostic_panel.cancel()
        # ElevenLabs 요청은 중간에 멈출 수 없으니 기다리지 않고 결과 처리만 끊는다.
        self._tts_action_job = None
        for thread in (self._ollama_install_thread, self._cosyvoice_install_thread):
            if thread and thread.isRunning():
                thread.quit()
                thread.wait(2000)

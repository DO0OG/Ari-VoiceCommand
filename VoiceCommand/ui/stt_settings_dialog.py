"""
음성 인식(STT) 설정 다이얼로그 — STT 엔진, Whisper 옵션, 마이크 감도, 웨이크워드
"""
import logging
import threading
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QGroupBox,
    QListWidget, QListWidgetItem, QCheckBox,
    QInputDialog, QSlider, QMessageBox, QDialogButtonBox, QKeySequenceEdit,
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QFont, QKeySequence
from core.config_manager import ConfigManager
from i18n.translator import _
from ui.theme import FONT_KO, FONT_SIZE_NORMAL, INPUT_STYLE
from ui.stt_diagnostics import STTSampleDiagnosticPanel
from ui.global_hotkey import parse_global_hotkey


class _DownloadSignals(QObject):
    finished = Signal(bool, str)  # (success, message)


class STTSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("음성 인식 설정"))
        self.setMinimumWidth(500)
        self.setFont(QFont(FONT_KO, FONT_SIZE_NORMAL))
        self.setStyleSheet(INPUT_STYLE)
        self.settings = ConfigManager.load_settings()
        parent_mic_combo = getattr(parent, "mic_combo", None)
        self.microphone_name = (
            str(parent_mic_combo.currentData() or "")
            if parent_mic_combo is not None
            else str(self.settings.get("microphone", "") or "")
        )
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # ── 음성 입력 ──────────────────────────────────────────────────────────
        input_group = QGroupBox(_("단축키·클릭으로 듣기"))
        ivbox = QVBoxLayout(input_group)
        ivbox.addWidget(QLabel(_("전역 단축키:")))
        self.voice_hotkey_edit = QKeySequenceEdit()
        self.voice_hotkey_edit.setKeySequence(QKeySequence(
            str(self.settings.get("voice_activation_hotkey", "Ctrl+Alt+Space"))
        ))
        ivbox.addWidget(self.voice_hotkey_edit)
        ivbox.addWidget(QLabel(_("듣기 방식:")))
        self.voice_activation_mode_combo = QComboBox()
        self.voice_activation_mode_combo.addItem(
            _("누르고 있는 동안 듣기 (push-to-talk)"), "push_to_talk"
        )
        self.voice_activation_mode_combo.addItem(
            _("한 번 눌러 시작 (toggle)"), "toggle"
        )
        self._set_combo(
            self.voice_activation_mode_combo,
            self.settings.get("voice_activation_mode", "push_to_talk"),
        )
        ivbox.addWidget(self.voice_activation_mode_combo)
        self.wake_word_enabled_checkbox = QCheckBox(_("웨이크워드 사용"))
        self.wake_word_enabled_checkbox.setChecked(
            bool(self.settings.get("wake_word_enabled", True))
        )
        ivbox.addWidget(self.wake_word_enabled_checkbox)
        input_hint = QLabel(
            _("캐릭터를 짧게 클릭하면 발화 끝을 감지하고, 길게 누르면 누르는 동안 듣습니다.")
        )
        input_hint.setWordWrap(True)
        ivbox.addWidget(input_hint)
        hotkey_hint = QLabel(
            _("단축키가 다른 앱에서 사용 중이면 등록되지 않습니다. 앱은 계속 실행됩니다.")
        )
        hotkey_hint.setWordWrap(True)
        ivbox.addWidget(hotkey_hint)
        layout.addWidget(input_group)

        # ── STT 엔진 ──────────────────────────────────────────────────────────
        engine_group = QGroupBox(_("STT 엔진"))
        eg_vbox = QVBoxLayout(engine_group)
        eg_vbox.addWidget(QLabel(_("음성 인식 엔진:")))
        self.stt_provider_combo = QComboBox()
        self.stt_provider_combo.addItem(_("Google STT (온라인)"), "google")
        self.stt_provider_combo.addItem(_("Whisper (오프라인)"), "whisper")
        self._set_combo(self.stt_provider_combo, self.settings.get("stt_provider", "google"))
        self.stt_provider_combo.currentIndexChanged.connect(self._on_stt_changed)
        eg_vbox.addWidget(self.stt_provider_combo)

        # ── Whisper 설정 ───────────────────────────────────────────────────────
        self.whisper_group = QGroupBox(_("Whisper 설정"))
        wg_vbox = QVBoxLayout(self.whisper_group)
        wg_vbox.addWidget(QLabel(_("모델 크기:")))
        self.whisper_model_combo = QComboBox()
        for model_name in ("tiny", "small", "medium"):
            self.whisper_model_combo.addItem(model_name, model_name)
        self._set_combo(self.whisper_model_combo, self.settings.get("whisper_model", "small"))
        wg_vbox.addWidget(self.whisper_model_combo)
        self.whisper_download_btn = QPushButton(_("모델 다운로드"))
        self.whisper_download_btn.clicked.connect(self._download_whisper_model)
        wg_vbox.addWidget(self.whisper_download_btn)
        eg_vbox.addWidget(self.whisper_group)

        layout.addWidget(engine_group)

        self.stt_diagnostic_panel = STTSampleDiagnosticPanel(
            self._stt_diagnostic_settings, self.microphone_name, self
        )
        layout.addWidget(self.stt_diagnostic_panel)

        # ── 마이크 감도 ────────────────────────────────────────────────────────
        mic_group = QGroupBox(_("마이크 감도"))
        mg_vbox = QVBoxLayout(mic_group)
        self.stt_energy_slider = QSlider(Qt.Horizontal)
        self.stt_energy_slider.setRange(100, 4000)
        self.stt_energy_slider.setValue(int(self.settings.get("stt_energy_threshold", 300)))
        self.stt_energy_slider.valueChanged.connect(self._on_energy_changed)
        mg_vbox.addWidget(self.stt_energy_slider)
        self.stt_energy_label = QLabel("")
        mg_vbox.addWidget(self.stt_energy_label)
        self.stt_dynamic_checkbox = QCheckBox(_("자동 감도 조정 사용"))
        self.stt_dynamic_checkbox.setChecked(bool(self.settings.get("stt_dynamic_energy", True)))
        mg_vbox.addWidget(self.stt_dynamic_checkbox)
        layout.addWidget(mic_group)

        # ── 웨이크워드 ─────────────────────────────────────────────────────────
        wake_group = QGroupBox(_("웨이크워드 목록"))
        wk_vbox = QVBoxLayout(wake_group)
        self.wake_words_list = QListWidget()
        for word in self.settings.get("wake_words", ["아리야", "시작"]):
            self.wake_words_list.addItem(QListWidgetItem(str(word)))
        wk_vbox.addWidget(self.wake_words_list)
        btn_row = QHBoxLayout()
        add_btn = QPushButton(_("추가"))
        add_btn.clicked.connect(self._add_wake_word)
        remove_btn = QPushButton(_("삭제"))
        remove_btn.clicked.connect(self._remove_wake_word)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        wk_vbox.addLayout(btn_row)
        layout.addWidget(wake_group)

        # ── 확인 / 취소 ────────────────────────────────────────────────────────
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(_("저장"))
        buttons.button(QDialogButtonBox.Cancel).setText(_("취소"))
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_energy_changed(self.stt_energy_slider.value())
        self._on_stt_changed()

    # ── 헬퍼 ──────────────────────────────────────────────────────────────────

    def _set_combo(self, combo: QComboBox, value) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    def _on_stt_changed(self):
        is_whisper = self.stt_provider_combo.currentData() == "whisper"
        self.whisper_group.setVisible(is_whisper)
        self.adjustSize()

    def _stt_diagnostic_settings(self) -> dict:
        settings = dict(self.settings)
        settings.update({
            "stt_provider": self.stt_provider_combo.currentData(),
            "whisper_model": self.whisper_model_combo.currentData(),
            "stt_energy_threshold": int(self.stt_energy_slider.value()),
            "stt_dynamic_energy": self.stt_dynamic_checkbox.isChecked(),
            "microphone": self.microphone_name,
        })
        return settings

    def _on_energy_changed(self, value: int):
        self.stt_energy_label.setText(_("현재 감도: {value}").format(value=value))

    def _download_whisper_model(self):
        model_name = self.whisper_model_combo.currentData() or "small"
        device = self.settings.get("whisper_device", "auto")
        compute_type = self.settings.get("whisper_compute_type", "int8")

        self.whisper_download_btn.setEnabled(False)
        self.whisper_download_btn.setText(_("다운로드 중..."))

        signals = _DownloadSignals()
        signals.finished.connect(self._on_download_finished)

        def _run():
            try:
                from core.stt_provider import WhisperSTTProvider
                provider = WhisperSTTProvider(
                    model_size=model_name, device=device, compute_type=compute_type
                )
                # 워커 정상 시작 확인 후 즉시 종료
                del provider
                signals.finished.emit(True, _("'{model}' 모델 준비가 완료되었습니다.").format(model=model_name))
            except Exception as exc:
                signals.finished.emit(False, _("모델 준비에 실패했습니다.\n{error}").format(error=exc))

        # 참조 유지 (GC 방지)
        self._download_signals = signals
        threading.Thread(target=_run, daemon=True, name="Whisper-Download").start()

    def _on_download_finished(self, success: bool, message: str):
        self.whisper_download_btn.setEnabled(True)
        self.whisper_download_btn.setText(_("모델 다운로드"))
        self._download_signals = None
        if success:
            QMessageBox.information(self, _("Whisper 다운로드"), message)
        else:
            QMessageBox.warning(self, _("Whisper 다운로드"), message)

    def _add_wake_word(self):
        text, ok = QInputDialog.getText(self, _("웨이크워드 추가"), _("새 웨이크워드를 입력하세요:"))
        value = text.strip()
        if ok and value:
            self.wake_words_list.addItem(QListWidgetItem(value))

    def _remove_wake_word(self):
        row = self.wake_words_list.currentRow()
        if row < 0:
            return
        if self.wake_words_list.count() <= 1:
            QMessageBox.warning(self, _("웨이크워드"), _("웨이크워드는 최소 1개 이상 필요합니다."))
            return
        self.wake_words_list.takeItem(row)

    def _save(self):
        hotkey = self.voice_hotkey_edit.keySequence().toString(
            QKeySequence.SequenceFormat.PortableText
        )
        try:
            parse_global_hotkey(hotkey)
        except ValueError:
            QMessageBox.warning(
                self,
                _("단축키 설정"),
                _("Ctrl+Alt+Space처럼 수정 키와 기본 키를 함께 지정하세요."),
            )
            return

        wake_words = [
            self.wake_words_list.item(i).text().strip()
            for i in range(self.wake_words_list.count())
            if self.wake_words_list.item(i).text().strip()
        ]
        if not wake_words:
            QMessageBox.warning(self, _("웨이크워드"), _("웨이크워드는 최소 1개 이상 필요합니다."))
            return

        current = ConfigManager.load_settings()
        current.update({
            "stt_provider": self.stt_provider_combo.currentData(),
            "whisper_model": self.whisper_model_combo.currentData(),
            "wake_words": wake_words,
            "wake_word_enabled": self.wake_word_enabled_checkbox.isChecked(),
            "voice_activation_hotkey": hotkey,
            "voice_activation_mode": self.voice_activation_mode_combo.currentData(),
            "stt_energy_threshold": int(self.stt_energy_slider.value()),
            "stt_dynamic_energy": self.stt_dynamic_checkbox.isChecked(),
        })
        ConfigManager.save_settings(current)
        logging.info("[STTSettingsDialog] STT 설정 저장 완료")
        self.accept()

"""
음성 인식(STT) 설정 다이얼로그 — STT 엔진, Whisper 옵션, 마이크 감도, 웨이크워드
"""
import logging
import threading
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QGroupBox,
    QListWidget, QListWidgetItem, QCheckBox,
    QInputDialog, QSlider, QMessageBox, QDialogButtonBox,
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QFont
from core.config_manager import ConfigManager
from ui.theme import FONT_KO, FONT_SIZE_NORMAL, INPUT_STYLE


class _DownloadSignals(QObject):
    finished = Signal(bool, str)  # (success, message)


class STTSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("음성 인식 설정")
        self.setMinimumWidth(420)
        self.setFont(QFont(FONT_KO, FONT_SIZE_NORMAL))
        self.setStyleSheet(INPUT_STYLE)
        self.settings = ConfigManager.load_settings()
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # ── STT 엔진 ──────────────────────────────────────────────────────────
        engine_group = QGroupBox("STT 엔진")
        eg_vbox = QVBoxLayout(engine_group)
        eg_vbox.addWidget(QLabel("음성 인식 엔진:"))
        self.stt_provider_combo = QComboBox()
        self.stt_provider_combo.addItem("Google STT (온라인)", "google")
        self.stt_provider_combo.addItem("Whisper (오프라인)", "whisper")
        self._set_combo(self.stt_provider_combo, self.settings.get("stt_provider", "google"))
        self.stt_provider_combo.currentIndexChanged.connect(self._on_stt_changed)
        eg_vbox.addWidget(self.stt_provider_combo)

        # ── Whisper 설정 ───────────────────────────────────────────────────────
        self.whisper_group = QGroupBox("Whisper 설정")
        wg_vbox = QVBoxLayout(self.whisper_group)
        wg_vbox.addWidget(QLabel("모델 크기:"))
        self.whisper_model_combo = QComboBox()
        for model_name in ("tiny", "small", "medium"):
            self.whisper_model_combo.addItem(model_name, model_name)
        self._set_combo(self.whisper_model_combo, self.settings.get("whisper_model", "small"))
        wg_vbox.addWidget(self.whisper_model_combo)
        self.whisper_download_btn = QPushButton("모델 다운로드")
        self.whisper_download_btn.clicked.connect(self._download_whisper_model)
        wg_vbox.addWidget(self.whisper_download_btn)
        eg_vbox.addWidget(self.whisper_group)

        layout.addWidget(engine_group)

        # ── 마이크 감도 ────────────────────────────────────────────────────────
        mic_group = QGroupBox("마이크 감도")
        mg_vbox = QVBoxLayout(mic_group)
        self.stt_energy_slider = QSlider(Qt.Horizontal)
        self.stt_energy_slider.setRange(100, 4000)
        self.stt_energy_slider.setValue(int(self.settings.get("stt_energy_threshold", 300)))
        self.stt_energy_slider.valueChanged.connect(self._on_energy_changed)
        mg_vbox.addWidget(self.stt_energy_slider)
        self.stt_energy_label = QLabel("")
        mg_vbox.addWidget(self.stt_energy_label)
        self.stt_dynamic_checkbox = QCheckBox("자동 감도 조정 사용")
        self.stt_dynamic_checkbox.setChecked(bool(self.settings.get("stt_dynamic_energy", True)))
        mg_vbox.addWidget(self.stt_dynamic_checkbox)
        layout.addWidget(mic_group)

        # ── 웨이크워드 ─────────────────────────────────────────────────────────
        wake_group = QGroupBox("웨이크워드 목록")
        wk_vbox = QVBoxLayout(wake_group)
        self.wake_words_list = QListWidget()
        for word in self.settings.get("wake_words", ["아리야", "시작"]):
            self.wake_words_list.addItem(QListWidgetItem(str(word)))
        wk_vbox.addWidget(self.wake_words_list)
        btn_row = QHBoxLayout()
        add_btn = QPushButton("추가")
        add_btn.clicked.connect(self._add_wake_word)
        remove_btn = QPushButton("삭제")
        remove_btn.clicked.connect(self._remove_wake_word)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        wk_vbox.addLayout(btn_row)
        layout.addWidget(wake_group)

        # ── 확인 / 취소 ────────────────────────────────────────────────────────
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("저장")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
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

    def _on_energy_changed(self, value: int):
        self.stt_energy_label.setText(f"현재 감도: {value}")

    def _download_whisper_model(self):
        model_name = self.whisper_model_combo.currentData() or "small"
        device = self.settings.get("whisper_device", "auto")
        compute_type = self.settings.get("whisper_compute_type", "int8")

        self.whisper_download_btn.setEnabled(False)
        self.whisper_download_btn.setText("다운로드 중...")

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
                signals.finished.emit(True, f"'{model_name}' 모델 준비가 완료되었습니다.")
            except Exception as exc:
                signals.finished.emit(False, f"모델 준비에 실패했습니다.\n{exc}")

        # 참조 유지 (GC 방지)
        self._download_signals = signals
        threading.Thread(target=_run, daemon=True, name="Whisper-Download").start()

    def _on_download_finished(self, success: bool, message: str):
        self.whisper_download_btn.setEnabled(True)
        self.whisper_download_btn.setText("모델 다운로드")
        self._download_signals = None
        if success:
            QMessageBox.information(self, "Whisper 다운로드", message)
        else:
            QMessageBox.warning(self, "Whisper 다운로드", message)

    def _add_wake_word(self):
        text, ok = QInputDialog.getText(self, "웨이크워드 추가", "새 웨이크워드를 입력하세요:")
        value = text.strip()
        if ok and value:
            self.wake_words_list.addItem(QListWidgetItem(value))

    def _remove_wake_word(self):
        row = self.wake_words_list.currentRow()
        if row < 0:
            return
        if self.wake_words_list.count() <= 1:
            QMessageBox.warning(self, "웨이크워드", "웨이크워드는 최소 1개 이상 필요합니다.")
            return
        self.wake_words_list.takeItem(row)

    def _save(self):
        wake_words = [
            self.wake_words_list.item(i).text().strip()
            for i in range(self.wake_words_list.count())
            if self.wake_words_list.item(i).text().strip()
        ]
        if not wake_words:
            QMessageBox.warning(self, "웨이크워드", "웨이크워드는 최소 1개 이상 필요합니다.")
            return

        current = ConfigManager.load_settings()
        current.update({
            "stt_provider": self.stt_provider_combo.currentData(),
            "whisper_model": self.whisper_model_combo.currentData(),
            "wake_words": wake_words,
            "stt_energy_threshold": int(self.stt_energy_slider.value()),
            "stt_dynamic_energy": self.stt_dynamic_checkbox.isChecked(),
        })
        ConfigManager.save_settings(current)
        logging.info("[STTSettingsDialog] STT 설정 저장 완료")
        self.accept()

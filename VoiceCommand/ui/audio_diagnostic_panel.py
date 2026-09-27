"""Settings panel for microphone level and record/playback checks."""

from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from i18n.translator import _
from ui.audio_diagnostics import AudioDiagnosticThread, _live_audio_diagnostic_threads
from ui.theme import secondary_btn_style


class _SafeAudioDiagnosticThread(AudioDiagnosticThread):
    def run(self):
        try:
            super().run()
        except Exception as exc:
            self.done.emit(self, False, str(exc))


class AudioDiagnosticPanel(QGroupBox):
    def __init__(self, input_device, output_device, parent=None):
        super().__init(_("마이크 및 스피커 진단"), parent)
        self._input_device = input_device
        self._output_device = output_device
        self._thread: AudioDiagnosticThread | None = None
        self._mode = ""
        self._closing = False

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(_("마이크 입력 레벨:")))
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setFormat("%p%")
        layout.addWidget(self.level_bar)

        buttons = QHBoxLayout()
        self.monitor_button = QPushButton(_("마이크 레벨 확인"))
        self.monitor_button.setStyleSheet(secondary_btn_style())
        self.monitor_button.clicked.connect(self._toggle_monitor)
        buttons.addWidget(self.monitor_button)
        self.record_button = QPushButton(_("3초 녹음 후 재생"))
        self.record_button.setStyleSheet(secondary_btn_style())
        self.record_button.clicked.connect(self._start_record_playback)
        buttons.addWidget(self.record_button)
        layout.addLayout(buttons)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        finished = getattr(self.window(), "finished", None)
        if finished is not None:
            finished.connect(self.cancel)

    def _toggle_monitor(self):
        if self._thread is not None and self._thread.isRunning():
            if self._mode == "monitor":
                self._thread.requestInterruption()
                self.status.setText(_("마이크 확인을 중지하고 있습니다..."))
            return
        self._start(monitor_only=True)

    def _start_record_playback(self):
        if self._thread is None or not self._thread.isRunning():
            self._start(monitor_only=False)

    def _start(self, monitor_only: bool):
        self._closing = False
        self._mode = "monitor" if monitor_only else "record_playback"
        self.monitor_button.setText(_("중지") if monitor_only else _("마이크 레벨 확인"))
        self.record_button.setEnabled(not monitor_only)
        self.status.setText(
            _("마이크 입력을 확인하고 있습니다...")
            if monitor_only
            else _("3초 동안 녹음하고 있습니다. 잠시 말씀해 주세요...")
        )
        self.status.setStyleSheet("color: #888;")
        thread = _SafeAudioDiagnosticThread(
            self._input_device(), self._output_device(), monitor_only=monitor_only
        )
        thread.level_changed.connect(self.level_bar.setValue)
        thread.done.connect(self._on_done)
        thread.finished.connect(lambda t=thread: _live_audio_diagnostic_threads.discard(t))
        _live_audio_diagnostic_threads.add(thread)
        self._thread = thread
        thread.start()

    def _on_done(self, thread: AudioDiagnosticThread, success: bool, message: str):
        if self._closing or self._thread is not thread:
            return
        self._thread = None
        self._mode = ""
        self.monitor_button.setText(_("마이크 레벨 확인"))
        self.record_button.setEnabled(True)
        if message:
            self.status.setText(message)
            self.status.setStyleSheet(
                f"color: {'#27ae60' if success else '#e74c3c'}; font-weight: bold;"
            )
        elif success:
            self.status.setText("")
            self.level_bar.setValue(0)

    def cancel(self, *_args):
        self._closing = True
        if self._thread is not None and self._thread.isRunning():
            self._thread.requestInterruption()

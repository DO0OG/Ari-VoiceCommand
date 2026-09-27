"""Background worker for testing the selected TTS provider."""

from typing import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton

from i18n.translator import _
from ui.diagnostic_helpers import run_tts_diagnostic
from ui.theme import secondary_btn_style


live_tts_diagnostic_threads: set[QThread] = set()


class TTSDiagnosticThread(QThread):
    done = Signal(bool, str)

    def __init__(
        self,
        settings: dict,
        selected_mode: str,
        output_device_name: str,
        provider_factory: Callable | None = None,
    ):
        super().__init__()
        self.settings = settings
        self.selected_mode = selected_mode
        self.output_device_name = output_device_name
        self.provider_factory = provider_factory

    def run(self):
        def create_diagnostic_provider(settings):
            factory = self.provider_factory
            if factory is None:
                from tts.tts_factory import create_tts_provider

                factory = create_tts_provider
            provider, actual_mode = factory(settings)
            volume = getattr(provider, "volume", None)
            if isinstance(volume, (int, float)):
                try:
                    provider.volume = min(2.0, max(0.0, float(settings.get("tts_volume", volume))))
                except (TypeError, ValueError):
                    pass
            return _DiagnosticProvider(provider), actual_mode

        self.done.emit(
            *run_tts_diagnostic(
                self.settings,
                self.selected_mode,
                self.output_device_name,
                _("안녕하세요. 음성 출력 시험 중입니다."),
                provider_factory=create_diagnostic_provider,
                is_cancelled=self.isInterruptionRequested,
            )
        )


class _DiagnosticProvider:
    def __init__(self, provider):
        self._provider = provider

    def speak(self, sentence: str) -> bool:
        result = self._provider.speak(sentence)
        return result and getattr(self._provider, "_last_playback_success", True) is not False

    def cleanup(self):
        cleanup = getattr(self._provider, "cleanup", None)
        if callable(cleanup):
            cleanup()


class TTSDiagnosticPanel(QGroupBox):
    def __init__(self, values_provider: Callable, parent=None):
        super().__init__(_("음성 출력 시험"), parent)
        self._values_provider = values_provider
        self._thread: TTSDiagnosticThread | None = None
        self._closing = False

        layout = QHBoxLayout(self)
        self.button = QPushButton(_("시험 재생"))
        self.button.setStyleSheet(secondary_btn_style())
        self.button.clicked.connect(self._start)
        layout.addWidget(self.button)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status, 1)

        finished = getattr(self.window(), "finished", None)
        if finished is not None:
            finished.connect(self.cancel)

    def _start(self):
        if self._thread is not None and self._thread.isRunning():
            return
        settings, mode, output_device_name = self._values_provider()
        self._closing = False
        self.button.setEnabled(False)
        self.status.setText(_("시험 재생 중..."))
        self.status.setStyleSheet("color: #888;")
        thread = TTSDiagnosticThread(settings, mode, output_device_name)
        thread.done.connect(self._on_done)
        thread.finished.connect(lambda t=thread: live_tts_diagnostic_threads.discard(t))
        live_tts_diagnostic_threads.add(thread)
        self._thread = thread
        thread.start()

    def _on_done(self, success: bool, message: str):
        if self._closing:
            return
        self.button.setEnabled(True)
        self.status.setText(message)
        self.status.setStyleSheet(
            f"color: {'#27ae60' if success else '#e74c3c'}; font-weight: bold;"
        )

    def cancel(self, *_args):
        self._closing = True
        if self._thread is not None and self._thread.isRunning():
            self._thread.requestInterruption()

"""Background worker for recording and transcribing a short STT sample."""

from typing import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from i18n.translator import _
from ui.diagnostic_helpers import resolve_input_device_index, transcribe_diagnostic_sample
from ui.theme import secondary_btn_style


live_stt_sample_threads: set[QThread] = set()


class STTSampleThread(QThread):
    status_changed = Signal(str)
    done = Signal(bool, str)

    def __init__(self, settings: dict, microphone_name: str):
        super().__init__()
        self.settings = settings
        self.microphone_name = microphone_name

    def run(self):
        try:
            import speech_recognition as sr
            from audio.audio_manager import GlobalAudio, get_audio_lock

            audio_lock = get_audio_lock()
            audio_acquired = False
            pa = GlobalAudio.get_instance()
            devices = [pa.get_device_info_by_index(i) for i in range(pa.get_device_count())]
            microphone_index = resolve_input_device_index(self.microphone_name, devices)
            if not audio_lock.acquire(timeout=3):
                raise RuntimeError(_("마이크가 다른 작업에서 사용 중입니다. 잠시 후 다시 시도해 주세요."))
            audio_acquired = True

            recognizer = sr.Recognizer()
            recognizer.energy_threshold = int(self.settings.get("stt_energy_threshold", 300))
            recognizer.dynamic_energy_threshold = bool(self.settings.get("stt_dynamic_energy", True))
            self.status_changed.emit(_("지금 짧은 문장을 말씀해 주세요."))
            from VoiceCommand import SharedMicrophone
            microphone = SharedMicrophone(device_index=microphone_index)
            with microphone as source:
                if microphone.stream is None:
                    raise OSError(_("선택한 마이크를 찾을 수 없습니다. 장치를 다시 선택해 주세요."))
                recognizer.adjust_for_ambient_noise(source, duration=0.25)
                audio_data = recognizer.listen(source, timeout=5, phrase_time_limit=4)
            audio_lock.release()
            audio_acquired = False

            if self.isInterruptionRequested():
                self.done.emit(True, "")
                return
            self.status_changed.emit(_("음성을 인식하고 있습니다..."))
            self.done.emit(*transcribe_diagnostic_sample(audio_data, self.settings))
        except Exception as exc:
            if "sr" in locals() and isinstance(exc, sr.WaitTimeoutError):
                self.done.emit(False, _("음성을 듣지 못했습니다. 다시 시험해 주세요."))
            else:
                self.done.emit(False, _("음성 인식 시험에 실패했습니다: {error}").format(error=exc))
        finally:
            if locals().get("audio_acquired"):
                audio_lock.release()


class STTSampleDiagnosticPanel(QGroupBox):
    def __init__(self, settings_provider: Callable[[], dict], microphone_name: str, parent=None):
        super().__init__(_("음성 인식 시험"), parent)
        self._settings_provider = settings_provider
        self._microphone_name = microphone_name
        self._thread: STTSampleThread | None = None
        self._closing = False

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.button = QPushButton(_("짧은 문장 인식"))
        self.button.setStyleSheet(secondary_btn_style())
        self.button.clicked.connect(self._start)
        row.addWidget(self.button)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        layout.addLayout(row)

        finished = getattr(self.window(), "finished", None)
        if finished is not None:
            finished.connect(self.cancel)

    def _start(self):
        if self._thread is not None and self._thread.isRunning():
            return
        settings = self._settings_provider()
        self._closing = False
        self.button.setEnabled(False)
        self.status.setText(_("마이크를 준비하고 있습니다..."))
        self.status.setStyleSheet("color: #888;")
        thread = STTSampleThread(settings, self._microphone_name)
        thread.status_changed.connect(self._on_status_changed)
        thread.done.connect(self._on_done)
        thread.finished.connect(lambda t=thread: live_stt_sample_threads.discard(t))
        live_stt_sample_threads.add(thread)
        self._thread = thread
        thread.start()

    def _on_status_changed(self, message: str):
        if not self._closing:
            self.status.setText(message)

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

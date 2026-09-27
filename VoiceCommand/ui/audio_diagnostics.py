"""설정 화면의 마이크 확인과 녹음 재생 작업."""
from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal

from audio.audio_manager import (
    GlobalAudio,
    find_output_device_candidates,
    get_audio_lock,
    get_audio_output_lock,
)
from i18n.translator import _
from ui.diagnostic_helpers import pcm_level_percent, resolve_input_device_index


_live_audio_diagnostic_threads: set[QThread] = set()


class AudioDiagnosticThread(QThread):
    level_changed = Signal(int)
    done = Signal(object, bool, str)

    def __init__(
        self,
        input_device_name: str,
        output_device_name: str,
        monitor_only: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.input_device_name = input_device_name
        self.output_device_name = output_device_name
        self.monitor_only = monitor_only

    def run(self):
        import pyaudio

        input_lock = get_audio_lock()
        output_lock = get_audio_output_lock()
        input_stream = None
        input_acquired = False
        pa = None
        try:
            pa = GlobalAudio.get_instance()
            input_devices = [pa.get_device_info_by_index(i) for i in range(pa.get_device_count())]
            input_device_index = resolve_input_device_index(self.input_device_name, input_devices)

            output_device_indices = []
            if not self.monitor_only:
                if self.output_device_name:
                    output_device_indices = find_output_device_candidates(self.output_device_name)
                    if not output_device_indices:
                        raise RuntimeError(_("선택한 스피커를 찾을 수 없습니다. 장치를 다시 선택해 주세요."))
                else:
                    output_device_indices = [None]

            if not input_lock.acquire(timeout=3):
                raise RuntimeError(_("마이크가 다른 작업에서 사용 중입니다. 잠시 후 다시 시도해 주세요."))
            input_acquired = True
            input_stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                input_device_index=input_device_index,
                frames_per_buffer=1024,
            )

            chunks: list[bytes] = []
            started = time.monotonic()
            capture_seconds = None if self.monitor_only else 3.0
            while not self.isInterruptionRequested():
                if capture_seconds is not None and time.monotonic() - started >= capture_seconds:
                    break
                chunk = input_stream.read(1024, exception_on_overflow=False)
                self.level_changed.emit(pcm_level_percent(chunk))
                if not self.monitor_only:
                    chunks.append(chunk)

            input_stream.stop_stream()
            input_stream.close()
            input_stream = None
            input_lock.release()
            input_acquired = False

            if self.isInterruptionRequested():
                self.done.emit(self, True, "")
                return
            if self.monitor_only:
                self.done.emit(self, True, "")
                return

            if not output_lock.acquire(timeout=3):
                raise RuntimeError(_("스피커가 다른 작업에서 사용 중입니다. 잠시 후 다시 시도해 주세요."))
            try:
                audio_data = b"".join(chunks)
                last_error = None
                output_stream = None
                for device_index in output_device_indices:
                    try:
                        output_stream = pa.open(
                            format=pyaudio.paInt16,
                            channels=1,
                            rate=16000,
                            output=True,
                            output_device_index=device_index,
                            frames_per_buffer=1024,
                        )
                        break
                    except Exception as exc:
                        last_error = exc
                if output_stream is None:
                    raise RuntimeError(
                        _("스피커 출력 장치를 열지 못했습니다: {error}").format(error=last_error)
                    )
                try:
                    frame_bytes = 1024 * 2
                    for offset in range(0, len(audio_data), frame_bytes):
                        if self.isInterruptionRequested():
                            break
                        output_stream.write(audio_data[offset:offset + frame_bytes])
                    output_stream.stop_stream()
                finally:
                    output_stream.close()
            finally:
                output_lock.release()

            if self.isInterruptionRequested():
                self.done.emit(self, True, "")
            else:
                self.done.emit(self, True, _("녹음한 소리를 선택한 스피커로 재생했습니다."))
        except Exception as exc:
            self.done.emit(self, False, str(exc))
        finally:
            if input_stream is not None:
                try:
                    input_stream.stop_stream()
                except Exception:
                    pass
                try:
                    input_stream.close()
                except Exception:
                    pass
            if input_acquired:
                input_lock.release()

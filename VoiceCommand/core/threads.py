"""음성 인식, TTS, 명령 실행을 담당하는 Qt 작업 스레드 모음."""

import logging
import time
import secrets
import queue
import threading
from contextlib import contextmanager
from collections import deque
from typing import Callable
import speech_recognition as sr
from queue import Queue
from PySide6.QtCore import QThread, Signal
from audio.audio_manager import _audio_lock
from core.constants import (
    SPEECH_REPEAT_NOTICE_DURATION_MS,
    WAKE_WORDS,
    get_wake_responses,
)
from core.config_manager import ConfigManager
from core.stt_provider import create_stt_provider

_RNG = secrets.SystemRandom()


def _wait_for_tts_playback_completion(
    is_tts_playing: Callable[[], bool],
    playback_finished: threading.Event,
    timeout: float = 15.0,
    now_fn: Callable[[], float] = time.monotonic,
) -> bool:
    """TTS 재생 완료 이벤트를 기다린다."""
    wait_start = now_fn()
    while is_tts_playing():
        elapsed = now_fn() - wait_start
        remaining = timeout - elapsed
        if remaining <= 0:
            logging.warning("TTS 대기 타임아웃 (%.0f초 초과)", timeout)
            return False
        # 완료 신호가 누락돼도 오래 멈추지 않도록 짧게 나눠 기다린다.
        playback_finished.wait(min(remaining, 0.3))
        playback_finished.clear()
    return True

# ───────────────────────────────────────────────────────────────────────────
# VoiceRecognitionThread
# ───────────────────────────────────────────────────────────────────────────

class VoiceRecognitionThread(QThread):
    """음성 인식 스레드: 웨이크워드 감지 및 명령 처리"""
    result = Signal(str)
    listening_state_changed = Signal(bool)
    microphone_unavailable = Signal()

    def __init__(self):
        super().__init__()
        self.running = True
        self.selected_microphone = None
        self.microphone_index = None
        self.microphone_available: bool | None = None
        self._microphone_status_lock = threading.Lock()
        self._microphone_notification_claimed = False
        self._microphone_request_lock = threading.Lock()
        self._microphone_wakeup = threading.Event()
        self._microphone_request_pending = False
        self._pending_microphone = None
        self._voice_wakeup = threading.Event()
        self._voice_activation_lock = threading.Lock()
        self._pending_voice_activation = None
        self._active_voice_activation = None
        self._command_listening = False
        self._microphone_active = False
        self._microphone_probed = False
        self._voice_setup_failed = False
        self._stt_signature = None
        self._stt = None
        self._last_texts = deque(maxlen=3)

        self.wake_detector = None
        from VoiceCommand import SharedMicrophone
        self.speech_recognizer = None
        self.microphone = None
        try:
            self.microphone = SharedMicrophone(device_index=self.microphone_index)
            self.microphone_available = True
            self._microphone_active = True
        except Exception as exc:
            logging.warning("마이크 초기화 실패: %s. 음성 인식을 사용할 수 없습니다.", exc)
            self.microphone_available = False
            self.microphone_unavailable.emit()

    def set_microphone(self, microphone):
        """Request a microphone change without opening PyAudio on the caller thread."""
        microphone = microphone or None
        with self._microphone_request_lock:
            if (
                not self._microphone_request_pending
                and self.selected_microphone == microphone
                and self._microphone_active
                and not self._voice_setup_failed
            ):
                return
            self._pending_microphone = microphone
            self._microphone_request_pending = True
            if not self._microphone_active:
                self._set_microphone_status(None)
            self._microphone_wakeup.set()

    def request_listening(self, push_to_talk=False) -> bool:
        """음성 입력 시작을 대기 루프에 전달한다."""
        if (
            not self.running
            or self.microphone is None
            or not self._microphone_active
            or self._voice_setup_failed
        ):
            return False
        with self._voice_activation_lock:
            if (
                self._pending_voice_activation
                or self._active_voice_activation
                or self._command_listening
            ):
                return False
            self._pending_voice_activation = {
                "released": threading.Event() if push_to_talk else None,
            }
            self._voice_wakeup.set()
        return True

    def release_listening(self) -> None:
        """push-to-talk 입력 종료를 전달한다."""
        with self._voice_activation_lock:
            request = self._active_voice_activation or self._pending_voice_activation
            if request and request["released"] is not None:
                request["released"].set()

    def refresh_voice_settings(self) -> None:
        """음성 설정 변경을 대기 루프에 알린다."""
        self._voice_wakeup.set()

    def _take_voice_activation(self):
        with self._voice_activation_lock:
            request = self._pending_voice_activation
            self._pending_voice_activation = None
            self._voice_wakeup.clear()
            if request is not None:
                self._active_voice_activation = request
                self._command_listening = True
            return request

    def _finish_voice_activation(self) -> None:
        with self._voice_activation_lock:
            self._active_voice_activation = None
            self._command_listening = False

    def _discard_pending_voice_activation(self) -> None:
        with self._voice_activation_lock:
            request = self._pending_voice_activation
            self._pending_voice_activation = None
            self._voice_wakeup.clear()
        if request and request["released"] is not None:
            request["released"].set()

    def claim_microphone_unavailable_notification(self) -> bool:
        """Return true once when the UI should show the missing-microphone notice."""
        with self._microphone_status_lock:
            if self.microphone_available is not False or self._microphone_notification_claimed:
                return False
            self._microphone_notification_claimed = True
            return True

    def _take_pending_microphone(self):
        with self._microphone_request_lock:
            if not self._microphone_request_pending:
                return False, None
            microphone = self._pending_microphone
            self._microphone_request_pending = False
            self._pending_microphone = None
            self._microphone_wakeup.clear()
            return True, microphone

    def _set_microphone_status(self, available: bool | None):
        with self._microphone_status_lock:
            self.microphone_available = available
        if available is False:
            self.microphone_unavailable.emit()

    def _probe_microphone(self, microphone) -> None:
        with self._microphone_source(microphone):
            pass

    @contextmanager
    def _microphone_source(self, microphone=None):
        microphone = microphone or self.microphone
        if microphone is None:
            raise OSError("마이크를 사용할 수 없습니다.")
        with _audio_lock:
            with microphone as source:
                if source is None or getattr(microphone, "stream", None) is None:
                    raise OSError("마이크 입력 스트림을 열 수 없습니다.")
                yield source

    def _disable_microphone(self, error, context="마이크 입력을 사용할 수 없습니다"):
        with self._microphone_request_lock:
            self.microphone = None
            self._microphone_active = False
        self._microphone_probed = False
        logging.warning("%s: %s", context, error)
        self._set_microphone_status(False)

    def _apply_pending_microphone(self):
        pending, microphone_name = self._take_pending_microphone()
        if not pending:
            return

        from VoiceCommand import SharedMicrophone, get_microphone_index_helper

        previous_microphone = self.microphone
        wake_word_enabled = bool(ConfigManager.get("wake_word_enabled", True))
        try:
            microphone_index = get_microphone_index_helper(microphone_name)
            microphone = SharedMicrophone(device_index=microphone_index)
            if wake_word_enabled:
                self._probe_microphone(microphone)
        except Exception as exc:
            if previous_microphone is None:
                self._disable_microphone(exc, "설정한 마이크를 사용할 수 없습니다")
            else:
                logging.warning("설정한 마이크를 사용할 수 없어 현재 마이크를 유지합니다: %s", exc)
            return

        with self._microphone_request_lock:
            self.microphone = microphone
            self.selected_microphone = microphone_name
            self.microphone_index = microphone_index
            self._microphone_active = True
        self._microphone_probed = wake_word_enabled
        self._voice_setup_failed = False
        self._set_microphone_status(True)

    def _initialize_voice_recognition(self, initialize_wake_detector=True) -> bool:
        if self.speech_recognizer is not None and (
            not initialize_wake_detector or self.wake_detector is not None
        ):
            return True
        try:
            if self.speech_recognizer is None:
                self.speech_recognizer = sr.Recognizer()
                self._apply_recognizer_settings()
            self._refresh_stt_provider()
            if initialize_wake_detector and self.wake_detector is None:
                from audio.simple_wake import SimpleWakeWord

                self.wake_detector = SimpleWakeWord(
                    wake_words=ConfigManager.get("wake_words", WAKE_WORDS),
                    stt_provider=self._stt,
                    provider_signature=self._stt_signature,
                )
            return True
        except Exception as exc:
            self.wake_detector = None
            self._voice_setup_failed = True
            logging.warning("음성 인식 기능 초기화 실패: %s", exc, exc_info=True)
            return False

    def _apply_recognizer_settings(self):
        self.speech_recognizer.energy_threshold = int(ConfigManager.get("stt_energy_threshold", 300))
        self.speech_recognizer.dynamic_energy_threshold = bool(ConfigManager.get("stt_dynamic_energy", True))
        pause_threshold = max(0.0, float(ConfigManager.get("stt_pause_threshold", 0.6)))
        self.speech_recognizer.pause_threshold = pause_threshold
        self.speech_recognizer.non_speaking_duration = min(
            self.speech_recognizer.non_speaking_duration,
            pause_threshold,
        )

    def _refresh_stt_provider(self):
        settings = ConfigManager.load_settings()
        signature = (
            settings.get("stt_provider", "google"),
            settings.get("whisper_model", "small"),
            settings.get("whisper_device", "auto"),
            settings.get("whisper_compute_type", "int8"),
        )
        needs_refresh = signature != self._stt_signature
        if not needs_refresh and self._stt is not None and hasattr(self._stt, "is_healthy"):
            try:
                needs_refresh = not bool(self._stt.is_healthy())
            except Exception:
                needs_refresh = True
        if needs_refresh:
            self._stt_signature = signature
            self._stt = create_stt_provider(settings)
            logging.info("[VoiceRecognitionThread] STT 프로바이더 갱신: %s", signature[0])
            # wake_detector와 STT 프로바이더 인스턴스 공유 — 중복 워커 생성 방지
            if hasattr(self, "wake_detector") and self.wake_detector is not None:
                self.wake_detector._stt = self._stt
                self.wake_detector._provider_signature = signature

    def run(self):
        try:
            logging.info("음성 감지 루프 시작")
            while self.running:
                self._apply_pending_microphone()
                if not self.running:
                    break
                if self.microphone is None or self._voice_setup_failed:
                    self._microphone_wakeup.wait()
                    continue

                wake_word_enabled = bool(ConfigManager.get("wake_word_enabled", True))
                if not wake_word_enabled:
                    self._voice_wakeup.wait()
                    request = self._take_voice_activation()
                    if request is not None:
                        self._listen_for_manual_activation(request)
                    continue

                if not self._microphone_probed:
                    try:
                        self._probe_microphone(self.microphone)
                        self._microphone_probed = True
                        self._set_microphone_status(True)
                    except Exception as exc:
                        self._disable_microphone(exc, "마이크 입력을 열 수 없습니다")
                        continue

                if not self._initialize_voice_recognition():
                    self._microphone_wakeup.wait()
                    continue

                try:
                    self._apply_recognizer_settings()
                    self._refresh_stt_provider()
                except Exception as exc:
                    self._voice_setup_failed = True
                    logging.warning("음성 인식 설정을 적용하지 못했습니다: %s", exc, exc_info=True)
                    continue
                from VoiceCommand import is_session_lock_blocked, should_pause_wake_detection
                request = self._take_voice_activation()
                if request is not None:
                    self._listen_for_manual_activation(request)
                    continue
                if should_pause_wake_detection():
                    time.sleep(0.05)
                    continue
                # 오디오 장치 점유를 위해 락 획득
                try:
                    with self._microphone_source() as source:
                        detected = self.wake_detector.listen_for_wake_word(
                            source,
                            detection_allowed=lambda: not should_pause_wake_detection(),
                            interrupt_event=self._voice_wakeup,
                        )
                except (OSError, RuntimeError, AssertionError, AttributeError, ValueError) as exc:
                    self._disable_microphone(exc, "마이크 입력 중 오류가 발생했습니다")
                    continue
                except Exception as exc:
                    self._voice_setup_failed = True
                    logging.error("웨이크워드 처리 실패: %s", exc, exc_info=True)
                    continue

                try:
                    request = self._take_voice_activation()
                    if request is not None:
                        self._listen_for_manual_activation(request)
                        continue
                    if detected and is_session_lock_blocked():
                        time.sleep(0.05)
                        continue

                    if detected and should_pause_wake_detection():
                        logging.info("TTS 보호 구간과 겹친 웨이크워드 감지를 무시합니다.")
                        with self._microphone_source() as source:
                            self.wake_detector.recalibrate(source)
                        time.sleep(0.05)
                        continue

                    if detected:
                        self.handle_wake_word(
                            getattr(self.wake_detector, "detected_command", None)
                        )
                except (OSError, RuntimeError, AssertionError, AttributeError, ValueError) as exc:
                    self._disable_microphone(exc, "음성 인식 중 마이크 오류가 발생했습니다")
                    continue
                except Exception as exc:
                    self._voice_setup_failed = True
                    logging.error("음성 인식 처리 실패: %s", exc, exc_info=True)
                    continue
                
                time.sleep(0.1)
        except Exception as e:
            logging.error("VoiceRecognitionThread 오류: %s", e, exc_info=True)
        finally:
            self.cleanup()

    def handle_wake_word(self, command_text=None):
        from VoiceCommand import _state, is_session_lock_blocked, tts_wrapper

        if is_session_lock_blocked():
            return
        with self._voice_activation_lock:
            if self._command_listening:
                return
            self._command_listening = True

        logging.info("웨이크 워드 감지됨!")
        if isinstance(command_text, str):
            command_text = command_text.strip() or None
        else:
            command_text = None

        try:
            if command_text is not None:
                if not is_session_lock_blocked():
                    self.result.emit(command_text)
            else:
                response = _RNG.choice(get_wake_responses())
                _state.tts_playback_finished_event.clear()
                tts_wrapper(response)

                try:
                    from VoiceCommand import is_tts_playing
                    _wait_for_tts_playback_completion(
                        is_tts_playing,
                        _state.tts_playback_finished_event,
                    )
                    delay_ms = max(0, int(ConfigManager.get("post_tts_listen_delay_ms", 100)))
                    time.sleep(delay_ms / 1000)
                except Exception as e:
                    logging.error("TTS 대기 중 오류: %s", e)
                    time.sleep(0.5)

                self._discard_pending_voice_activation()
                if is_session_lock_blocked():
                    return
                self._listen_for_command()
        finally:
            with self._voice_activation_lock:
                self._command_listening = False

        if is_session_lock_blocked():
            return
        # 대화 후 재캘리브레이션
        from VoiceCommand import wake_detector_recalibrate_helper
        with self._microphone_source() as source:
            wake_detector_recalibrate_helper(self.wake_detector, source)

    def _listen_for_command(self, push_to_talk_released=None):
        from VoiceCommand import (
            recognize_speech_helper,
            set_listening_indicator,
            _show_tts_bubble,
            is_session_lock_blocked,
        )

        if is_session_lock_blocked():
            return
        with self._voice_activation_lock:
            started_here = not self._command_listening
            self._command_listening = True
        set_listening_indicator(True)
        self.listening_state_changed.emit(True)
        duplicate_notice = None
        try:
            with self._microphone_source() as source:
                duplicate_notice = recognize_speech_helper(
                    self.speech_recognizer,
                    source,
                    self.result,
                    stt_provider=self._stt,
                    previous_texts=self._last_texts,
                    continue_check=lambda: not is_session_lock_blocked(),
                    push_to_talk_released=push_to_talk_released,
                )
        finally:
            set_listening_indicator(False)
            self.listening_state_changed.emit(False)
            if started_here:
                with self._voice_activation_lock:
                    self._command_listening = False
        if duplicate_notice:
            _show_tts_bubble(
                duplicate_notice,
                duration=SPEECH_REPEAT_NOTICE_DURATION_MS,
            )

    def _listen_for_manual_activation(self, request):
        from VoiceCommand import (
            is_session_lock_blocked,
            is_tts_playing,
            wake_detector_recalibrate_helper,
        )

        try:
            if is_session_lock_blocked():
                logging.info("잠금 상태에서 음성 입력 시작을 무시합니다.")
                return
            if is_tts_playing():
                logging.info("TTS 재생 중 음성 입력 시작을 무시합니다.")
                return
            wake_word_enabled = bool(ConfigManager.get("wake_word_enabled", True))
            if not self._initialize_voice_recognition(wake_word_enabled):
                return
            self._apply_recognizer_settings()
            self._refresh_stt_provider()
            self._listen_for_command(request["released"])
            self._microphone_probed = True
            if wake_word_enabled and self.wake_detector is not None:
                with self._microphone_source() as source:
                    wake_detector_recalibrate_helper(self.wake_detector, source)
        except (OSError, RuntimeError, AssertionError, AttributeError, ValueError) as exc:
            self._disable_microphone(exc, "음성 입력 중 마이크 오류가 발생했습니다")
        except Exception as exc:
            logging.error("단축키·클릭 음성 입력 실패: %s", exc, exc_info=True)
        finally:
            self._finish_voice_activation()

    def cleanup(self):
        if hasattr(self, 'wake_detector'):
            if self.wake_detector is not None:
                self.wake_detector.should_stop = True
                self.wake_detector.flush_pending_settings()
        self.microphone = None

    def stop(self):
        self.running = False
        self._microphone_wakeup.set()
        self.release_listening()
        self._voice_wakeup.set()
        if getattr(self, 'wake_detector', None) is not None:
            self.wake_detector.should_stop = True
        self.wait(2000)


# ───────────────────────────────────────────────────────────────────────────
# TTSThread
# ───────────────────────────────────────────────────────────────────────────

class TTSThread(QThread):
    """TTS 전용 작업 스레드: 큐를 통해 순차 재생"""
    _MAX_QUEUE_SIZE = 32
    _COALESCE_WINDOW_SEC = 0.08

    def __init__(self):
        super().__init__()
        self.queue = Queue(maxsize=self._MAX_QUEUE_SIZE)
        self.is_processing = False
        self._shutdown_requested = False
        self._shutdown_lock = threading.Lock()

    def _collect_batch(self, first_text):
        texts = []
        task_count = 1
        stop_requested = False

        if first_text:
            stripped = str(first_text).strip()
            if stripped:
                texts.append(stripped)

        deadline = time.monotonic() + self._COALESCE_WINDOW_SEC
        while True:
            drained = False
            while True:
                try:
                    next_text = self.queue.get_nowait()
                except queue.Empty:
                    break
                task_count += 1
                drained = True
                if next_text is None:
                    stop_requested = True
                    break
                stripped = str(next_text).strip()
                if stripped:
                    texts.append(stripped)
            if stop_requested:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if not drained:
                time.sleep(min(0.01, remaining))

        if len(texts) > 1:
            logging.debug("[TTSThread] 인접한 TTS 요청 %d개를 1개로 병합", len(texts))
        return " ".join(texts).strip(), task_count, stop_requested

    def run(self):
        logging.info("TTSThread 구동 중")
        while True:
            try:
                text = self.queue.get(timeout=1.0)
                if text is None:
                    self.queue.task_done()
                    break

                self.is_processing = True
                batch_text, task_count, stop_requested = self._collect_batch(text)

                try:
                    from VoiceCommand import text_to_speech
                    if batch_text and not self._shutdown_requested:
                        text_to_speech(batch_text)
                finally:
                    for _ in range(task_count):
                        self.queue.task_done()
                    self.is_processing = False

                # 큐가 완전히 비었을 때 현재 상태(STT 대기 포함)에 맞게 말풍선을 정리
                if self.queue.empty():
                    from VoiceCommand import _handle_tts_playback_finished
                    _handle_tts_playback_finished()
                if stop_requested:
                    break
                    
            except queue.Empty:
                continue

    def speak(self, text):
        if not text:
            return False
        with self._shutdown_lock:
            if self._shutdown_requested:
                return False
            try:
                self.queue.put_nowait(text)
                return True
            except queue.Full:
                logging.warning("TTSThread 큐가 가득 차서 마지막 요청을 폐기했습니다.")
                return False

    def stop(self):
        with self._shutdown_lock:
            if self._shutdown_requested:
                return
            self._shutdown_requested = True

            try:
                from VoiceCommand import _state

                provider_stop = getattr(_state.fish_tts, "stop", None)
                if callable(provider_stop):
                    provider_stop()
            except (
                AttributeError,
                ImportError,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as exc:
                logging.debug("현재 TTS 재생 중지 생략: %s", exc)

            while True:
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    break
                else:
                    self.queue.task_done()
            self.queue.put_nowait(None)


# ───────────────────────────────────────────────────────────────────────────
# CommandExecutionThread
# ───────────────────────────────────────────────────────────────────────────

class CommandExecutionThread(QThread):
    """명령 실행 전용 스레드: 메인 스레드 차단 방지"""
    def __init__(self):
        super().__init__()
        self.queue = Queue()

    def run(self):
        logging.info("CommandExecutionThread 구동 중")
        while True:
            try:
                command = self.queue.get(timeout=1.0)
                try:
                    if command is None:
                        break

                    from VoiceCommand import execute_command
                    execute_command(command)
                finally:
                    self.queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logging.error("CommandExecutionThread 오류: %s", e)
                continue

    def execute(self, command):
        self.queue.put(command)

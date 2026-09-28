"""
간단한 음성 트리거 (계정 불필요)
"""
import logging
import math
import re
import struct
import time
from collections import deque

import speech_recognition as sr

from core.config_manager import ConfigManager
from core.stt_provider import create_stt_provider


_NORMALIZE_WHITESPACE_RE = re.compile(r"\s+")
_STRIP_PUNCTUATION_RE = re.compile(r"[^0-9A-Za-z가-힣\s]+")
_WAKE_MIN_AUDIO_SECONDS = 0.3
_WAKE_MAX_AUDIO_SECONDS = 1.5
_ENERGY_SAVE_DELAY_SECONDS = 1.0


def should_transcribe_wake_audio(audio_data, energy_threshold):
    """웨이크 대기 오디오의 길이와 에너지 분포를 확인한다."""
    sample_rate = audio_data.sample_rate
    if sample_rate <= 0:
        return False

    raw_data = audio_data.get_raw_data(convert_width=2)
    if not raw_data or len(raw_data) % 2:
        return False

    frame_size = max(1, int(sample_rate * 0.02))
    frame_energies = []
    frame_energy = 0
    frame_length = 0
    for (sample,) in struct.iter_unpack("<h", raw_data):
        frame_energy += sample * sample
        frame_length += 1
        if frame_length == frame_size:
            frame_energies.append(math.sqrt(frame_energy / frame_length))
            frame_energy = 0
            frame_length = 0
    if frame_length:
        frame_energies.append(math.sqrt(frame_energy / frame_length))

    threshold = max(1.0, float(energy_threshold))
    active_indexes = [
        index for index, energy in enumerate(frame_energies) if energy >= threshold
    ]
    if not active_indexes:
        return False
    # 녹음에는 말 끝의 무음이 붙으므로 첫·마지막 소리 프레임 사이를 발화 길이로 본다.
    span_frames = active_indexes[-1] - active_indexes[0] + 1
    speech_seconds = span_frames * frame_size / sample_rate
    if not _WAKE_MIN_AUDIO_SECONDS <= speech_seconds <= _WAKE_MAX_AUDIO_SECONDS:
        return False
    active_energies = [frame_energies[index] for index in active_indexes]
    if len(active_energies) / span_frames < 0.15:
        return False

    active_mean = sum(active_energies) / len(active_energies)
    active_variance = sum((energy - active_mean) ** 2 for energy in active_energies)
    active_deviation = math.sqrt(active_variance / len(active_energies))
    steady_frames = max(8, int(0.25 * sample_rate / frame_size))
    # 에너지가 고르게 이어지면 음악으로 본다. 짧은 음악 구분은 한계가 있어 필요하면 VAD로 바꾼다.
    if len(active_energies) >= steady_frames and active_deviation / active_mean < 0.12:
        return False
    return True


class SimpleWakeWord:
    def __init__(self, wake_words=None):
        self.wake_words = list(wake_words or ["아리야", "시작"])
        self.recognizer = sr.Recognizer()
        self.should_stop = False
        self._calibrated = False  # 첫 listen 시 lazy 캘리브레이션
        self._configured_energy_threshold = None
        self._saved_energy_threshold = None
        self._pending_energy_threshold = None
        self._pending_energy_since = None
        self._stt_call_times = deque()
        self._last_stt_metric_log = time.monotonic()
        self._provider_signature = None
        self._stt = None
        self.refresh_settings()

    def refresh_settings(self):
        settings = ConfigManager.load_settings()
        self.wake_words = list(settings.get("wake_words", self.wake_words) or ["아리야", "시작"])
        energy_threshold = int(settings.get("stt_energy_threshold", 300))
        if energy_threshold != self._configured_energy_threshold:
            self.recognizer.energy_threshold = energy_threshold
            self._configured_energy_threshold = energy_threshold
            self._saved_energy_threshold = energy_threshold
            self._pending_energy_threshold = None
            self._pending_energy_since = None
        self.recognizer.dynamic_energy_threshold = bool(settings.get("stt_dynamic_energy", True))

        signature = (
            settings.get("stt_provider", "google"),
            settings.get("whisper_model", "small"),
            settings.get("whisper_device", "auto"),
            settings.get("whisper_compute_type", "int8"),
        )
        needs_refresh = signature != self._provider_signature
        if not needs_refresh and self._stt is not None and hasattr(self._stt, "is_healthy"):
            try:
                needs_refresh = not bool(self._stt.is_healthy())
            except Exception:
                needs_refresh = True
        if needs_refresh:
            self._provider_signature = signature
            self._stt = create_stt_provider(settings)
            self._calibrated = False
            logging.info("[WakeWord] STT 프로바이더 갱신: %s", signature[0])

    def _normalize_text(self, text):
        normalized = _STRIP_PUNCTUATION_RE.sub(" ", text or "")
        normalized = _NORMALIZE_WHITESPACE_RE.sub(" ", normalized)
        return normalized.strip().lower()

    def _matches_wake_word(self, text, wake_word):
        normalized_text = self._normalize_text(text)
        normalized_wake_word = self._normalize_text(wake_word)
        if not normalized_text or not normalized_wake_word:
            return False
        return normalized_text == normalized_wake_word

    def recalibrate(self, source):
        """TTS 이후 환경 변화 시 임계값 재조정"""
        try:
            self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            self._save_energy_threshold()
            logging.debug(f"재캘리브레이션 완료 (energy_threshold={self.recognizer.energy_threshold:.1f})")
        except Exception as e:
            logging.debug(f"재캘리브레이션 실패: {e}")

    def listen_for_wake_word(self, source, detection_allowed=None):
        """웨이크워드 대기 — 첫 호출 시 캘리브레이션, 이후 즉시 청취"""
        if self.should_stop:
            return False
        try:
            self._log_stt_call_rate()
            self.refresh_settings()
            self._flush_pending_energy_threshold()
            if not self._calibrated:
                self.recognizer.adjust_for_ambient_noise(source, duration=1.0)
                self._calibrated = True
                self._save_energy_threshold()
                logging.info(
                    "웨이크워드 캘리브레이션 완료 (energy_threshold=%.1f)",
                    self.recognizer.energy_threshold,
                )
            audio = self.recognizer.listen(source, timeout=2, phrase_time_limit=2)
            if not should_transcribe_wake_audio(audio, self.recognizer.energy_threshold):
                logging.debug("[WakeWord] 길이/에너지 게이트에서 오디오 구간을 제외했습니다")
                return False
            text = self._transcribe(audio)
            if not text:
                return False
            logging.debug("들은 내용 (%d자)", len(text))

            for wake_word in self.wake_words:
                if self._matches_wake_word(text, wake_word):
                    if detection_allowed is not None and not detection_allowed():
                        logging.debug("[WakeWord] TTS 재생/보호 구간 중 감지 후보 무시")
                        return False
                    return True
            return False

        except sr.WaitTimeoutError:
            return False
        except sr.UnknownValueError:
            return False
        except Exception as e:
            logging.debug(f"음성 감지 오류: {e}")
            return False

    @property
    def stt_calls_per_hour(self):
        cutoff = time.monotonic() - 3600
        while self._stt_call_times and self._stt_call_times[0] <= cutoff:
            self._stt_call_times.popleft()
        return len(self._stt_call_times)

    def _transcribe(self, audio):
        if self._stt is None:
            return None
        self._stt_call_times.append(time.monotonic())
        return self._stt.transcribe(audio)

    def _log_stt_call_rate(self):
        now = time.monotonic()
        if now - self._last_stt_metric_log < 60:
            return
        self._last_stt_metric_log = now
        logging.info("[WakeWord] stt_calls_per_hour=%d", self.stt_calls_per_hour)

    def _save_energy_threshold(self) -> None:
        energy_threshold = int(self.recognizer.energy_threshold)
        if energy_threshold == self._pending_energy_threshold:
            return
        if energy_threshold == self._saved_energy_threshold:
            self._pending_energy_threshold = None
            self._pending_energy_since = None
            return
        self._pending_energy_threshold = energy_threshold
        self._pending_energy_since = time.monotonic()

    def _flush_pending_energy_threshold(self, force=False) -> None:
        energy_threshold = self._pending_energy_threshold
        if energy_threshold is None:
            return
        if not force and time.monotonic() - self._pending_energy_since < _ENERGY_SAVE_DELAY_SECONDS:
            return
        if ConfigManager.set_value("stt_energy_threshold", energy_threshold):
            self._configured_energy_threshold = energy_threshold
            self._saved_energy_threshold = energy_threshold
            self._pending_energy_threshold = None
            self._pending_energy_since = None
        else:
            logging.debug("STT 임계값 저장 실패: %s", energy_threshold)

    def flush_pending_settings(self) -> None:
        """종료 시 대기 중인 임계값을 저장한다."""
        self._flush_pending_energy_threshold(force=True)

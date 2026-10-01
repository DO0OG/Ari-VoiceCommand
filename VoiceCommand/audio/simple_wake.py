"""
간단한 음성 트리거 (계정 불필요)
"""
import logging
import math
import re
import struct
import time
import unicodedata
from collections import deque

import speech_recognition as sr

from core.config_manager import ConfigManager
from core.stt_provider import create_stt_provider


_NORMALIZE_WHITESPACE_RE = re.compile(r"\s+")
_WAKE_MIN_AUDIO_SECONDS = 0.3
_WAKE_MAX_AUDIO_SECONDS = 4.0
_SHORT_WAKE_WORD_MAX_LENGTH = 3
_SHORT_WAKE_WORD_EDIT_DISTANCE = 1
_LONG_WAKE_WORD_EDIT_DISTANCE = 2


def _edit_distance(left, right, max_distance):
    if abs(len(left) - len(right)) > max_distance:
        return max_distance + 1

    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        if min(current) > max_distance:
            return max_distance + 1
        previous = current
    return previous[-1]


def _is_text_separator(char):
    category = unicodedata.category(char)
    return char.isspace() or category[0] in ("P", "Z")


def _is_kana(char):
    codepoint = ord(char)
    return 0x3040 <= codepoint <= 0x30FF or 0x31F0 <= codepoint <= 0x31FF


def _is_japanese_prefix_boundary(text, boundary, wake_word):
    normalized_wake_word = unicodedata.normalize("NFKC", wake_word or "")
    if not any(_is_kana(char) for char in normalized_wake_word):
        return False
    next_char = text[boundary]
    return (
        _is_kana(text[boundary - 1])
        and unicodedata.category(next_char)[0] in ("L", "N")
    )


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
    def __init__(self, wake_words=None, stt_provider=None, provider_signature=None):
        self.wake_words = list(wake_words or ["아리야", "시작"])
        self.detected_command = None
        self.recognizer = sr.Recognizer()
        self.should_stop = False
        self._calibrated = False  # 첫 listen 시 lazy 캘리브레이션
        self._configured_energy_threshold = None
        self._stt_call_times = deque()
        self._last_stt_metric_log = time.monotonic()
        self._provider_signature = provider_signature
        self._stt = stt_provider
        self.refresh_settings(initialize_provider=False)

    def refresh_settings(self, initialize_provider=True):
        settings = ConfigManager.load_settings()
        self.wake_words = list(settings.get("wake_words", self.wake_words) or ["아리야", "시작"])
        energy_threshold = int(settings.get("stt_energy_threshold", 300))
        dynamic_energy = bool(settings.get("stt_dynamic_energy", False))
        if energy_threshold != self._configured_energy_threshold or not dynamic_energy:
            self.recognizer.energy_threshold = energy_threshold
            self._configured_energy_threshold = energy_threshold
        if dynamic_energy != self.recognizer.dynamic_energy_threshold:
            self.recognizer.dynamic_energy_threshold = dynamic_energy
            self._calibrated = False
        pause_threshold = max(0.0, float(settings.get("wake_pause_threshold", 0.4)))
        self.recognizer.pause_threshold = pause_threshold
        self.recognizer.non_speaking_duration = min(
            self.recognizer.non_speaking_duration,
            pause_threshold,
        )

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
        if needs_refresh and initialize_provider:
            self._provider_signature = signature
            self._stt = create_stt_provider(settings)
            self._calibrated = False
            logging.info("[WakeWord] STT 프로바이더 갱신: %s", signature[0])
        elif self._stt is not None and self._provider_signature is None:
            self._provider_signature = signature

    def _normalize_text(self, text):
        normalized = unicodedata.normalize("NFKC", text or "").casefold()
        normalized_chars = []
        for char in normalized:
            codepoint = ord(char)
            if 0x30A1 <= codepoint <= 0x30F6 or codepoint in (0x30FD, 0x30FE):
                char = chr(codepoint - 0x60)
            category = unicodedata.category(char)
            if char.isspace() or category[0] in ("P", "Z"):
                normalized_chars.append(" ")
            elif category[0] in ("L", "N", "M"):
                normalized_chars.append(char)
        normalized = _NORMALIZE_WHITESPACE_RE.sub(" ", "".join(normalized_chars))
        return normalized.strip()

    def _wake_word_distance(self, text, wake_word):
        normalized_text = self._normalize_text(text).replace(" ", "")
        normalized_wake_word = self._normalize_text(wake_word).replace(" ", "")
        if not normalized_text or not normalized_wake_word:
            return None

        has_hangul = any("\uac00" <= char <= "\ud7a3" for char in normalized_wake_word)
        if has_hangul:
            wake_length = sum(
                "\uac00" <= char <= "\ud7a3" for char in normalized_wake_word
            )
        else:
            wake_length = len(normalized_wake_word)
        max_distance = (
            _SHORT_WAKE_WORD_EDIT_DISTANCE
            if wake_length <= _SHORT_WAKE_WORD_MAX_LENGTH
            else _LONG_WAKE_WORD_EDIT_DISTANCE
        )
        if has_hangul:
            normalized_text = unicodedata.normalize("NFD", normalized_text)
            normalized_wake_word = unicodedata.normalize("NFD", normalized_wake_word)
        distance = _edit_distance(normalized_text, normalized_wake_word, max_distance)
        return distance, max_distance

    def _matches_wake_word(self, text, wake_word):
        distance = self._wake_word_distance(text, wake_word)
        return distance is not None and distance[0] <= distance[1]

    def _command_after_wake_word(self, text, wake_word):
        best_match = None
        best_rank = None
        for boundary in range(1, len(text)):
            has_separator = _is_text_separator(text[boundary])
            if not has_separator and not _is_japanese_prefix_boundary(
                text, boundary, wake_word
            ):
                continue
            command_start = boundary + int(has_separator)
            while command_start < len(text) and _is_text_separator(text[command_start]):
                command_start += 1
            command = text[command_start:].strip()
            if not command or not self._normalize_text(command):
                continue

            distance = self._wake_word_distance(text[:boundary], wake_word)
            if distance is None or distance[0] > distance[1]:
                continue
            if (
                not has_separator
                and _is_kana(text[boundary])
                and len(self._normalize_text(text[:boundary]).replace(" ", ""))
                != len(self._normalize_text(wake_word).replace(" ", ""))
            ):
                continue
            rank = (distance[0], boundary)
            if best_rank is None or rank < best_rank:
                best_match = command
                best_rank = rank
        return best_match

    def recalibrate(self, source):
        """TTS 이후 환경 변화 시 임계값 재조정"""
        self.refresh_settings(initialize_provider=False)
        if not self.recognizer.dynamic_energy_threshold:
            return
        try:
            self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            logging.debug(f"재캘리브레이션 완료 (energy_threshold={self.recognizer.energy_threshold:.1f})")
        except Exception as e:
            logging.debug(f"재캘리브레이션 실패: {e}")

    def listen_for_wake_word(self, source, detection_allowed=None, interrupt_event=None):
        """웨이크워드 대기 — 첫 호출 시 캘리브레이션, 이후 즉시 청취"""
        self.detected_command = None
        if self.should_stop:
            return False
        try:
            self._log_stt_call_rate()
            self.refresh_settings()
            if not self._calibrated:
                if self.recognizer.dynamic_energy_threshold:
                    self.recognizer.adjust_for_ambient_noise(source, duration=1.0)
                self._calibrated = True
            original_stream = None
            if interrupt_event is not None:
                original_stream = source.stream
                source.stream = _WakeListenStream(original_stream, interrupt_event)
            gate_energy_threshold = self.recognizer.energy_threshold
            try:
                audio = self.recognizer.listen(
                    source,
                    timeout=2,
                    phrase_time_limit=_WAKE_MAX_AUDIO_SECONDS,
                )
            finally:
                if original_stream is not None:
                    source.stream = original_stream
            if interrupt_event is not None and interrupt_event.is_set():
                return False
            # 자동 임계값이 높아져도 수동 설정값보다 강한 게이트가 되지 않게 한다.
            gate_energy_threshold = min(
                gate_energy_threshold,
                self.recognizer.energy_threshold,
                self._configured_energy_threshold,
            )
            if not should_transcribe_wake_audio(audio, gate_energy_threshold):
                logging.debug("[WakeWord] 길이/에너지 게이트에서 오디오 구간을 제외했습니다")
                return False
            text = self._transcribe(audio)
            if not text:
                return False
            logging.debug("들은 내용 (%d자)", len(text))

            for wake_word in self.wake_words:
                command = self._command_after_wake_word(text, wake_word)
                if command is not None or self._matches_wake_word(text, wake_word):
                    if detection_allowed is not None and not detection_allowed():
                        logging.debug("[WakeWord] TTS 재생/보호 구간 중 감지 후보 무시")
                        return False
                    self.detected_command = command
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
        return self._stt.transcribe(audio, mode="wake")

    def _log_stt_call_rate(self):
        now = time.monotonic()
        if now - self._last_stt_metric_log < 60:
            return
        self._last_stt_metric_log = now
        logging.info("[WakeWord] stt_calls_per_hour=%d", self.stt_calls_per_hour)

class _WakeListenStream:
    def __init__(self, stream, interrupt_event):
        self._stream = stream
        self._interrupt_event = interrupt_event

    def read(self, size):
        if self._interrupt_event.is_set():
            raise sr.WaitTimeoutError("웨이크워드 듣기가 취소되었습니다.")
        audio = self._stream.read(size)
        if self._interrupt_event.is_set():
            raise sr.WaitTimeoutError("웨이크워드 듣기가 취소되었습니다.")
        return audio

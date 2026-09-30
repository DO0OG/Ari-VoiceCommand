"""
Microsoft Edge TTS 제공자 — 무료, API 키 불필요
문장 단위로 합성하고, 앞 문장을 재생하는 동안 다음 문장을 합성한다.
Fish Audio / CosyVoice3와 동일한 인터페이스: speak() / playback_finished / cleanup()
"""

import asyncio
import logging
import math
import queue
import re
import threading
import time

import pyaudio
from PySide6.QtCore import QObject, Signal

from audio.audio_manager import GlobalAudio, get_audio_output_lock
from core.emotions import DEFAULT_EMOTION, get_emotion_details
from tts.pcm_playback import write_pcm_chunks
from tts.tts_cache import DEFAULT_MAX_BYTES, DiskTTSAudioCache, build_tts_cache_key

KO_VOICES = [
    ("ko-KR-SunHiNeural", "SunHi (여성, 기본)"),
    ("ko-KR-InJoonNeural", "InJoon (남성)"),
    ("ko-KR-HyunsuNeural", "Hyunsu (남성, 다중감정)"),
]
DEFAULT_VOICE = "ko-KR-SunHiNeural"
_SAMPLE_RATE = 22050
_SENTENCE_TIMEOUT_SECONDS = 10.0
_SENTENCE_ENDINGS = frozenset(".!?。！？…")
_CLOSING_PUNCTUATION = frozenset("\"'”’»』」】）)]}〉》")
_COMMON_ABBREVIATIONS = frozenset(
    {"dr.", "e.g.", "i.e.", "jr.", "mr.", "mrs.", "ms.", "prof.", "sr.", "u.s.", "vs."}
)
_RATE_PATTERN = re.compile(r"^([+-]?\d+)%$")
_MIN_RATE_PERCENT = -50
_MAX_RATE_PERCENT = 100


def _is_cjk_or_hangul(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x3040 <= codepoint <= 0x30FF
        or 0x3400 <= codepoint <= 0x9FFF
        or 0xAC00 <= codepoint <= 0xD7AF
    )


def _is_abbreviation_period(text: str, period_index: int) -> bool:
    if text[period_index] != ".":
        return False
    if (
        period_index > 0
        and period_index + 1 < len(text)
        and text[period_index - 1].isdigit()
        and text[period_index + 1].isdigit()
    ):
        return True
    match = re.search(r"(?:^|\s)([A-Za-z](?:[A-Za-z.]*)?)$", text[: period_index + 1])
    return bool(match and match.group(1).casefold() in _COMMON_ABBREVIATIONS)


def split_sentences(text: str) -> list[str]:
    """Split spoken text into sentence-sized chunks while preserving punctuation."""
    text = str(text or "").strip()
    if not text:
        return []

    sentences = []
    start = 0
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\n":
            sentence = text[start:index].strip()
            if sentence:
                sentences.append(sentence)
            start = index + 1
            while start < len(text) and text[start].isspace():
                start += 1
            index = start
            continue

        if character not in _SENTENCE_ENDINGS or _is_abbreviation_period(text, index):
            index += 1
            continue

        end = index + 1
        while end < len(text) and (
            text[end] in _SENTENCE_ENDINGS or text[end] in _CLOSING_PUNCTUATION
        ):
            end += 1
        next_character = end
        while next_character < len(text) and text[next_character].isspace():
            next_character += 1

        if (
            next_character == len(text)
            or next_character > end
            or _is_cjk_or_hangul(text[next_character])
        ):
            sentence = text[start:end].strip()
            if sentence:
                sentences.append(sentence)
            start = next_character
            index = start
        else:
            index = end

    remainder = text[start:].strip()
    if remainder:
        sentences.append(remainder)
    return sentences


class EdgeTTS(QObject):
    playback_finished = Signal()

    def __init__(
        self,
        voice=DEFAULT_VOICE,
        rate="+0%",
        volume="+0%",
        synthesis_timeout_seconds=_SENTENCE_TIMEOUT_SECONDS,
        cache_max_bytes=DEFAULT_MAX_BYTES,
        audio_cache=None,
        emotion_enabled=True,
        tts_volume=1.0,
    ):
        super().__init__()
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.tts_volume = tts_volume
        self.emotion_enabled = bool(emotion_enabled)
        try:
            timeout = float(synthesis_timeout_seconds)
        except (TypeError, ValueError):
            timeout = _SENTENCE_TIMEOUT_SECONDS
        if not math.isfinite(timeout):
            timeout = _SENTENCE_TIMEOUT_SECONDS
        self.synthesis_timeout_seconds = max(0.1, timeout)
        self.is_playing = False
        try:
            cache_limit = int(cache_max_bytes)
        except (OverflowError, TypeError, ValueError):
            cache_limit = DEFAULT_MAX_BYTES
        self._audio_cache = (
            audio_cache
            if audio_cache is not None
            else DiskTTSAudioCache(max_bytes=cache_limit)
        )
        self._state_lock = threading.Lock()
        self._active_stop_event = None
        self._playback_thread = None
        self._speak_finished = threading.Event()
        self._speak_finished.set()
        self._closed = False
        self._cache_warmup_idle_check = None
        self._cache_warmup_cancel = threading.Event()
        self._language_change_callback = self._on_language_changed
        self._language_callback_registered = False
        logging.info("Edge TTS 초기화 완료 (voice=%s)", voice)

    @staticmethod
    def _fixed_message_texts() -> frozenset[str]:
        from commands.ai_fast_path import FastPathMixin
        from core.constants import get_wake_responses
        from i18n.translator import gettext_func

        fast_path_messages = (
            gettext_func(message)
            for message in FastPathMixin._FAST_PATH_MESSAGES.values()
        )
        instant_ack_messages = (
            gettext_func(message)
            for phrases in FastPathMixin._INSTANT_ACK_RESPONSE_POOL.values()
            for message in phrases
        )
        return frozenset(
            (*get_wake_responses(), *fast_path_messages, *instant_ack_messages)
        )

    def _prosody(self, emotion: str) -> tuple[str, str]:
        details = get_emotion_details(emotion)
        rate_offset = details["edge_rate"] if self.emotion_enabled else 0
        pitch_offset = details["edge_pitch"] if self.emotion_enabled else 0
        match = _RATE_PATTERN.fullmatch(str(self.rate).strip())
        rate = self.rate
        if match and rate_offset:
            value = int(match.group(1)) + rate_offset
            value = max(_MIN_RATE_PERCENT, min(_MAX_RATE_PERCENT, value))
            rate = f"{value:+d}%"
        pitch = f"{pitch_offset:+d}Hz"
        return rate, pitch

    def _cache_key(self, text: str, emotion: str, language: str) -> str:
        rate, pitch = self._prosody(emotion)
        return build_tts_cache_key(
            "edge", self.voice, rate, self.volume, emotion, language, text,
            pitch=pitch,
        )

    async def _synthesize(self, text: str, emotion: str = DEFAULT_EMOTION) -> bytes:
        import edge_tts

        rate, pitch = self._prosody(emotion)
        communicate = edge_tts.Communicate(
            text, self.voice, rate=rate, volume=self.volume, pitch=pitch
        )
        chunks = []
        async for item in communicate.stream():
            if item["type"] == "audio":
                chunks.append(item["data"])
        return b"".join(chunks) if chunks else b""

    @staticmethod
    async def _wait_for_stop(stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            await asyncio.sleep(0.05)

    async def _synthesize_with_timeout(self, text, emotion, stop_event):
        synthesis = asyncio.create_task(self._synthesize(text, emotion))
        stop_watcher = asyncio.create_task(self._wait_for_stop(stop_event))
        try:
            done, _pending = await asyncio.wait(
                (synthesis, stop_watcher),
                timeout=self.synthesis_timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_watcher in done and stop_event.is_set():
                return None
            if synthesis in done:
                return synthesis.result()
            raise asyncio.TimeoutError
        finally:
            for task in (synthesis, stop_watcher):
                if not task.done():
                    task.cancel()
            await asyncio.gather(synthesis, stop_watcher, return_exceptions=True)

    def _synthesize_pcm(
        self,
        loop,
        text: str,
        emotion: str,
        cacheable_messages: frozenset[str],
        language: str,
        stop_event: threading.Event,
    ) -> bytes | None:
        if stop_event.is_set():
            return None

        cacheable = text in cacheable_messages
        cache_key = self._cache_key(text, emotion, language) if cacheable else None
        if cache_key is not None:
            cached_pcm = self._audio_cache.get(cache_key)
            if cached_pcm is not None:
                logging.debug("Edge TTS 고정 문구 캐시 적중")
                return cached_pcm

        audio_data = loop.run_until_complete(
            self._synthesize_with_timeout(text, emotion, stop_event)
        )
        if not audio_data or stop_event.is_set():
            return None

        from audio.mp3_decoder import decode_mp3_to_pcm

        pcm = decode_mp3_to_pcm(audio_data, _SAMPLE_RATE)
        if cache_key is not None and pcm and not stop_event.is_set():
            self._audio_cache.put(cache_key, pcm)
        return pcm

    @staticmethod
    def _put_synthesis_result(result_queue, result, stop_event) -> bool:
        while not stop_event.is_set():
            try:
                result_queue.put(result, timeout=0.05)
                return True
            except queue.Full:
                continue
        return False

    def _synthesize_sentences(
        self,
        sentences: list[str],
        emotion: str,
        cacheable_messages: frozenset[str],
        language: str,
        stop_event: threading.Event,
        result_queue,
    ) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            for index, sentence in enumerate(sentences, start=1):
                if stop_event.is_set():
                    break
                try:
                    pcm = self._synthesize_pcm(
                        loop,
                        sentence,
                        emotion,
                        cacheable_messages,
                        language,
                        stop_event,
                    )
                except asyncio.TimeoutError:
                    logging.warning(
                        "Edge TTS 문장 합성 타임아웃 (%d/%d)", index, len(sentences)
                    )
                    continue
                except Exception as exc:
                    logging.warning(
                        "Edge TTS 문장 합성 실패 (%d/%d): %s",
                        index,
                        len(sentences),
                        type(exc).__name__,
                    )
                    continue

                if pcm and not self._put_synthesis_result(
                    result_queue, pcm, stop_event
                ):
                    break
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                asyncio.set_event_loop(None)
                loop.close()
            self._put_synthesis_result(result_queue, None, stop_event)

    @staticmethod
    def _write_pcm_chunks(
        stream, pcm: bytes, stop_event: threading.Event, volume: float = 1.0
    ) -> bool:
        return write_pcm_chunks(
            stream, pcm, stop_event, _SAMPLE_RATE, volume=volume
        )

    def _create_output_stream(self):
        from audio.audio_manager import get_output_device_index

        return GlobalAudio.open_stream(
            format=pyaudio.paInt16,
            channels=1,
            rate=_SAMPLE_RATE,
            output=True,
            output_device_index=get_output_device_index(),
        )

    def speak(
        self,
        text: str,
        emotion: str = "평온",
        stop_event: threading.Event | None = None,
    ) -> bool:
        sentences = split_sentences(text)
        if not sentences:
            return False

        stop_event = stop_event or threading.Event()
        with self._state_lock:
            if self._closed:
                return False
            self._active_stop_event = stop_event
            self._playback_thread = threading.current_thread()
            self.is_playing = True
            self._speak_finished.clear()
            self._cache_warmup_cancel.set()

        started_at = time.monotonic()
        result_queue = queue.Queue(maxsize=1)
        synthesis_stop_event = threading.Event()
        try:
            from i18n.translator import get_language

            language = get_language()
            cacheable_messages = self._fixed_message_texts()
        except (ImportError, RuntimeError, TypeError, ValueError) as exc:
            logging.warning("Edge TTS 문구 캐시 준비 실패: %s", exc)
            language = "ko"
            cacheable_messages = frozenset()

        producer = threading.Thread(
            target=self._synthesize_sentences,
            args=(
                sentences,
                emotion,
                cacheable_messages,
                language,
                synthesis_stop_event,
                result_queue,
            ),
            name="EdgeTTS-Synthesis",
            daemon=True,
        )
        if not stop_event.is_set():
            producer.start()

        stream = None
        played_audio = False
        success = True
        try:
            while not stop_event.is_set():
                try:
                    pcm = result_queue.get(timeout=0.1)
                except queue.Empty:
                    if not producer.is_alive():
                        break
                    continue
                if pcm is None:
                    break
                if stream is None:
                    stream = self._create_output_stream()
                if not self._write_pcm_chunks(
                    stream, pcm, stop_event, volume=self.tts_volume
                ):
                    success = False
                    break
                played_audio = True
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logging.error("Edge TTS 오디오 재생 실패: %s", exc)
            success = False
        finally:
            if stop_event.is_set():
                success = False
            synthesis_stop_event.set()
            if stream is not None:
                with get_audio_output_lock():
                    GlobalAudio.close_stream(stream)
            if producer.is_alive():
                producer.join(timeout=0.2)
            with self._state_lock:
                if self._active_stop_event is stop_event:
                    self._active_stop_event = None
                self._playback_thread = None
                self.is_playing = False
                self._speak_finished.set()
            self.playback_finished.emit()

        if played_audio and success:
            logging.info(
                "[TTS] Edge TTS 전체 완료: %.2fs, %d문장",
                time.monotonic() - started_at,
                len(sentences),
            )
            self._restart_cache_warmup()
            return True

        self._restart_cache_warmup()
        return False

    def speak_cached(
        self,
        text: str,
        emotion: str = DEFAULT_EMOTION,
        request_cancel_event: threading.Event | None = None,
    ) -> bool:
        """캐시된 고정 문구만 재생하고 합성 요청은 하지 않는다."""
        if not text or (
            request_cancel_event is not None and request_cancel_event.is_set()
        ):
            return False
        from i18n.translator import get_language

        pcm = self._audio_cache.get(self._cache_key(text, emotion, get_language()))
        if pcm is None:
            return False

        stop_event = threading.Event()
        with self._state_lock:
            if (
                self._closed
                or self.is_playing
                or (
                    request_cancel_event is not None
                    and request_cancel_event.is_set()
                )
            ):
                return False
            self._active_stop_event = stop_event
            self._playback_thread = threading.current_thread()
            self.is_playing = True
            self._speak_finished.clear()

        stream = None
        try:
            if stop_event.is_set():
                return False
            stream = self._create_output_stream()
            return self._write_pcm_chunks(
                stream, pcm, stop_event, volume=self.tts_volume
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logging.warning("Edge TTS 캐시 재생 실패: %s", type(exc).__name__)
            return False
        finally:
            if stream is not None:
                try:
                    with get_audio_output_lock():
                        GlobalAudio.close_stream(stream)
                except (OSError, RuntimeError, TypeError, ValueError) as exc:
                    logging.debug("Edge TTS 캐시 스트림 정리 실패: %s", type(exc).__name__)
            with self._state_lock:
                if self._active_stop_event is stop_event:
                    self._active_stop_event = None
                self._playback_thread = None
                self.is_playing = False
                self._speak_finished.set()
            self.playback_finished.emit()

    def schedule_fixed_message_cache_warmup(self, is_idle=None) -> None:
        if self._closed:
            return
        if not self._language_callback_registered:
            from i18n.translator import on_language_changed

            on_language_changed(self._language_change_callback)
            self._language_callback_registered = True
        if is_idle is not None:
            self._cache_warmup_idle_check = is_idle
        if self._cache_warmup_idle_check is None:
            self._cache_warmup_idle_check = lambda: not self.is_playing
        self._cache_warmup_cancel.set()
        cancel_event = threading.Event()
        self._cache_warmup_cancel = cancel_event
        worker = threading.Thread(
            target=self._warm_fixed_message_cache,
            args=(cancel_event, self._cache_warmup_idle_check),
            name="EdgeTTS-CacheWarmup",
            daemon=True,
        )
        worker.start()

    def _restart_cache_warmup(self) -> None:
        if self._cache_warmup_idle_check is not None and not self._closed:
            self.schedule_fixed_message_cache_warmup(
                self._cache_warmup_idle_check
            )

    def _on_language_changed(self) -> None:
        self._restart_cache_warmup()

    def _warm_fixed_message_cache(self, cancel_event, is_idle) -> None:
        if cancel_event.wait(2.0):
            return
        while not cancel_event.is_set():
            try:
                if is_idle():
                    break
            except (AttributeError, RuntimeError, TypeError):
                if not self.is_playing:
                    break
            cancel_event.wait(0.25)
        if cancel_event.is_set():
            return

        from i18n.translator import get_language

        language = get_language()
        messages = self._fixed_message_texts()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            for message in messages:
                if cancel_event.is_set() or self._closed:
                    break
                while not cancel_event.is_set() and not self._closed:
                    try:
                        if is_idle():
                            break
                    except (AttributeError, RuntimeError, TypeError):
                        if not self.is_playing:
                            break
                    cancel_event.wait(0.25)
                if cancel_event.is_set() or self._closed:
                    break
                key = self._cache_key(message, DEFAULT_EMOTION, language)
                if self._audio_cache.get(key) is not None:
                    continue
                try:
                    self._synthesize_pcm(
                        loop,
                        message,
                        DEFAULT_EMOTION,
                        messages,
                        language,
                        cancel_event,
                    )
                except asyncio.TimeoutError:
                    logging.debug("Edge TTS 고정 문구 캐시 사전 합성 시간 초과")
                except Exception as exc:
                    logging.debug("Edge TTS 고정 문구 캐시 사전 합성 실패: %s", exc)
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                asyncio.set_event_loop(None)
                loop.close()

    def stop(self) -> None:
        with self._state_lock:
            stop_event = self._active_stop_event
        if stop_event is not None:
            stop_event.set()

    def cleanup(self):
        with self._state_lock:
            self._closed = True
            stop_event = self._active_stop_event
        self._cache_warmup_cancel.set()
        if self._language_callback_registered:
            from i18n.translator import remove_language_changed_callback

            remove_language_changed_callback(self._language_change_callback)
        if stop_event is not None:
            stop_event.set()
            if threading.current_thread() is not self._playback_thread:
                self._speak_finished.wait(timeout=2.0)
        # 전역 PyAudio 인스턴스는 AriCore.cleanup()의 GlobalAudio.terminate()에서만 종료한다.

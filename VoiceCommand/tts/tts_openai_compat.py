"""OpenAI 호환 TTS 서버 제공자."""

import array
import base64
from io import BytesIO
import importlib
import logging
import os
import sys
import threading
import time
import wave

import pyaudio
from PySide6.QtCore import QObject, Signal

from audio.audio_manager import GlobalAudio, get_audio_output_lock
from core.emotions import DEFAULT_EMOTION, get_emotion_instruction
from i18n.translator import get_language
from tts.pcm_playback import write_pcm_chunks

_MAX_REFERENCE_BYTES = 5 * 1024 * 1024
_REQUEST_TIMEOUT_SECONDS = 30


def _parse_wav(wav_data: bytes) -> tuple[int, bytes]:
    """WAV를 모노 int16 PCM과 샘플레이트로 변환한다."""
    try:
        with wave.open(BytesIO(wav_data), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            sample_width = wav_file.getsampwidth()
            frame_count = wav_file.getnframes()
            if channels not in (1, 2):
                raise ValueError("WAV must have one or two channels")
            if sample_width != 2:
                raise ValueError("WAV must use 16-bit samples")
            if sample_rate <= 0:
                raise ValueError("WAV sample rate must be positive")
            if wav_file.getcomptype() != "NONE":
                raise ValueError("WAV must use uncompressed PCM")
            frames = wav_file.readframes(frame_count)
    except (wave.Error, EOFError) as exc:
        raise ValueError("Invalid WAV response") from exc

    expected_bytes = frame_count * channels * sample_width
    if len(frames) != expected_bytes:
        raise ValueError("WAV response is incomplete")

    samples = array.array("h")
    samples.frombytes(frames)
    if samples.itemsize != 2:
        raise ValueError("This platform does not support int16 samples")
    if sys.byteorder != "little":
        samples.byteswap()

    if channels == 2:
        mono = array.array("h")
        mono.extend(
            int((samples[index] + samples[index + 1]) / 2)
            for index in range(0, len(samples), 2)
        )
        samples = mono

    return sample_rate, samples.tobytes()


class OpenAICompatTTS(QObject):
    playback_finished = Signal()

    def __init__(
        self,
        base_url="",
        api_key="",
        model="",
        voice="",
        clone_mode="none",
        emotion_mode="instructions",
        reference_wav="",
        reference_text="",
        emotion_enabled=True,
        language=None,
        tts_volume=1.0,
    ):
        super().__init__()
        if not base_url or not str(base_url).strip():
            raise ValueError("OpenAI-compatible TTS base URL is missing")
        if clone_mode not in ("none", "ref_audio"):
            raise ValueError("Unsupported OpenAI-compatible TTS clone mode")
        if emotion_mode not in ("instructions", "none"):
            raise ValueError("Unsupported OpenAI-compatible TTS emotion mode")

        self.model = model
        self.voice = voice
        self.clone_mode = clone_mode
        self.emotion_mode = emotion_mode
        self._api_key = str(api_key or "")
        self.reference_wav = reference_wav
        self.reference_text = reference_text
        self.emotion_enabled = bool(emotion_enabled)
        self.language = language
        self.tts_volume = tts_volume
        self.is_playing = False
        self._state_lock = threading.Lock()
        self._active_stop_event = None

        try:
            openai_module = importlib.import_module("openai")
            self._client = openai_module.OpenAI(
                base_url=base_url,
                api_key=api_key or "not-needed",
                max_retries=0,
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
        except (ImportError, AttributeError, TypeError, ValueError) as exc:
            logging.error("OpenAI-compatible TTS client initialization failed")
            raise RuntimeError("OpenAI-compatible TTS client initialization failed") from exc

    def _reference_audio(self) -> str:
        if not self.reference_wav:
            raise ValueError("Reference WAV is not configured")
        if os.path.getsize(self.reference_wav) > _MAX_REFERENCE_BYTES:
            raise ValueError("Reference WAV exceeds the 5 MiB limit")
        with open(self.reference_wav, "rb") as reference_file:
            audio = reference_file.read(_MAX_REFERENCE_BYTES + 1)
        if len(audio) > _MAX_REFERENCE_BYTES:
            raise ValueError("Reference WAV exceeds the 5 MiB limit")
        encoded = base64.b64encode(audio).decode("ascii")
        return f"data:audio/wav;base64,{encoded}"

    def _speech_options(self, text: str, emotion: str) -> dict:
        # openai SDK는 voice를 필수 인자로 받으므로 복제 모드에서도 항상 넘긴다.
        options = {
            "model": self.model,
            "voice": self.voice,
            "input": text,
            "response_format": "wav",
        }
        if self.clone_mode == "ref_audio":
            options["extra_body"] = {
                "ref_audio": self._reference_audio(),
                "ref_text": self.reference_text,
                "task_type": "Base",
            }
        if self.emotion_enabled and self.emotion_mode == "instructions":
            language = self.language
            if language is None:
                language = get_language()
            options["instructions"] = get_emotion_instruction(emotion, language)
        return options

    def speak(
        self,
        text: str,
        emotion: str = DEFAULT_EMOTION,
        stop_event: threading.Event | None = None,
    ) -> bool:
        if not text:
            return False

        stop_event = stop_event or threading.Event()
        with self._state_lock:
            self._active_stop_event = stop_event
            self.is_playing = True

        try:
            started_at = time.time()
            if stop_event.is_set():
                return False
            response = self._client.audio.speech.create(**self._speech_options(text, emotion))
            if stop_event.is_set():
                return False
            sample_rate, pcm = _parse_wav(response.content)

            from audio.audio_manager import get_output_device_index
            if stop_event.is_set():
                return False
            stream = GlobalAudio.open_stream(
                format=pyaudio.paInt16,
                channels=1,
                rate=sample_rate,
                output=True,
                output_device_index=get_output_device_index(),
            )
            try:
                success = write_pcm_chunks(
                    stream, pcm, stop_event, sample_rate, volume=self.tts_volume
                )
            finally:
                with get_audio_output_lock():
                    GlobalAudio.close_stream(stream)

            if success:
                logging.info(
                    "[TTS] OpenAI-compatible TTS completed in %.2fs",
                    time.time() - started_at,
                )
            return success
        except Exception as exc:
            if not stop_event.is_set():
                detail = str(exc)
                if self._api_key:
                    detail = detail.replace(self._api_key, "[redacted]")
                logging.error("OpenAI-compatible TTS request failed: %s", detail)
            return False
        finally:
            with self._state_lock:
                if self._active_stop_event is stop_event:
                    self._active_stop_event = None
                    self.is_playing = False
            self.playback_finished.emit()

    def stop(self) -> None:
        with self._state_lock:
            stop_event = self._active_stop_event
        if stop_event is not None:
            stop_event.set()

    def cleanup(self) -> None:
        client = getattr(self, "_client", None)
        close = getattr(client, "close", None)
        if close is not None:
            close()

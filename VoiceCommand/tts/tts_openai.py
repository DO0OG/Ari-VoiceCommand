"""
OpenAI TTS 제공자 — tts-1 / tts-1-hd
response_format="pcm" → 24kHz mono int16 raw PCM (변환 없이 즉시 재생)
Fish Audio / CosyVoice3와 동일한 인터페이스: speak() / playback_finished / cleanup()
"""
import importlib
import logging
import threading
import time

import pyaudio
from PySide6.QtCore import QObject, Signal

from audio.audio_manager import GlobalAudio, get_audio_output_lock
from core.emotions import DEFAULT_EMOTION, get_emotion_details
from tts.pcm_playback import write_pcm_chunks

VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
MODELS = ["tts-1", "tts-1-hd", "gpt-4o-mini-tts"]
_SAMPLE_RATE = 24000  # OpenAI PCM 출력 고정값


class OpenAITTS(QObject):
    playback_finished = Signal()

    def __init__(
        self, api_key="", voice="nova", model="tts-1", speed=1.0,
        emotion_enabled=True, custom_voice_id="",
    ):
        super().__init__()
        self.voice = {"id": custom_voice_id} if custom_voice_id else voice
        self.model = model
        self.speed = max(0.25, min(4.0, speed))  # OpenAI 허용 범위
        self.emotion_enabled = bool(emotion_enabled)
        self.is_playing = False
        self._client = None
        self._state_lock = threading.Lock()
        self._active_stop_event = None

        if not api_key:
            raise ValueError("OpenAI TTS API key is missing")

        try:
            openai_module = importlib.import_module("openai")
            self._client = openai_module.OpenAI(api_key=api_key)
            logging.info("OpenAI TTS 초기화 완료 (voice=%s, model=%s)", voice, model)
        except Exception as e:
            logging.error("OpenAI TTS 초기화 실패: %s", e)
            raise RuntimeError("OpenAI TTS client initialization failed") from e

    def speak(
        self,
        text: str,
        emotion: str = DEFAULT_EMOTION,
        stop_event: threading.Event | None = None,
    ) -> bool:
        if not text or self._client is None:
            return False

        stop_event = stop_event or threading.Event()
        with self._state_lock:
            self._active_stop_event = stop_event
            self.is_playing = True

        try:
            t0 = time.time()
            if stop_event.is_set():
                return False

            # PCM 포맷 요청 → 변환 불필요, 즉시 재생 가능
            options = {
                "model": self.model,
                "voice": self.voice,
                "input": text,
                "response_format": "pcm",
                "speed": self.speed,
            }
            if self.emotion_enabled and self.model.startswith("gpt-4o-mini-tts"):
                options["instructions"] = get_emotion_details(emotion)["openai"]
            response = self._client.audio.speech.create(**options)
            if stop_event.is_set():
                return False
            pcm_data = response.content  # bytes: 24kHz mono int16

            logging.info(
                "[TTS] OpenAI 수신: %.2fs, %s bytes",
                time.time() - t0,
                f"{len(pcm_data):,}",
            )

            from audio.audio_manager import get_output_device_index
            if stop_event.is_set():
                return False
            stream = GlobalAudio.open_stream(
                format=pyaudio.paInt16,
                channels=1,
                rate=_SAMPLE_RATE,
                output=True,
                output_device_index=get_output_device_index(),
            )
            try:
                success = write_pcm_chunks(
                    stream, pcm_data, stop_event, _SAMPLE_RATE
                )
            finally:
                with get_audio_output_lock():
                    GlobalAudio.close_stream(stream)

            if not success:
                return False
            logging.info("[TTS] OpenAI 전체 완료: %.2fs", time.time() - t0)
            return True

        except Exception as exc:
            logging.error("OpenAI TTS speak 오류: %s", exc)
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

    def cleanup(self):
        """재생 상태를 정리한다."""
        # 전역 PyAudio 인스턴스는 AriCore.cleanup()의 GlobalAudio.terminate()에서만 종료한다.
        self.is_playing = False

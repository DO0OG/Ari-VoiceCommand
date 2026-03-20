"""
OpenAI TTS 제공자 — tts-1 / tts-1-hd
response_format="pcm" → 24kHz mono int16 raw PCM (변환 없이 즉시 재생)
Fish Audio / CosyVoice3와 동일한 인터페이스: speak() / playback_finished / cleanup()
"""
import logging
import time

import pyaudio
from PySide6.QtCore import QObject, Signal

VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
MODELS = ["tts-1", "tts-1-hd"]
_SAMPLE_RATE = 24000  # OpenAI PCM 출력 고정값


class OpenAITTS(QObject):
    playback_finished = Signal()

    def __init__(self, api_key="", voice="nova", model="tts-1", speed=1.0):
        super().__init__()
        self.voice = voice
        self.model = model
        self.speed = max(0.25, min(4.0, speed))  # OpenAI 허용 범위
        self.is_playing = False
        self.pa = pyaudio.PyAudio()
        self._client = None

        if api_key:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=api_key)
                logging.info(f"OpenAI TTS 초기화 완료 (voice={voice}, model={model})")
            except Exception as e:
                logging.error(f"OpenAI TTS 초기화 실패: {e}")

    def speak(self, text: str) -> bool:
        if not text or self._client is None:
            return False

        try:
            self.is_playing = True
            t0 = time.time()

            # PCM 포맷 요청 → 변환 불필요, 즉시 재생 가능
            response = self._client.audio.speech.create(
                model=self.model,
                voice=self.voice,
                input=text,
                response_format="pcm",
                speed=self.speed,
            )
            pcm_data = response.content  # bytes: 24kHz mono int16

            logging.info(f"[TTS] OpenAI 수신: {time.time()-t0:.2f}s, {len(pcm_data):,} bytes")

            stream = self.pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=_SAMPLE_RATE,
                output=True,
            )
            stream.write(pcm_data)
            stream.stop_stream()
            stream.close()

            logging.info(f"[TTS] OpenAI 전체 완료: {time.time()-t0:.2f}s")
            self.is_playing = False
            self.playback_finished.emit()
            return True

        except Exception as e:
            logging.error(f"OpenAI TTS speak 오류: {e}")
            self.is_playing = False
            self.playback_finished.emit()
            return False

    def cleanup(self):
        try:
            self.pa.terminate()
        except Exception:
            pass

    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass

"""
ElevenLabs TTS 제공자 — HTTP 스트리밍 API
Fish Audio / CosyVoice3와 동일한 인터페이스: speak() / playback_finished / cleanup()
"""
import io
import logging
import time

import pyaudio
from PySide6.QtCore import QObject, Signal

_DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel (다국어)
_SAMPLE_RATE = 22050


class ElevenLabsTTS(QObject):
    playback_finished = Signal()

    def __init__(self, api_key="", voice_id="",
                 model_id="eleven_multilingual_v2",
                 stability=0.5, similarity_boost=0.75):
        super().__init__()
        self.api_key = api_key
        self.voice_id = voice_id or _DEFAULT_VOICE_ID
        self.model_id = model_id
        self.stability = stability
        self.similarity_boost = similarity_boost
        self.is_playing = False
        self.pa = pyaudio.PyAudio()

        if api_key:
            logging.info(f"ElevenLabs TTS 초기화 완료 (voice_id={self.voice_id})")
        else:
            logging.warning("ElevenLabs API 키가 설정되지 않았습니다.")

    def speak(self, text: str, emotion: str = "평온") -> bool:
        if not text or not self.api_key:
            return False

        try:
            import requests
        except ImportError:
            logging.error("requests 패키지가 필요합니다: pip install requests")
            return False

        try:
            self.is_playing = True
            t0 = time.time()

            url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
            headers = {
                "xi-api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            }
            payload = {
                "text": text,
                "model_id": self.model_id,
                "voice_settings": {
                    "stability": self.stability,
                    "similarity_boost": self.similarity_boost,
                },
            }

            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()

            logging.info(f"[TTS] ElevenLabs 수신: {time.time()-t0:.2f}s, {len(resp.content):,} bytes")

            # MP3 → PCM 변환
            from pydub import AudioSegment
            audio = AudioSegment.from_mp3(io.BytesIO(resp.content))
            audio = audio.set_channels(1).set_sample_width(2).set_frame_rate(_SAMPLE_RATE)
            pcm = audio.raw_data

            stream = self.pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=_SAMPLE_RATE,
                output=True,
            )
            stream.write(pcm)
            stream.stop_stream()
            stream.close()

            logging.info(f"[TTS] ElevenLabs 전체 완료: {time.time()-t0:.2f}s")
            self.is_playing = False
            self.playback_finished.emit()
            return True

        except Exception as e:
            logging.error(f"ElevenLabs TTS speak 오류: {e}")
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

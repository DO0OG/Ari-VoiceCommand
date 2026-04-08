"""
ElevenLabs TTS 제공자.
Fish Audio / CosyVoice3와 동일한 인터페이스: speak() / playback_finished / cleanup()
"""
import logging
import tempfile
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
        self._session = None

        if api_key:
            logging.info("ElevenLabs TTS 초기화 완료 (voice_id=%s)", self.voice_id)
        else:
            logging.warning("ElevenLabs API 키가 설정되지 않았습니다.")

    def _get_session(self):
        if self._session is not None:
            return self._session
        try:
            import requests
        except ImportError:
            logging.error("requests 패키지가 필요합니다: pip install requests")
            return None
        self._session = requests.Session()
        return self._session

    def speak(self, text: str, emotion: str = "평온") -> bool:
        if not text or not self.api_key:
            return False

        session = self._get_session()
        if session is None:
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

            bytes_received = 0
            first_chunk_at = None
            with tempfile.SpooledTemporaryFile(max_size=2 * 1024 * 1024) as audio_buffer:
                with session.post(url, json=payload, headers=headers, timeout=30, stream=True) as resp:
                    resp.raise_for_status()
                    for chunk in resp.iter_content(chunk_size=65536):
                        if not chunk:
                            continue
                        if first_chunk_at is None:
                            first_chunk_at = time.time()
                        bytes_received += len(chunk)
                        audio_buffer.write(chunk)
                audio_buffer.seek(0)

                if first_chunk_at is not None:
                    logging.info("[TTS] ElevenLabs 첫 청크: %.2fs", first_chunk_at - t0)
                logging.info("[TTS] ElevenLabs 수신 완료: %.2fs, %s bytes", time.time() - t0, f"{bytes_received:,}")

                # MP3 → PCM 변환
                from pydub import AudioSegment
                audio = AudioSegment.from_file(audio_buffer, format="mp3")
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

            logging.info("[TTS] ElevenLabs 전체 완료: %.2fs", time.time() - t0)
            self.is_playing = False
            self.playback_finished.emit()
            return True

        except Exception as e:
            logging.error("ElevenLabs TTS speak 오류: %s", e)
            self.is_playing = False
            self.playback_finished.emit()
            return False

    def cleanup(self):
        try:
            if self._session is not None:
                self._session.close()
                self._session = None
        except Exception as exc:
            logging.debug("ElevenLabs 세션 정리 중 무시된 오류: %s", exc)
        try:
            self.pa.terminate()
        except Exception as exc:
            logging.debug("ElevenLabs TTS 정리 중 무시된 오류: %s", exc)

    def __del__(self):
        try:
            self.cleanup()
        except Exception as exc:
            logging.debug("ElevenLabs TTS 소멸자 정리 실패: %s", exc)

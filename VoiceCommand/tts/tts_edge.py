"""
Microsoft Edge TTS 제공자 — 무료, API 키 불필요
edge-tts 패키지 사용: pip install edge-tts
Fish Audio / CosyVoice3와 동일한 인터페이스: speak() / playback_finished / cleanup()
"""
import asyncio
import io
import logging
import time

import pyaudio
from PySide6.QtCore import QObject, Signal

# 지원 한국어 보이스 (edge-tts --list-voices 참고)
KO_VOICES = [
    ("ko-KR-SunHiNeural", "SunHi (여성, 기본)"),
    ("ko-KR-InJoonNeural", "InJoon (남성)"),
    ("ko-KR-HyunsuNeural", "Hyunsu (남성, 다중감정)"),
]
DEFAULT_VOICE = "ko-KR-SunHiNeural"
_SAMPLE_RATE = 22050


class EdgeTTS(QObject):
    playback_finished = Signal()

    def __init__(self, voice=DEFAULT_VOICE, rate="+0%", volume="+0%"):
        super().__init__()
        self.voice = voice
        self.rate = rate    # 말하기 속도: "+10%" 빠름, "-10%" 느림
        self.volume = volume
        self.is_playing = False
        self.pa = pyaudio.PyAudio()
        logging.info(f"Edge TTS 초기화 완료 (voice={voice})")

    def speak(self, text: str, emotion: str = "평온") -> bool:
        if not text:
            return False

        try:
            import edge_tts  # noqa: F401
        except ImportError:
            logging.error("edge-tts 패키지가 필요합니다: pip install edge-tts")
            return False

        try:
            self.is_playing = True
            t0 = time.time()

            # asyncio 이벤트 루프로 비동기 합성 실행
            loop = asyncio.new_event_loop()
            try:
                audio_data = loop.run_until_complete(self._synthesize(text))
            finally:
                loop.close()

            if not audio_data:
                logging.warning("Edge TTS: 오디오 데이터 없음")
                self.is_playing = False
                self.playback_finished.emit()
                return False

            logging.info(f"[TTS] Edge TTS 수신: {time.time()-t0:.2f}s, {len(audio_data):,} bytes")

            # MP3 → PCM 변환
            from pydub import AudioSegment
            audio = AudioSegment.from_mp3(io.BytesIO(audio_data))
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

            logging.info(f"[TTS] Edge TTS 전체 완료: {time.time()-t0:.2f}s")
            self.is_playing = False
            self.playback_finished.emit()
            return True

        except Exception as e:
            logging.error(f"Edge TTS speak 오류: {e}")
            self.is_playing = False
            self.playback_finished.emit()
            return False

    async def _synthesize(self, text: str) -> bytes:
        import edge_tts
        communicate = edge_tts.Communicate(
            text, self.voice, rate=self.rate, volume=self.volume
        )
        chunks = []
        async for item in communicate.stream():
            if item["type"] == "audio":
                chunks.append(item["data"])
        return b"".join(chunks) if chunks else b""

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

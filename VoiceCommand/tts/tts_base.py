"""
TTS 제공자 추상 기반 클래스
모든 TTS 구현체는 이 인터페이스를 따라야 한다.
"""
from abc import ABC, abstractmethod
from PySide6.QtCore import QObject, Signal


class BaseTTS(QObject, ABC):
    """TTS 제공자 공통 인터페이스.

    구현체:
      - FishTTSWebSocket  (fish_tts_ws.py)   — Fish Audio 스트리밍
      - CosyVoiceTTS      (cosyvoice_tts.py)  — 로컬 CosyVoice3 서브프로세스
      - OpenAITTS         (tts_openai.py)     — OpenAI tts-1 / tts-1-hd
      - ElevenLabsTTS     (tts_elevenlabs.py) — ElevenLabs REST API
      - EdgeTTS           (tts_edge.py)       — Microsoft Edge TTS (무료)
    """

    playback_finished = Signal()

    @abstractmethod
    def speak(self, text: str, emotion: str = "평온") -> bool:
        """텍스트를 음성으로 합성·재생한다.

        Args:
            text: 합성할 텍스트 (한국어)

        Returns:
            True = 재생 성공, False = 실패/건너뜀
        """

    @abstractmethod
    def cleanup(self) -> None:
        """리소스(오디오 스트림, 서브프로세스 등)를 정리한다."""

    # ── 기본 속성 ──────────────────────────────────────────────────────────────

    @property
    def is_playing(self) -> bool:
        """현재 재생 중인지 여부"""
        return getattr(self, "_is_playing", False)

    @is_playing.setter
    def is_playing(self, value: bool):
        self._is_playing = value

"""
간단한 음성 트리거 (계정 불필요)
"""
import logging
import speech_recognition as sr

from core.config_manager import ConfigManager
from core.stt_provider import create_stt_provider


class SimpleWakeWord:
    def __init__(self, wake_words=None):
        self.wake_words = list(wake_words or ["아리야", "시작"])
        self.recognizer = sr.Recognizer()
        self.should_stop = False
        self._calibrated = False  # 첫 listen 시 lazy 캘리브레이션
        self._provider_signature = None
        self._stt = None
        self.refresh_settings()

    def refresh_settings(self):
        settings = ConfigManager.load_settings()
        self.wake_words = list(settings.get("wake_words", self.wake_words) or ["아리야", "시작"])
        self.recognizer.energy_threshold = int(settings.get("stt_energy_threshold", 300))
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

    def recalibrate(self, source):
        """TTS 이후 환경 변화 시 임계값 재조정"""
        try:
            self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            logging.debug(f"재캘리브레이션 완료 (energy_threshold={self.recognizer.energy_threshold:.1f})")
        except Exception as e:
            logging.debug(f"재캘리브레이션 실패: {e}")

    def listen_for_wake_word(self, source):
        """웨이크워드 대기 — 첫 호출 시 캘리브레이션, 이후 즉시 청취"""
        if self.should_stop:
            return False
        try:
            self.refresh_settings()
            if not self._calibrated:
                self.recognizer.adjust_for_ambient_noise(source, duration=1.0)
                self._calibrated = True
                logging.info(f"웨이크워드 캘리브레이션 완료 (energy_threshold={self.recognizer.energy_threshold:.1f})")
            audio = self.recognizer.listen(source, timeout=2, phrase_time_limit=2)
            text = self._stt.transcribe(audio) if self._stt else None
            if not text:
                return False
            logging.debug(f"들은 내용: {text}")

            for wake_word in self.wake_words:
                if wake_word in text:
                    return True
            return False

        except sr.WaitTimeoutError:
            return False
        except sr.UnknownValueError:
            return False
        except Exception as e:
            logging.debug(f"음성 감지 오류: {e}")
            return False

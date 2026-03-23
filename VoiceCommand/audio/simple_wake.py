"""
간단한 음성 트리거 (계정 불필요)
"""
import speech_recognition as sr
import logging


class SimpleWakeWord:
    def __init__(self, wake_words=["아리야", "시작"]):
        self.wake_words = wake_words
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = False  # 자동 임계값 조정 비활성
        self.should_stop = False
        self._calibrated = False  # 첫 listen 시 lazy 캘리브레이션

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
            if not self._calibrated:
                self.recognizer.adjust_for_ambient_noise(source, duration=1.0)
                self._calibrated = True
                logging.info(f"웨이크워드 캘리브레이션 완료 (energy_threshold={self.recognizer.energy_threshold:.1f})")
            audio = self.recognizer.listen(source, timeout=2, phrase_time_limit=2)

            text = self.recognizer.recognize_google(audio, language="ko-KR")
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

import logging
import threading

# 전역 오디오 락 (여러 스레드에서 PyAudio 동시 접근 방지)
_audio_lock = threading.Lock()


class GlobalAudio:
    """전역 PyAudio 인스턴스 관리 (싱글톤 패턴)"""
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        """PyAudio 인스턴스를 반환 (없으면 생성)"""
        with cls._lock:
            if cls._instance is None:
                import pyaudio
                logging.info("전역 PyAudio 인스턴스 초기화 중...")
                try:
                    cls._instance = pyaudio.PyAudio()
                    logging.info("전역 PyAudio 인스턴스 생성 완료")
                except Exception as e:
                    logging.error(f"PyAudio 초기화 실패: {e}")
                    raise
            return cls._instance

    @classmethod
    def terminate(cls):
        """PyAudio 인스턴스 종료"""
        with cls._lock:
            if cls._instance:
                try:
                    cls._instance.terminate()
                    logging.info("전역 PyAudio 인스턴스 종료 완료")
                except Exception as e:
                    logging.debug(f"PyAudio 종료 오류 (무시): {e}")
                cls._instance = None


def get_audio_lock():
    """전역 오디오 락 반환"""
    return _audio_lock

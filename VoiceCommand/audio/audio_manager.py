"""전역 오디오 입력/출력 리소스를 공유하는 락 및 PyAudio 싱글톤."""

import logging
import threading

# 입력(마이크)과 출력(스피커)을 별도 락으로 분리
# PyAudio의 입력/출력 스트림은 독립적이므로 같은 락을 공유할 필요 없음
_audio_input_lock = threading.Lock()   # 마이크 캡처용
_audio_output_lock = threading.Lock()  # 스피커 재생용

# 하위 호환용 alias (기존 코드가 _audio_lock을 직접 임포트하는 경우 대비)
_audio_lock = _audio_input_lock


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
    """전역 오디오 입력 락 반환 (하위 호환)"""
    return _audio_input_lock


def get_audio_output_lock():
    """전역 오디오 출력 락 반환"""
    return _audio_output_lock

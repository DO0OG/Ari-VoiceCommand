import logging
import time
import random
import threading
import queue
import speech_recognition as sr
from queue import Queue
from PySide6.QtCore import QThread, Signal
from audio.audio_manager import _audio_lock
from core.constants import (
    WAKE_WORDS, WAKE_RESPONSES, SPEECH_LANGUAGE,
    SPEECH_TIMEOUT, SPEECH_PHRASE_LIMIT
)

# ───────────────────────────────────────────────────────────────────────────
# VoiceRecognitionThread
# ───────────────────────────────────────────────────────────────────────────

class VoiceRecognitionThread(QThread):
    """음성 인식 스레드: 웨이크워드 감지 및 명령 처리"""
    result = Signal(str)
    listening_state_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.running = True
        self.selected_microphone = None
        self.microphone_index = None

        from audio.simple_wake import SimpleWakeWord
        self.wake_detector = SimpleWakeWord(wake_words=WAKE_WORDS)

        from VoiceCommand import SharedMicrophone
        self.speech_recognizer = sr.Recognizer()
        self.microphone = SharedMicrophone(device_index=self.microphone_index)

    def set_microphone(self, microphone):
        from VoiceCommand import SharedMicrophone
        if self.selected_microphone != microphone:
            self.selected_microphone = microphone
            from VoiceCommand import get_microphone_index_helper
            self.microphone_index = get_microphone_index_helper(microphone)
            self.microphone = SharedMicrophone(device_index=self.microphone_index)

    def run(self):
        try:
            logging.info("음성 감지 루프 시작")
            while self.running:
                # 오디오 장치 점유를 위해 락 획득
                with _audio_lock:
                    with self.microphone as source:
                        detected = self.wake_detector.listen_for_wake_word(source)
                
                if detected:
                    self.handle_wake_word()
                
                time.sleep(0.1)
        except Exception as e:
            logging.error(f"VoiceRecognitionThread 오류: {e}", exc_info=True)
        finally:
            self.cleanup()

    def handle_wake_word(self):
        logging.info("웨이크 워드 감지됨!")
        from VoiceCommand import tts_wrapper, recognize_speech_helper, wake_detector_recalibrate_helper
        
        response = random.choice(WAKE_RESPONSES)
        tts_wrapper(response)
        
        # TTS 재생 완료 대기 (유동적 대기)
        try:
            from VoiceCommand import is_tts_playing
            wait_start = time.time()
            while is_tts_playing():
                if time.time() - wait_start > 15.0:
                    logging.warning("TTS 대기 타임아웃 (15초 초과)")
                    break
                time.sleep(0.1)
            
            # 재생이 끝난 후 음성 인시 시작 전 아주 짧은 여유
            time.sleep(0.2)
        except Exception as e:
            logging.error(f"TTS 대기 중 오류: {e}")
            time.sleep(0.5)
        
        self.listening_state_changed.emit(True)
        with _audio_lock:
            with self.microphone as source:
                recognize_speech_helper(self.speech_recognizer, source, self.result)
        self.listening_state_changed.emit(False)
        
        # 대화 후 재캘리브레이션
        with _audio_lock:
            with self.microphone as source:
                wake_detector_recalibrate_helper(self.wake_detector, source)

    def cleanup(self):
        if hasattr(self, 'wake_detector'):
            self.wake_detector.should_stop = True
        self.microphone = None

    def stop(self):
        self.running = False
        if hasattr(self, 'wake_detector'):
            self.wake_detector.should_stop = True
        self.wait(2000)


# ───────────────────────────────────────────────────────────────────────────
# TTSThread
# ───────────────────────────────────────────────────────────────────────────

class TTSThread(QThread):
    """TTS 전용 작업 스레드: 큐를 통해 순차 재생"""
    _MAX_QUEUE_SIZE = 32

    def __init__(self):
        super().__init__()
        self.queue = Queue(maxsize=self._MAX_QUEUE_SIZE)
        self.is_processing = False

    def run(self):
        logging.info("TTSThread 구동 중")
        while True:
            try:
                text = self.queue.get(timeout=1.0)
                if text is None:
                    break
                
                try:
                    self.is_processing = True
                    from VoiceCommand import text_to_speech, character_widget
                    text_to_speech(text)
                finally:
                    self.queue.task_done()
                    self.is_processing = False

                # 큐가 완전히 비었을 때만 말풍선을 숨김 (연속된 문장 처리)
                if self.queue.empty() and character_widget:
                    character_widget.hide_speech_bubble()
                    
            except queue.Empty:
                continue

    def speak(self, text):
        if not text:
            return False
        try:
            self.queue.put_nowait(text)
            return True
        except queue.Full:
            logging.warning("TTSThread 큐가 가득 차서 마지막 요청을 폐기했습니다.")
            return False


# ───────────────────────────────────────────────────────────────────────────
# CommandExecutionThread
# ───────────────────────────────────────────────────────────────────────────

class CommandExecutionThread(QThread):
    """명령 실행 전용 스레드: 메인 스레드 차단 방지"""
    def __init__(self):
        super().__init__()
        self.queue = Queue()

    def run(self):
        logging.info("CommandExecutionThread 구동 중")
        while True:
            try:
                command = self.queue.get(timeout=1.0)
                if command is None:
                    break
                
                from VoiceCommand import execute_command
                execute_command(command)
                self.queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"CommandExecutionThread 오류: {e}")
                continue

    def execute(self, command):
        self.queue.put(command)

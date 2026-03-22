import sys
import os
import time
import logging
import gc
import psutil
from collections import deque

from PySide6.QtCore import QObject, Signal
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from threads import VoiceRecognitionThread, TTSThread, CommandExecutionThread
from VoiceCommand import set_tts_thread

# 리소스 모니터링 스레드
class ResourceMonitor(QObject):
    gc_needed = Signal()

    def __init__(self, check_interval=5):
        super().__init__()
        self.check_interval = check_interval
        self.running = True
        self.process = psutil.Process()
        self.memory_history = deque(maxlen=10)
        self.last_gc_time = time.time()

    def get_memory_info(self):
        try:
            mem_info = self.process.memory_info()
            return mem_info.rss / (1024 * 1024)
        except Exception:
            return 0

    def run(self):
        while self.running:
            current_memory = self.get_memory_info()
            self.memory_history.append(current_memory)

            if len(self.memory_history) >= 5:
                avg_memory = sum(self.memory_history) / len(self.memory_history)
                if (
                    current_memory > avg_memory * 1.5
                    and time.time() - self.last_gc_time > 60
                ):
                    self.gc_needed.emit()
                    self.last_gc_time = time.time()

            time.sleep(self.check_interval)

    def stop(self):
        self.running = False

# 가비지 컬렉션 실행
def perform_gc():
    logging.info("가비지 컬렉션 실행 중...")
    gc.collect()
    process = psutil.Process()
    mem_info = process.memory_info()
    logging.info(
        f"가비지 컬렉션 완료. 메모리 사용량: RSS: {mem_info.rss / (1024 * 1024):.2f} MB"
    )

class FileChangeHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        self._start_time = time.time()

    def on_modified(self, event):
        if time.time() - self._start_time < 10:
            return
        if event.src_path.endswith('.py'):
            logging.info(f"파일 {event.src_path}가 수정되었습니다. 프로그램을 재시작합니다...")
            os.execv(sys.executable, ['python'] + sys.argv)

def start_file_watcher():
    # 배포(frozen) 환경에서는 파일 감시 불필요
    if getattr(sys, 'frozen', False):
        return None
    event_handler = FileChangeHandler()
    observer = Observer()
    observer.schedule(event_handler, path='.', recursive=False)
    observer.start()
    return observer


class AriCore(QObject):
    def __init__(self):
        super().__init__()
        self.voice_thread = VoiceRecognitionThread()
        self.tts_thread = TTSThread()
        set_tts_thread(self.tts_thread)
        self.command_thread = CommandExecutionThread()
        self.resource_monitor = ResourceMonitor()
        logging.info("AriCore 초기화 완료")

        self.init_microphone()
        self.init_threads()
        self.init_connections()

        self.file_observer = start_file_watcher()
        logging.info("파일 감시 시작")

    def init_threads(self):
        self.voice_thread.start()
        self.tts_thread.start()
        self.command_thread.start()
        self.resource_monitor.gc_needed.connect(perform_gc)

    def init_connections(self):
        self.voice_thread.result.connect(self.handle_voice_result)

    def init_microphone(self):
        """마이크 초기화 (설정값 적용)"""
        from config_manager import ConfigManager
        settings = ConfigManager.load_settings()
        selected_microphone = settings.get("microphone", "")
        
        if selected_microphone:
            logging.info(f"설정된 마이크 사용: {selected_microphone}")
            self.voice_thread.set_microphone(selected_microphone)
        else:
            logging.info("기본 마이크를 사용합니다.")
            self.voice_thread.set_microphone(None)

    def handle_voice_result(self, text):
        logging.info(f"인식된 명령: {text}")
        self.command_thread.execute(text)

    def cleanup(self):
        logging.info("=== AriCore cleanup 시작 ===")

        # Step 1: 음성 인식 먼저 중지 (새 명령 차단)
        logging.info("Step 1/6: 음성 인식 중지")
        self.voice_thread.stop()
        if not self.voice_thread.wait(5000):
            logging.warning("음성 인식 스레드 타임아웃")

        # Step 2: 파일 감시자 중지
        logging.info("Step 2/6: 파일 감시자 중지")
        if hasattr(self, 'file_observer') and self.file_observer:
            self.file_observer.stop()
            self.file_observer.join(timeout=2)

        # Step 3: TTS 스레드 중지
        logging.info("Step 3/6: TTS 스레드 중지")
        self.tts_thread.queue.put(None)
        if not self.tts_thread.wait(5000):
            logging.warning("TTS 스레드 타임아웃")

        # Step 4: 명령 실행 스레드 중지
        logging.info("Step 4/6: 명령 실행 스레드 중지")
        self.command_thread.queue.put(None)
        if not self.command_thread.wait(5000):
            logging.warning("명령 실행 스레드 타임아웃")

        # Step 5: 리소스 모니터 중지
        logging.info("Step 5/6: 리소스 모니터 중지")
        self.resource_monitor.stop()

        # Step 6: TTS 리소스 정리
        logging.info("Step 6/6: TTS 리소스 정리")
        from VoiceCommand import fish_tts
        from audio_manager import GlobalAudio
        if fish_tts:
            fish_tts.cleanup()
        GlobalAudio.terminate()

        logging.info("=== AriCore cleanup 완료 ===")

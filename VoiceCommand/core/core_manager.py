"""코어 런타임 상태와 시스템 정보를 조회하는 유틸리티."""

import sys
import os
import time
import logging
import gc
import psutil
from collections import deque

from PySide6.QtCore import QObject, Signal, QProcess
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from core._whisper_worker import bundled_executable_path
from core.resource_manager import is_bundled
from core.threads import VoiceRecognitionThread, TTSThread, CommandExecutionThread
from core.VoiceCommand import is_session_lock_blocked, set_tts_thread

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

def _restart_command() -> tuple[str, list[str]]:
    """현재 실행 환경을 유지한 재시작 명령을 반환한다.

    배포판의 sys.executable은 존재하지 않는 python.exe를 가리키므로 실제 실행 파일을 다시 띄운다.
    """
    if is_bundled():
        return bundled_executable_path(), sys.argv[1:]
    return sys.executable, [os.path.abspath(sys.argv[0]), *sys.argv[1:]]


class FileChangeHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        self._start_time = time.time()

    def on_modified(self, event):
        if time.time() - self._start_time < 10:
            return
        if event.src_path.endswith('.py'):
            logging.info(f"파일 {event.src_path}가 수정되었습니다. 프로그램을 재시작합니다...")
            executable, args = _restart_command()
            started = QProcess.startDetached(executable, args, os.getcwd())
            if started:
                logging.info("새 프로세스를 시작했습니다. 현재 프로세스를 종료합니다.")
                raise SystemExit(0)
            logging.error("프로세스 재시작에 실패했습니다.")

def start_file_watcher():
    # 배포(frozen/Nuitka) 환경에서는 파일 감시 불필요
    if is_bundled():
        return None
    event_handler = FileChangeHandler()
    observer = None
    try:
        observer = Observer()
        observer.schedule(event_handler, path='.', recursive=False)
        observer.start()
    except Exception as exc:
        logging.warning("파일 감시 기능을 시작할 수 없습니다: %s", exc, exc_info=True)
        if observer is not None:
            try:
                observer.stop()
                if observer.is_alive():
                    observer.join(timeout=2)
            except Exception as cleanup_error:
                logging.debug("파일 감시 기능 정리 생략: %s", cleanup_error)
        return None
    return observer


def _cleanup_llm_clients():
    llm_provider = sys.modules.get("agent.llm_provider")
    if llm_provider is None:
        gc.collect()
        return

    provider = getattr(llm_provider, "_instance", None)
    if provider is None:
        gc.collect()
        return

    closed_ids = set()
    for name in (
        "client",
        "planner_client",
        "execution_client",
        "memory_extractor_client",
    ):
        client = getattr(provider, name, None)
        try:
            if client is not None and id(client) not in closed_ids:
                closed_ids.add(id(client))
                close = getattr(client, "close", None)
                if callable(close):
                    close()
        except Exception as exc:
            logging.debug("LLM 클라이언트 종료 생략: %s", exc)
        finally:
            try:
                setattr(provider, name, None)
            except Exception as exc:
                logging.debug("LLM 클라이언트 참조 해제 생략: %s", exc)
            del client

    del provider
    gc.collect()


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
        from core.config_manager import ConfigManager
        settings = ConfigManager.load_settings()
        selected_microphone = settings.get("microphone", "")
        
        if selected_microphone:
            logging.info(f"설정된 마이크 사용: {selected_microphone}")
            self.voice_thread.set_microphone(selected_microphone)
        else:
            logging.info("기본 마이크를 사용합니다.")

    def handle_voice_result(self, text):
        if is_session_lock_blocked():
            logging.info("잠금 상태에서 인식된 음성 명령을 무시합니다.")
            return
        logging.info("인식된 명령 수신 (%d자)", len(text or ""))
        self.command_thread.execute(text)

    def cleanup(self):
        logging.info("=== AriCore cleanup 시작 ===")

        # Step 1: 음성 인식 먼저 중지 (새 명령 차단)
        logging.info("Step 1/7: 음성 인식 중지")
        self.voice_thread.stop()
        if not self.voice_thread.wait(5000):
            logging.warning("음성 인식 스레드 타임아웃")

        # Step 2: 파일 감시자 중지
        logging.info("Step 2/7: 파일 감시자 중지")
        if hasattr(self, 'file_observer') and self.file_observer:
            self.file_observer.stop()
            self.file_observer.join(timeout=2)

        # Step 3: TTS 스레드 중지
        logging.info("Step 3/7: TTS 스레드 중지")
        self.tts_thread.stop()
        if not self.tts_thread.wait(5000):
            logging.warning("TTS 스레드 타임아웃")

        # Step 4: 명령 실행 스레드 중지
        logging.info("Step 4/7: 명령 실행 스레드 중지")
        self.command_thread.queue.put(None)
        if not self.command_thread.wait(5000):
            logging.warning("명령 실행 스레드 타임아웃")

        logging.info("Step 5/7: LLM 클라이언트 정리")
        _cleanup_llm_clients()

        # Step 6: 리소스 모니터 중지
        logging.info("Step 6/7: 리소스 모니터 중지")
        self.resource_monitor.stop()

        # Step 7: TTS 리소스 정리
        logging.info("Step 7/7: TTS 리소스 정리")
        from core.VoiceCommand import _state
        from audio.audio_manager import GlobalAudio
        if _state.fish_tts:
            _state.fish_tts.cleanup()
        GlobalAudio.terminate()

        logging.info("=== AriCore cleanup 완료 ===")

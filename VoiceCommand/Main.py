import sys
import os
import time
import logging
import faulthandler
from datetime import datetime

# Windows 콘솔 창 숨기기
if sys.platform == "win32":
    import ctypes
    ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
import gc
import psutil
import warnings

faulthandler.enable()  # 네이티브 크래시(세그폴트 등) 발생 시 stderr에 스택 출력
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QDialog
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QObject, Signal, QTimer
from settings_dialog import SettingsDialog
from ai_assistant import get_ai_assistant
from character_widget import CharacterWidget
from collections import deque
from threads import (
    VoiceRecognitionThread,
    TTSThread,
    CommandExecutionThread
)
from VoiceCommand import (
    tts_wrapper,
    set_ai_assistant,
    set_character_widget,
    set_tts_thread,
    start_tts_background,
)
import json
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 전역 변수 선언
tts_model = None
speaker_ids = None
whisper_model = None
ai_assistant = None
icon_path = None
active_timer = None

warnings.filterwarnings("ignore", category=FutureWarning)
os.environ["SDL_VIDEODRIVER"] = "dummy"

icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
if not os.path.exists(icon_path):
    print(f"경고: 아이콘 파일을 찾을 수 없습니다: {icon_path}")
    icon_path = None


# 로그 설정
def setup_logging():
    from resource_manager import ResourceManager
    log_dir = ResourceManager.get_writable_path("logs")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"ari_log_{current_time}.log")

    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


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
        except:
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


class SystemTrayIcon(QSystemTrayIcon):
    def __init__(self, icon, parent=None):
        super(SystemTrayIcon, self).__init__(icon, parent)
        self.setToolTip(f"Ari Voice Command")
        self.should_exit = False
        self.character_widget = None  # 캐릭터 위젯 참조 초기화

        self.menu = QMenu(parent)
        self.setContextMenu(self.menu)

        # 캐릭터 표시/숨기기 메뉴 추가 (최상단)
        self.character_action = self.menu.addAction("캐릭터 표시")
        self.character_action.triggered.connect(self.toggle_character)

        self.menu.addSeparator()

        # 게임 모드 토글 추가 (GPU 해제용)
        self.game_mode_action = self.menu.addAction("🎮 게임 모드 (GPU 절약)")
        self.game_mode_action.setCheckable(True)
        self.game_mode_action.triggered.connect(self.toggle_game_mode)

        # 스마트 어시스턴트 모드 토글 추가
        self.smart_mode_action = self.menu.addAction("스마트 어시스턴트 모드")
        self.smart_mode_action.setCheckable(True)
        self.smart_mode_action.triggered.connect(self.toggle_smart_mode)

        # 마우스 반응 토글 추가
        self.mouse_reaction_action = self.menu.addAction("마우스 반응")
        self.mouse_reaction_action.setCheckable(True)
        self.mouse_reaction_action.triggered.connect(self.toggle_mouse_reaction)

        self.menu.addSeparator()

        # 설정 메뉴 추가
        self.settings_action = self.menu.addAction("설정")
        self.settings_action.triggered.connect(self.open_settings)

        self.menu.addSeparator()

        self.exit_action = self.menu.addAction("종료")
        self.exit_action.triggered.connect(self.exit)

        # 메뉴가 열릴 때마다 상태 업데이트
        self.menu.aboutToShow.connect(self.update_character_menu_text)
        self.menu.aboutToShow.connect(self.update_game_mode_status)
        self.menu.aboutToShow.connect(self.update_smart_mode_status)
        self.menu.aboutToShow.connect(self.update_mouse_reaction_status)

    def toggle_game_mode(self):
        """게임 모드 토글: CosyVoice3 VRAM 해제 ↔ 복원"""
        from VoiceCommand import enable_game_mode, disable_game_mode, is_game_mode
        if self.game_mode_action.isChecked():
            enable_game_mode()
            if self.character_widget:
                self.character_widget.say("게임 모드 ON. GPU 메모리 해제했습니다.", duration=3000)
        else:
            disable_game_mode()
            if self.character_widget:
                self.character_widget.say("게임 모드 OFF. TTS 복원 중...", duration=3000)

    def update_game_mode_status(self):
        from VoiceCommand import is_game_mode
        self.game_mode_action.setChecked(is_game_mode())

    def toggle_smart_mode(self):
        """스마트 어시스턴트 모드 토글"""
        from VoiceCommand import learning_mode
        learning_mode['enabled'] = self.smart_mode_action.isChecked()

        status = "활성화" if learning_mode['enabled'] else "비활성화"
        logging.info(f"스마트 어시스턴트 모드 {status}")

        # 캐릭터에게 알림
        if self.character_widget:
            message = f"스마트 어시스턴트 모드가 {status}되었습니다."
            self.character_widget.say(message, duration=3000)

    def update_smart_mode_status(self):
        """스마트 모드 상태 업데이트"""
        from VoiceCommand import learning_mode
        self.smart_mode_action.setChecked(learning_mode['enabled'])

    def toggle_mouse_reaction(self):
        """마우스 반응 토글"""
        if self.character_widget:
            self.character_widget.toggle_mouse_tracking()

    def update_mouse_reaction_status(self):
        """마우스 반응 상태 업데이트"""
        if self.character_widget:
            self.mouse_reaction_action.setChecked(self.character_widget.mouse_tracking_enabled)

    def open_settings(self):
        """설정 창 열기"""
        dialog = SettingsDialog()
        if dialog.exec() == QDialog.Accepted:
            # 설정 변경 후 TTS 재초기화 (백그라운드)
            from VoiceCommand import initialize_tts, _tts_init_event
            import threading
            _tts_init_event.clear()

            def _reinit():
                try:
                    initialize_tts()
                except Exception as e:
                    logging.error(f"TTS 재초기화 실패: {e}")

            threading.Thread(target=_reinit, daemon=True, name="TTS-Reinit").start()
            logging.info("설정이 저장되고 TTS 재초기화를 시작했습니다.")

    def exit(self):
        self.should_exit = True
        QApplication.instance().quit()

    def set_character_widget(self, character_widget):
        """캐릭터 위젯 참조 설정"""
        self.character_widget = character_widget
        self.update_character_menu_text()
        logging.info("시스템 트레이에 캐릭터 위젯 참조가 설정되었습니다.")

    def toggle_character(self):
        """캐릭터 표시/숨기기 토글"""
        if not self.character_widget:
            logging.warning("캐릭터 위젯이 초기화되지 않았습니다.")
            return

        if self.character_widget.isVisible():
            self.character_widget.hide()
            logging.info("캐릭터를 숨겼습니다.")
        else:
            self.character_widget.show()
            logging.info("캐릭터를 표시했습니다.")

    def update_character_menu_text(self):
        """캐릭터 메뉴 텍스트 업데이트"""
        if self.character_widget and self.character_widget.isVisible():
            self.character_action.setText("캐릭터 숨기기")
        else:
            self.character_action.setText("캐릭터 표시")


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


def check_cosyvoice_first_run(app):
    """최초 실행 시 CosyVoice 설치 여부 확인"""
    from resource_manager import ResourceManager
    FLAG_FILE = ResourceManager.get_writable_path(".cosyvoice_asked")
    COSYVOICE_DIR = r"D:\Git\CosyVoice"

    if os.path.exists(FLAG_FILE) or os.path.exists(COSYVOICE_DIR):
        return  # 이미 물어봤거나 설치됨

    from PySide6.QtWidgets import QMessageBox
    msg = QMessageBox()
    msg.setWindowTitle("CosyVoice3 로컬 TTS")
    msg.setText(
        "로컬 TTS 엔진 CosyVoice3를 설치하시겠습니까?\n\n"
        "• 설치 시: 고품질 한국어 TTS 사용 가능 (GPU 권장, 약 2~5GB)\n"
        "• 미설치 시: Fish Audio API TTS 사용 (인터넷 필요)\n\n"
        "나중에 설치하려면 install_cosyvoice.py를 직접 실행하세요."
    )
    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    msg.setDefaultButton(QMessageBox.No)
    msg.button(QMessageBox.Yes).setText("설치")
    msg.button(QMessageBox.No).setText("나중에")

    # 플래그 파일 생성 (다시 묻지 않음)
    open(FLAG_FILE, "w").close()

    if msg.exec() == QMessageBox.Yes:
        import threading
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import Qt

        progress = QProgressDialog("CosyVoice3 설치 중...\n콘솔 창에서 진행 상황을 확인하세요.", None, 0, 0)
        progress.setWindowTitle("설치 중")
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.show()
        app.processEvents()

        def run_install():
            try:
                import install_cosyvoice
                install_cosyvoice.install()
            except Exception as e:
                logging.error(f"CosyVoice 설치 오류: {e}")
            finally:
                progress.close()

        t = threading.Thread(target=run_install, daemon=True)
        t.start()
        while t.is_alive():
            app.processEvents()
            time.sleep(0.1)

        QMessageBox.information(None, "설치 완료",
            "CosyVoice3 설치가 완료되었습니다.\n설정에서 TTS 모드를 '로컬 (CosyVoice3)'으로 변경하세요.")


def main():
    global ai_assistant, icon_path
    ari_core = None
    character = None
    tray_icon = None
    try:
        setup_logging()
        logging.info("프로그램 시작")

        # 리소스 추출
        from resource_manager import ResourceManager
        logging.info("리소스 추출 확인 중...")
        ResourceManager.extract_resources()

        app = QApplication(sys.argv)

        # 최초 실행 시 CosyVoice 설치 여부 확인
        check_cosyvoice_first_run(app)

        # AI 어시스턴트 초기화
        ai_assistant = get_ai_assistant()
        set_ai_assistant(ai_assistant)

        use_system_tray = QSystemTrayIcon.isSystemTrayAvailable()

        if use_system_tray:
            app.setQuitOnLastWindowClosed(False)
            icon = QIcon(icon_path) if icon_path else QIcon()
            tray_icon = SystemTrayIcon(icon)
            tray_icon.show()
        else:
            logging.warning("시스템 트레이를 사용할 수 없습니다. 콘솔 모드로 실행합니다.")

        ari_core = AriCore()

        # 전역 오디오 인스턴스 초기화 (메인 스레드에서 생성)
        from audio_manager import GlobalAudio
        GlobalAudio.get_instance()

        # TTS 백그라운드 초기화 시작 (CosyVoice 모델 로드를 미리 시작)
        start_tts_background()

        # 캐릭터 위젯 생성
        character = CharacterWidget()
        set_character_widget(character)

        # 트레이 아이콘에 캐릭터 참조 설정
        if use_system_tray and tray_icon:
            tray_icon.set_character_widget(character)

        # 메인 이벤트 루프 실행
        exit_code = app.exec()  # Qt 표준 이벤트 루프 사용
        logging.info(f"Application exited with code: {exit_code}")

    except KeyboardInterrupt:
        logging.info("프로그램 종료")
    except Exception as e:
        logging.error(f"예외 발생: {str(e)}", exc_info=True)
    finally:
        logging.info("=== 앱 종료 시작 ===")
        if character:
            character.cleanup()
            character.close()
        if ari_core:
            ari_core.cleanup()
        logging.info("=== 앱 종료 완료 ===")

if __name__ == "__main__":
    main()

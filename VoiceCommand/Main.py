import sys
import os
import time
import logging
import faulthandler
from datetime import datetime
import warnings

# Qt의 비활성 포커스 요청 경고(qt.qpa.window)를 숨긴다.
# 캐릭터 위젯은 WindowDoesNotAcceptFocus 플래그를 의도적으로 사용하므로,
# 드래그 시 발생하는 requestActivate 경고는 기능상 무해한 노이즈다.
_qt_logging_rules = os.environ.get("QT_LOGGING_RULES", "").strip()
_suppress_rule = "qt.qpa.window.warning=false"
if _suppress_rule not in _qt_logging_rules:
    os.environ["QT_LOGGING_RULES"] = (
        f"{_qt_logging_rules};{_suppress_rule}" if _qt_logging_rules else _suppress_rule
    )

# Windows 콘솔 창 숨기기
if sys.platform == "win32":
    import ctypes
    ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

if sys.stderr is not None:
    faulthandler.enable()  # 네이티브 크래시(세그폴트 등) 발생 시 stderr에 스택 출력

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMessageBox, QProgressDialog
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt

from assistant.ai_assistant import get_ai_assistant
from ui.character_widget import CharacterWidget
from ui.text_interface import create_text_interface
from core.VoiceCommand import (
    tts_wrapper,
    set_ai_assistant,
    set_character_widget,
    start_tts_background,
)

from core.core_manager import AriCore
from ui.tray_icon import SystemTrayIcon
from core.plugin_loader import PluginContext, get_plugin_manager

# 전역 변수 선언
ai_assistant = None
icon_path = None

warnings.filterwarnings("ignore", category=FutureWarning)
os.environ["SDL_VIDEODRIVER"] = "dummy"

icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
if not os.path.exists(icon_path):
    if sys.stdout is not None:
        print(f"경고: 아이콘 파일을 찾을 수 없습니다: {icon_path}")
    icon_path = None

# 로그 설정
_MAX_LOG_FILES = 10  # 보관할 최대 로그 파일 수

def _cleanup_old_logs(log_dir: str) -> None:
    """오래된 로그 파일 자동 삭제 (최대 _MAX_LOG_FILES개 유지)."""
    try:
        logs = sorted(
            [f for f in os.listdir(log_dir) if f.startswith("ari_log_") and f.endswith(".log")],
            reverse=True,
        )
        for old in logs[_MAX_LOG_FILES:]:
            try:
                os.remove(os.path.join(log_dir, old))
            except OSError as e:
                logging.debug(f"로그 파일 삭제 실패: {e}")
    except OSError as e:
        logging.debug(f"로그 디렉터리 읽기 실패: {e}")

def setup_logging():
    from core.resource_manager import ResourceManager
    log_dir = ResourceManager.get_writable_path("logs")
    os.makedirs(log_dir, exist_ok=True)

    _cleanup_old_logs(log_dir)

    current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"ari_log_{current_time}.log")

    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            *(  [logging.StreamHandler(sys.stdout)] if sys.stdout is not None else [] ),
        ],
    )

def check_cosyvoice_first_run(app):
    """최초 실행 시 CosyVoice 설치 여부 확인"""
    from core.resource_manager import ResourceManager
    FLAG_FILE = ResourceManager.get_writable_path(".cosyvoice_asked")
    from tts.cosyvoice_tts import _get_cosyvoice_dir_cached
    cosyvoice_dir = _get_cosyvoice_dir_cached()

    if os.path.exists(FLAG_FILE) or (cosyvoice_dir and os.path.isdir(cosyvoice_dir)):
        return  # 이미 물어봤거나 설치됨

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
    with open(FLAG_FILE, "w"):
        pass

    if msg.exec() == QMessageBox.Yes:
        import threading

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
    text_interface = None
    plugin_manager = None
    try:
        setup_logging()
        logging.info("프로그램 시작")

        # 리소스 추출
        from core.resource_manager import ResourceManager
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
        from audio.audio_manager import GlobalAudio
        GlobalAudio.get_instance()

        # TTS 백그라운드 초기화 시작 (CosyVoice 모델 로드를 미리 시작)
        start_tts_background()

        # 캐릭터 위젯 생성
        logging.info("캐릭터 위젯 생성 시작")
        character = CharacterWidget()
        logging.info("캐릭터 위젯 생성 완료")
        set_character_widget(character)

        # 텍스트 인터페이스 생성 및 설정
        text_interface = create_text_interface(ai_assistant, tts_wrapper)
        character.set_text_interface(text_interface)

        # 트레이 아이콘에 캐릭터 참조 및 텍스트 인터페이스 설정
        if use_system_tray and tray_icon:
            tray_icon.set_character_widget(character)
            tray_icon.set_text_interface(text_interface)

        plugin_manager = get_plugin_manager()
        plugin_manager.load_plugins(
            PluginContext(
                app=app,
                tray_icon=tray_icon,
                character_widget=character,
                text_interface=text_interface,
            )
        )
        logging.info("플러그인 로드 완료: %d개", len(plugin_manager.list_plugins()))

        # 메인 이벤트 루프 실행
        exit_code = app.exec()  # Qt 표준 이벤트 루프 사용
        logging.info(f"Application exited with code: {exit_code}")

    except KeyboardInterrupt:
        logging.info("프로그램 종료")
    except Exception as e:
        logging.error(f"예외 발생: {str(e)}", exc_info=True)
    finally:
        logging.info("=== 앱 종료 시작 ===")
        if text_interface:
            text_interface.cleanup()
        if character:
            character.cleanup()
            character.close()
        if ari_core:
            ari_core.cleanup()
        logging.info("=== 앱 종료 완료 ===")

if __name__ == "__main__":
    main()

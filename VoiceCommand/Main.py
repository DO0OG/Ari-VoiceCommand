"""Ari 데스크톱 애플리케이션의 Qt 진입점."""

import sys
import os
import logging
import faulthandler
from datetime import datetime
import warnings

# torch + faster-whisper(CTranslate2/MKL)가 libiomp5md.dll을 중복 초기화하는
# OMP Error #15를 억제한다. 두 라이브러리가 같은 프로세스에 공존하는 경우
# 발생하는 알려진 Windows 환경 충돌이며, 이 플래그로 안전하게 계속 실행된다.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

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
from PySide6.QtCore import QEventLoop, Qt, QTimer

from assistant.ai_assistant import get_ai_assistant
from ui.character_widget import CharacterWidget
from ui.text_interface import create_text_interface
from core.VoiceCommand import (
    tts_wrapper,
    set_ai_assistant,
    set_character_widget,
    start_tts_background,
    _state,
)

from core.core_manager import AriCore
from ui.tray_icon import SystemTrayIcon
from core.plugin_loader import PluginContext, get_plugin_manager
from commands.ai_command import AICommand
from agent.llm_provider import get_llm_provider
from agent.proactive_scheduler import get_scheduler

# 전역 변수 선언
ai_assistant = None
icon_path = None

warnings.filterwarnings("ignore", category=FutureWarning)
os.environ["SDL_VIDEODRIVER"] = "dummy"


def _resolve_icon_path(log_missing: bool = False):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
    if os.path.exists(path):
        return path
    if log_missing:
        logging.warning("아이콘 파일을 찾을 수 없습니다: %s", path)
    return None


icon_path = _resolve_icon_path()

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
                logging.debug("로그 파일 삭제 실패: %s", e)
    except OSError as e:
        logging.debug("로그 디렉터리 읽기 실패: %s", e)

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
        install_done = threading.Event()
        install_error = {"message": ""}

        def run_install():
            try:
                import install_cosyvoice
                install_cosyvoice.install()
            except Exception as e:
                logging.error("CosyVoice 설치 오류: %s", e)
                install_error["message"] = str(e)
            finally:
                install_done.set()

        t = threading.Thread(target=run_install, daemon=True)
        t.start()
        loop = QEventLoop()
        poll_timer = QTimer()
        poll_timer.setInterval(100)

        def finish_install_wait():
            if not install_done.is_set():
                return
            poll_timer.stop()
            progress.close()
            loop.quit()

        poll_timer.timeout.connect(finish_install_wait)
        poll_timer.start()
        loop.exec()

        if install_error["message"]:
            QMessageBox.warning(
                None,
                "설치 실패",
                f"CosyVoice3 설치 중 오류가 발생했습니다.\n{install_error['message']}",
            )
        else:
            QMessageBox.information(
                None,
                "설치 완료",
                "CosyVoice3 설치가 완료되었습니다.\n설정에서 TTS 모드를 '로컬 (CosyVoice3)'으로 변경하세요.",
            )


def register_background_learning_tasks(scheduler) -> None:
    from core.config_manager import ConfigManager

    memory_enabled = True
    weekly_enabled = bool(ConfigManager.get("weekly_report_enabled", False))
    scheduler.ensure_task(
        name="ari_memory_consolidation",
        goal="메모리 정리 실행",
        schedule_expr="매일 3시 30",
        task_type="maintenance",
        repeat=True,
        repeat_sec=86400,
        repeat_rule="daily",
        enabled=memory_enabled,
    )
    scheduler.ensure_task(
        name="ari_weekly_report",
        goal="이번 주 자기개선 리포트 생성",
        schedule_expr="매주 월요일 9시 0",
        task_type="weekly_report",
        repeat=True,
        repeat_sec=86400 * 7,
        repeat_rule="weekly",
        enabled=weekly_enabled,
    )

def start_performance_warmups() -> None:
    try:
        from agent.embedder import get_embedder
        get_embedder().warmup_async()
    except Exception as exc:
        logging.debug("임베더 워밍업 생략: %s", exc)


def flush_runtime_state() -> None:
    try:
        from agent.strategy_memory import flush_strategy_memory
        flush_strategy_memory()
    except Exception as exc:
        logging.debug("StrategyMemory flush 생략: %s", exc)
    try:
        from agent.episode_memory import flush_episode_memory
        flush_episode_memory()
    except Exception as exc:
        logging.debug("EpisodeMemory flush 생략: %s", exc)
    try:
        from agent.skill_library import flush_skill_library
        flush_skill_library()
    except Exception as exc:
        logging.debug("SkillLibrary flush 생략: %s", exc)
    try:
        from memory.conversation_history import get_conversation_history
        get_conversation_history().flush()
    except Exception as exc:
        logging.debug("ConversationHistory flush 생략: %s", exc)

def main():
    global ai_assistant, icon_path
    ari_core = None
    character = None
    tray_icon = None
    text_interface = None
    plugin_manager = None
    plugin_watcher = None
    plugin_flush_timer = None
    try:
        setup_logging()
        icon_path = _resolve_icon_path(log_missing=True)
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
        start_performance_warmups()

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

        scheduler = get_scheduler(tts_wrapper)
        try:
            register_background_learning_tasks(scheduler)
        except Exception as exc:
            logging.debug("백그라운드 학습 작업 등록 생략: %s", exc)

        # 놓친 예약 작업 보충 실행 — TTS/오디오 초기화 완료 후 실행
        try:
            scheduler.check_missed_tasks_on_startup()
        except Exception as exc:
            logging.debug("놓친 작업 확인 생략: %s", exc)

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
            # 캐릭터 우클릭 메뉴를 트레이 메뉴와 공유 (플러그인 액션 포함)
            character.set_tray_menu(tray_icon.menu)

        cmd_registry = _state.command_registry
        ai_command = next((cmd for cmd in getattr(cmd_registry, "commands", []) if isinstance(cmd, AICommand)), None)

        def _register_tool_for_plugin(schema: dict, handler) -> None:
            tool_name = str(schema.get("function", {}).get("name", "") or "")
            if not tool_name or ai_command is None:
                return
            if tool_name in ai_command._dispatch:
                logging.warning(f"[PluginLoader] 중복 도구 등록 거부: {tool_name}")
                return
            get_llm_provider().register_plugin_tool(schema)
            ai_command.register_plugin_tool_handler(tool_name, handler)

        plugin_manager = get_plugin_manager()
        plugin_manager.load_plugins(
            PluginContext(
                app=app,
                tray_icon=tray_icon,
                character_widget=character,
                text_interface=text_interface,
                register_menu_action=tray_icon.add_plugin_menu_action if tray_icon else None,
                register_command=cmd_registry.register_command if cmd_registry else None,
                register_tool=_register_tool_for_plugin,
                register_character_pack=character.register_character_pack if character else None,
                set_character_menu_enabled=character.set_context_menu_enabled if character else None,
            )
        )
        logging.info("플러그인 로드 완료: %d개", len(plugin_manager.list_plugins()))

        try:
            from core.plugin_watcher import PluginWatcher

            plugin_watcher = PluginWatcher(plugin_manager.plugin_dir(), plugin_manager)
            plugin_watcher.start()
            plugin_flush_timer = QTimer()
            plugin_flush_timer.timeout.connect(plugin_watcher.flush)
            plugin_flush_timer.start(1000)
        except Exception as exc:
            logging.error(f"플러그인 감시 시작 실패: {exc}")

        # 메인 이벤트 루프 실행
        exit_code = app.exec()  # Qt 표준 이벤트 루프 사용
        logging.info(f"Application exited with code: {exit_code}")

    except KeyboardInterrupt:
        logging.info("프로그램 종료")
    except Exception as e:
        logging.error(f"예외 발생: {str(e)}", exc_info=True)
    finally:
        logging.info("=== 앱 종료 시작 ===")
        flush_runtime_state()
        if text_interface:
            text_interface.cleanup()
        if character:
            character.cleanup()
            character.close()
        if ari_core:
            ari_core.cleanup()
        if plugin_flush_timer:
            plugin_flush_timer.stop()
        if plugin_watcher:
            plugin_watcher.stop()
        logging.info("=== 앱 종료 완료 ===")

if __name__ == "__main__":
    main()

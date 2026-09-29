"""Ari 데스크톱 애플리케이션의 Qt 진입점."""

# ruff: noqa: E402

import importlib
import sys
from core._whisper_worker import dispatch_worker_command

_worker_exit_code = dispatch_worker_command(sys.argv)
if _worker_exit_code is None:
    from core.script_worker import dispatch_script_command

    _worker_exit_code = dispatch_script_command(sys.argv)
if _worker_exit_code is None and len(sys.argv) == 3 and sys.argv[1] == "--bundle-import-self-test":
    # 배포 워크플로가 설치본의 필수 모듈 포함 여부를 확인한다. Whisper 워커처럼 GUI 임포트 전에 실행한다.
    from core.bundle_import_self_test import run_bundle_import_self_test

    _worker_exit_code = run_bundle_import_self_test(sys.argv[2])
if _worker_exit_code is None:
    from core.app_version import dispatch_version_command

    _worker_exit_code = dispatch_version_command(sys.argv)
if _worker_exit_code is not None:
    raise SystemExit(_worker_exit_code)

from core.single_instance import ensure_single_instance, start_single_instance_server

import os
import logging
import faulthandler
from datetime import datetime
import warnings

# i18n 최우선 초기화 — 다른 모듈이 _() 를 사용하기 전에 호출
from i18n.translator import init as i18n_init, _, on_language_changed
i18n_init()

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
# ShowWindow(hwnd, SW_HIDE)만으로는 Windows Terminal에서 최소화 상태로만
# 남고 완전히 사라지지 않는 경우가 있어(콘솔 창을 소유한 것이 conhost가 아니라
# Windows Terminal 자체인 경우), 콘솔을 프로세스에서 완전히 분리하는
# FreeConsole()을 우선 시도하고, 실패 시에만 ShowWindow로 대체한다.
# pythonw.exe로 실행된 경우(콘솔 없음)에는 두 호출 모두 조용히 실패해도 무해하다.
if sys.platform == "win32":
    import ctypes
    if not ctypes.windll.kernel32.FreeConsole():
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

if sys.stderr is not None:
    faulthandler.enable()  # 네이티브 크래시(세그폴트 등) 발생 시 stderr에 스택 출력

# Qt보다 먼저 torch와 onnxruntime을 불러 Windows DLL 초기화 경합을 피한다.
# Qt가 먼저 올라오면 onnxruntime DLL 초기화가 실패해 로컬 임베더를 쓸 수 없다.
try:
    importlib.import_module("torch")
except (ImportError, OSError, RuntimeError) as exc:
    logging.debug("torch 사전 로드 생략: %s", exc)
try:
    importlib.import_module("onnxruntime")
except (ImportError, OSError, RuntimeError) as exc:
    logging.debug("onnxruntime 사전 로드 생략: %s", exc)

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMessageBox, QProgressDialog
from PySide6.QtGui import QIcon
from PySide6.QtCore import QEventLoop, QThread, Qt, QTimer

from assistant.ai_assistant import get_ai_assistant
from core.activity_monitor import ActivityMonitor
from core.config_manager import ConfigManager
from core.VoiceCommand import (
    _state,
    disable_game_mode,
    enable_game_mode,
    is_game_mode as get_game_mode_state,
    is_tts_playing as get_tts_playing_state,
    tts_wrapper,
    set_ai_assistant,
    set_character_widget,
    start_tts_background,
    set_session_locked,
    set_session_lock_monitoring_available,
    set_activity_quiet,
)
from ui.character_widget import CharacterWidget
from ui.text_interface import create_text_interface

from core.core_manager import AriCore
from core.app_version import is_release_build, record_last_run_version
from ui.tray_icon import SystemTrayIcon
from core.plugin_loader import PluginContext, get_plugin_manager
from commands.ai_command import AICommand
from agent.llm_provider import get_llm_provider
from agent.proactive_scheduler import get_scheduler
from core.window_inspector import (
    get_foreground_fullscreen,
    get_foreground_process_name,
)

# 전역 변수 선언
ai_assistant = None
icon_path = None

warnings.filterwarnings("ignore", category=FutureWarning)
os.environ["SDL_VIDEODRIVER"] = "dummy"


def _resolve_icon_path(log_missing: bool = False):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for name in ("icon.ico", "icon.png"):
        path = os.path.join(base_dir, name)
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
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    handlers = []
    log_error = None
    try:
        from core.resource_manager import ResourceManager
        log_dir = ResourceManager.get_writable_path("logs")
        os.makedirs(log_dir, exist_ok=True)
        _cleanup_old_logs(log_dir)

        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(log_dir, f"ari_log_{current_time}.log")
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    except OSError as exc:
        log_error = exc

    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    elif not handlers:
        handlers.append(logging.NullHandler())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )
    if log_error is not None:
        logging.warning("로그 파일을 만들 수 없습니다. 파일 로그 없이 계속 실행합니다: %s", log_error)

def check_cosyvoice_first_run(app):
    """최초 실행 시 CosyVoice 설치 여부 확인"""
    from core.resource_manager import ResourceManager
    FLAG_FILE = ResourceManager.get_writable_path(".cosyvoice_asked")
    from tts.cosyvoice_tts import _get_cosyvoice_dir_cached
    cosyvoice_dir = _get_cosyvoice_dir_cached()
    from core.cosyvoice_installer import (
        DEFAULT_COSYVOICE_DIR,
        is_cosyvoice_install_recorded,
        mark_cosyvoice_prompt_declined,
    )

    if is_cosyvoice_install_recorded(FLAG_FILE, cosyvoice_dir):
        return  # 이미 물어봤거나 설치됨 (설치가 중간에 끝난 경우만 다시 묻는다)

    msg = QMessageBox()
    msg.setWindowTitle(_("CosyVoice3 로컬 TTS"))
    msg.setText(
        _("로컬 TTS 엔진 CosyVoice3를 설치하시겠습니까?\n\n"
          "• 설치 시: 고품질 한국어 TTS 사용 가능 (GPU 권장, 약 2~5GB)\n"
          "• 미설치 시: Fish Audio API TTS 사용 (인터넷 필요)\n\n"
          "나중에 설치하려면 설정의 TTS 페이지에서 설치할 수 있습니다.")
    )
    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    msg.setDefaultButton(QMessageBox.No)
    msg.button(QMessageBox.Yes).setText(_("설치"))
    msg.button(QMessageBox.No).setText(_("나중에"))

    if msg.exec() != QMessageBox.Yes:
        mark_cosyvoice_prompt_declined(FLAG_FILE)
    else:
        import threading

        progress = QProgressDialog(_("CosyVoice3 설치 중...\n콘솔 창에서 진행 상황을 확인하세요."), None, 0, 0)
        progress.setWindowTitle(_("설치 중"))
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.show()
        app.processEvents()
        install_done = threading.Event()
        install_error = {"message": ""}
        installed_dir = {"path": ""}

        def run_install():
            try:
                from core.cosyvoice_installer import install_cosyvoice
                from core.config_manager import ConfigManager

                installed_dir["path"] = install_cosyvoice(
                    DEFAULT_COSYVOICE_DIR,
                    log=lambda message: logging.info("%s", message),
                )
                if not ConfigManager.set_value("cosyvoice_dir", installed_dir["path"]):
                    logging.warning("CosyVoice 설치 경로 설정을 저장하지 못했습니다.")
                from tts.cosyvoice_tts import _reset_cosyvoice_dir_cache

                _reset_cosyvoice_dir_cache()
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
                _("설치 실패"),
                _("CosyVoice3 설치 중 오류가 발생했습니다.\n{error}").format(error=install_error["message"]),
            )
        else:
            QMessageBox.information(
                None,
                _("설치 완료"),
                _("CosyVoice3 설치가 완료되었습니다.\n설정에서 TTS 모드를 '로컬 (CosyVoice3)'으로 변경하세요."),
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
    try:
        from agent.skill_manager import get_skill_manager

        get_skill_manager()
    except Exception as exc:
        logging.debug("스킬 매니저 초기화 생략: %s", exc)


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
        from agent.mcp_client import get_mcp_pool

        get_mcp_pool().close_all()
    except Exception as exc:
        logging.debug("MCP 세션 정리 생략: %s", exc)
    try:
        from memory.conversation_history import get_conversation_history
        get_conversation_history().flush()
    except Exception as exc:
        logging.debug("ConversationHistory flush 생략: %s", exc)

def main():
    global ai_assistant, icon_path
    ari_core = None
    character = None
    hotkey_filter = None
    tray_icon = None
    text_interface = None
    plugin_manager = None
    plugin_watcher = None
    plugin_flush_timer = None
    plugin_hot_reload_enabled = False
    mcp_server_thread = None
    telegram_bridge = None
    update_checker = None
    activity_monitor = None
    speech_scheduler = None
    mood_state = None

    def _show_character():
        if character is not None:
            character.show()
            character.raise_()

    if not ensure_single_instance(sys.argv):
        return

    try:
        setup_logging()
        record_last_run_version()
        icon_path = _resolve_icon_path(log_missing=True)
        logging.info("프로그램 시작")

        # 리소스 추출
        from core.resource_manager import ResourceManager, is_bundled
        logging.info("리소스 추출 확인 중...")
        ResourceManager.extract_resources()

        # 기분 상태는 선택 기능이므로 저장소 초기화에 실패해도 앱을 시작한다.
        mood_state = None
        try:
            from core.mood_state import initialize_mood_state

            mood_state = initialize_mood_state()
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
            logging.warning("기분 상태를 초기화하지 못했습니다: %s", exc)

        if sys.platform == "win32" and not is_bundled():
            # 소스 실행 시 작업 표시줄이 python.exe 아이콘으로 묶이지 않도록 앱 ID를 따로 둔다.
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DO0OG.Ari")
        app = QApplication(sys.argv)
        auto_game_mode_applied = False

        def _sync_activity_game_mode():
            nonlocal auto_game_mode_applied
            category_reactions_enabled = bool(
                ConfigManager.get("activity_app_category_reaction_enabled", False)
            )
            auto_enabled = bool(ConfigManager.get("activity_auto_game_mode_enabled", False))
            should_enable = (
                category_reactions_enabled
                and auto_enabled
                and activity_monitor.foreground_category in ("game", "video")
            )
            if should_enable and not auto_game_mode_applied and not get_game_mode_state():
                enable_game_mode()
                auto_game_mode_applied = get_game_mode_state()
            elif not should_enable and auto_game_mode_applied:
                disable_game_mode()
                auto_game_mode_applied = False

        # 활동 감지는 선택 기능이므로 실패해도 앱 시작을 막지 않는다.
        try:
            activity_monitor = ActivityMonitor()
            if mood_state is not None:
                try:
                    activity_monitor.user_returned.connect(
                        mood_state.record_away_return
                    )
                except (AttributeError, RuntimeError, TypeError) as exc:
                    logging.warning("기분 상태 활동 연결을 건너뜁니다: %s", exc)
            activity_monitor.session_locked.connect(lambda: set_session_locked(True))
            activity_monitor.session_unlocked.connect(lambda: set_session_locked(False))
            activity_monitor.quiet_state_changed.connect(
                lambda reason: set_activity_quiet(reason != "none")
            )
            lock_detection_available = activity_monitor.start()
            set_session_lock_monitoring_available(lock_detection_available)
            set_activity_quiet(activity_monitor.quiet_reason != "none")
            if not lock_detection_available:
                logging.error("세션 잠금 감지를 사용할 수 없어 웨이크 감지를 중지합니다.")
            activity_monitor.foreground_category_changed.connect(
                lambda _category: _sync_activity_game_mode()
            )
            activity_monitor.settings_refreshed.connect(_sync_activity_game_mode)
            _sync_activity_game_mode()
        except Exception as exc:
            activity_monitor = None
            logging.warning("활동 감지를 시작하지 못했습니다: %s", exc)
        start_single_instance_server(_show_character)
        if icon_path:
            app.setWindowIcon(QIcon(icon_path))

        # 최초 실행 시 CosyVoice 설치 여부 확인
        try:
            check_cosyvoice_first_run(app)
        except Exception as exc:
            logging.warning("CosyVoice 첫 실행 확인을 건너뜁니다: %s", exc)

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

        # 전역 오디오 초기화는 선택 기능이므로 장치/권한 오류로 앱 시작을 중단하지 않는다.
        from audio.audio_manager import initialize_global_audio
        initialize_global_audio()

        # TTS 백그라운드 초기화 시작 (CosyVoice 모델 로드를 미리 시작)
        try:
            start_tts_background()
        except Exception as exc:
            logging.error("TTS 초기화 실패; 음성 출력 기능을 사용할 수 없습니다: %s", exc)

        try:
            plugin_hot_reload_enabled = bool(
                ConfigManager.get("plugin_hot_reload_enabled", False)
            )
            if bool(ConfigManager.get("mcp_server_enabled", False)):
                from agent.mcp_server import start_mcp_server_background
                mcp_server_thread = start_mcp_server_background(
                    tts_wrapper,
                    int(ConfigManager.get("mcp_server_port", 8765) or 8765),
                )
        except Exception as exc:
            logging.debug("로컬 MCP 서버 시작 생략: %s", exc)

        scheduler = None
        try:
            scheduler = get_scheduler(tts_wrapper)
        except Exception as exc:
            logging.warning("예약 작업 초기화 실패; 예약 기능을 사용할 수 없습니다: %s", exc)

        try:
            from agent.agent_orchestrator import is_agent_running
            from agent.speech_scheduler import (
                EventSpeechScheduler,
                set_speech_scheduler,
            )

            def _get_speech_suggestions():
                suggestions = (
                    scheduler.get_proactive_suggestions()
                    if scheduler is not None
                    else []
                )
                if suggestions:
                    return suggestions
                from memory.user_context import get_context_manager

                context = get_context_manager()
                results = [
                    {"text": _("⏰ {command}").format(command=command), "goal": command}
                    for command in context.get_time_based_suggestions(limit=2)
                ]
                for command in context.get_predicted_next_commands()[:2]:
                    if not any(item["goal"] == command for item in results):
                        results.append(
                            {
                                "text": _("→ {command}").format(command=command),
                                "goal": command,
                            }
                        )
                return results

            def _speech_guard_state():
                monitor = activity_monitor
                category = monitor.foreground_category if monitor else None
                fullscreen = (
                    any(
                        monitor.foreground_covers(
                            screen.geometry().width(), screen.geometry().height()
                        )
                        for screen in app.screens()
                    )
                    if monitor is not None
                    else get_foreground_fullscreen() is True
                )
                foreground_process = get_foreground_process_name()
                own_process = os.path.basename(sys.executable).casefold()
                return {
                    "locked": monitor is None or monitor.session_is_locked,
                    "away": monitor is None or monitor.is_user_away,
                    "quiet": bool(
                        monitor is None
                        or monitor.quiet_reason != "none"
                        or category in ("game", "video")
                    ),
                    "fullscreen": fullscreen,
                    "game": get_game_mode_state() or category == "game",
                    "tts": get_tts_playing_state(),
                    "agent": is_agent_running(),
                    "other_window": bool(
                        foreground_process
                        and foreground_process.casefold() != own_process
                    ),
                }

            speech_scheduler = EventSpeechScheduler(
                tts_wrapper,
                guard_state=_speech_guard_state,
                suggestions_provider=_get_speech_suggestions,
                mood_provider=lambda: mood_state,
            )
            set_speech_scheduler(speech_scheduler)
        except Exception as exc:
            logging.warning("발화 스케줄러 초기화 실패; 발화 기능을 사용할 수 없습니다: %s", exc)

        if scheduler is not None:
            if activity_monitor is not None:
                scheduler.set_activity_state(
                    locked=activity_monitor.session_is_locked,
                    away=activity_monitor.is_user_away,
                    quiet=activity_monitor.quiet_reason != "none",
                )
                activity_monitor.session_locked.connect(
                    lambda: scheduler.set_activity_state(locked=True)
                )
                activity_monitor.session_unlocked.connect(
                    lambda: scheduler.set_activity_state(locked=False)
                )
                activity_monitor.user_away.connect(
                    lambda _seconds: scheduler.set_activity_state(away=True)
                )
                activity_monitor.user_returned.connect(
                    lambda _seconds: scheduler.set_activity_state(away=False)
                )
                activity_monitor.quiet_state_changed.connect(
                    lambda reason: scheduler.set_activity_state(quiet=reason != "none")
                )
            try:
                register_background_learning_tasks(scheduler)
            except Exception as exc:
                logging.debug("백그라운드 학습 작업 등록 생략: %s", exc)

        # 놓친 예약 작업 보충 실행 — TTS/오디오 초기화 완료 후 실행
        if scheduler is not None:
            try:
                scheduler.check_missed_tasks_on_startup()
            except Exception as exc:
                logging.debug("놓친 작업 확인 생략: %s", exc)

        # 캐릭터 위젯 생성
        logging.info("캐릭터 위젯 생성 시작")
        character = CharacterWidget(activity_monitor=activity_monitor)
        logging.info("캐릭터 위젯 생성 완료")
        set_character_widget(character)
        if activity_monitor is not None:
            def _report_activity_return(away_seconds):
                if away_seconds < 30 * 60:
                    return
                summary = (
                    scheduler.activity_return_summary(away_seconds)
                    if scheduler is not None
                    else ""
                )
                if speech_scheduler is not None:
                    speech_scheduler.request("return", summary=summary)

            activity_monitor.user_returned.connect(_report_activity_return)

            def _report_ide_long_use(duration_seconds):
                if duration_seconds < 3 * 60 * 60:
                    return
                if speech_scheduler is not None:
                    speech_scheduler.request("long_use")

            activity_monitor.ide_long_use_due.connect(_report_ide_long_use)

        voice_thread = getattr(ari_core, "voice_thread", None)
        if voice_thread is not None:
            character.voice_thread = voice_thread
            try:
                from ui.global_hotkey import GlobalVoiceHotkey

                hotkey_filter = GlobalVoiceHotkey(voice_thread)
                character.voice_hotkey_filter = hotkey_filter
                hotkey_filter.install(app)
            except Exception as exc:
                logging.error("전역 단축키 초기화 실패; 단축키 입력을 사용할 수 없습니다: %s", exc)

            def _show_microphone_unavailable() -> None:
                if (
                    voice_thread.microphone_available is False
                    and voice_thread.claim_microphone_unavailable_notification()
                ):
                    character.say(_("마이크를 찾을 수 없어 음성 인식을 사용할 수 없습니다. 설정에서 마이크를 지정해 주세요."))

            try:
                voice_thread.microphone_unavailable.connect(_show_microphone_unavailable)
                _show_microphone_unavailable()
            except Exception as exc:
                logging.warning("마이크 상태 안내 연결을 건너뜁니다: %s", exc)

        # 텍스트 인터페이스 생성 및 설정
        try:
            text_interface = create_text_interface(ai_assistant, tts_wrapper)
            character.set_text_interface(text_interface)
        except Exception as exc:
            text_interface = None
            logging.error("텍스트 인터페이스 초기화 실패; 텍스트 채팅을 사용할 수 없습니다: %s", exc)

        # 트레이 아이콘에 캐릭터 참조 및 텍스트 인터페이스 설정
        if use_system_tray and tray_icon:
            tray_icon.set_character_widget(character)
            tray_icon.set_text_interface(text_interface)
            # 캐릭터 우클릭 메뉴를 트레이 메뉴와 공유 (플러그인 액션 포함)
            character.set_tray_menu(tray_icon.menu)

        if is_release_build():
            from core.VoiceCommand import is_game_mode, is_tts_playing
            from core.update_checker import UpdateChecker

            def _is_update_notice_busy() -> bool:
                command_thread = getattr(ari_core, "command_thread", None)
                return is_tts_playing() or bool(
                    getattr(command_thread, "is_processing", False)
                )

            update_checker = UpdateChecker(
                tray_icon,
                character,
                is_busy=_is_update_notice_busy,
                is_game_mode=is_game_mode,
            )
            if tray_icon:
                tray_icon.set_update_checker(update_checker)
            update_checker.notify_installed_update()
            update_checker.start()

        # 언어 핫로드 콜백 등록 — 설정에서 언어 변경 시 UI 즉시 갱신
        _tray_ref = tray_icon
        _text_ref = text_interface

        def _on_language_changed():
            if _tray_ref:
                _tray_ref.refresh_language()
            if _text_ref:
                _text_ref.refresh_theme()

        on_language_changed(_on_language_changed)

        cmd_registry = _state.command_registry
        ai_command = next((cmd for cmd in getattr(cmd_registry, "commands", []) if isinstance(cmd, AICommand)), None)
        try:
            if ai_command is not None:
                from services.telegram_bridge import start_telegram_bridge

                telegram_bridge = start_telegram_bridge(ai_command.run_interaction)
        except Exception as exc:
            logging.debug("Telegram bridge startup skipped: %s", exc)

        def _register_tool_for_plugin(schema: dict, handler, intents=None) -> None:
            tool_name = str(schema.get("function", {}).get("name", "") or "")
            if not tool_name or ai_command is None:
                return
            if tool_name in ai_command._dispatch:
                logging.warning("[PluginLoader] 중복 도구 등록 거부: %s", tool_name)
                return
            get_llm_provider().register_plugin_tool(schema, intents=intents)
            ai_command.register_plugin_tool_handler(tool_name, handler)

        def _confirm_plugin_load(plugin_name: str) -> bool:
            if QThread.currentThread() != app.thread():
                logging.error("플러그인 승인 요청이 Qt 메인 스레드 밖에서 발생했습니다.")
                return False
            timer_active = bool(plugin_flush_timer and plugin_flush_timer.isActive())
            if timer_active:
                plugin_flush_timer.stop()
            try:
                result = QMessageBox.question(
                    app.activeWindow(),
                    _("플러그인 승인"),
                    _("새 플러그인 '{name}'을 켤까요?").format(name=plugin_name),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
            finally:
                if timer_active:
                    plugin_flush_timer.start(1000)
            return result == QMessageBox.Yes

        try:
            plugin_manager = get_plugin_manager()
            if cmd_registry and hasattr(cmd_registry, "set_event_emitter"):
                cmd_registry.set_event_emitter(plugin_manager.emit_event)
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
                    confirm_plugin_load=_confirm_plugin_load,
                )
            )
            logging.info("플러그인 로드 완료: %d개", len(plugin_manager.list_plugins()))
        except Exception as exc:
            plugin_manager = None
            logging.error("플러그인 초기화 실패; 플러그인을 사용할 수 없습니다: %s", exc)

        if plugin_manager is not None and plugin_hot_reload_enabled:
            try:
                from core.plugin_watcher import PluginWatcher

                plugin_watcher = PluginWatcher(plugin_manager.plugin_dir(), plugin_manager)
                plugin_watcher.start()
                plugin_flush_timer = QTimer()
                plugin_flush_timer.timeout.connect(plugin_watcher.flush)
                plugin_flush_timer.start(1000)
            except Exception as exc:
                logging.error("플러그인 감시 시작 실패: %s", exc)
        elif plugin_manager is not None:
            logging.info("플러그인 핫 리로드 꺼짐")

        # 메인 이벤트 루프 실행
        exit_code = app.exec()  # Qt 표준 이벤트 루프 사용
        logging.info("Application exited with code: %s", exit_code)

    except KeyboardInterrupt:
        logging.info("프로그램 종료")
    except Exception as e:
        logging.error("예외 발생: %s", e, exc_info=True)
    finally:
        logging.info("=== 앱 종료 시작 ===")
        if update_checker:
            update_checker.stop()
        if activity_monitor:
            activity_monitor.stop()
        if speech_scheduler is not None:
            try:
                from agent.speech_scheduler import set_speech_scheduler

                set_speech_scheduler(None)
            except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
                logging.debug("발화 스케줄러 정리를 건너뜁니다: %s", exc)
        flush_runtime_state()
        if hotkey_filter:
            try:
                hotkey_filter.cleanup()
            except (AttributeError, OSError, RuntimeError) as exc:
                logging.warning("전역 단축키 정리 실패: %s", exc)
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
        if telegram_bridge:
            telegram_bridge.stop()
        if mcp_server_thread:
            logging.debug("MCP 서버 스레드는 데몬으로 종료됩니다.")
        logging.info("=== 앱 종료 완료 ===")

if __name__ == "__main__":
    # 릴리스 워크플로는 묶음 결정 모델의 로드를 확인하려고 패키징된 실행 파일을 이 플래그와 함께 실행한다.
    # 콘솔이 없는 실행 파일이므로 결과는 파일에 기록한다.
    if len(sys.argv) == 3 and sys.argv[1] == "--decision-self-test":
        from agent.decision.self_test import run_self_test

        sys.exit(run_self_test(sys.argv[2]))
    main()

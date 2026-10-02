"""애플리케이션 전역 상태와 음성/TTS 오케스트레이션 헬퍼."""

import _ctypes
import logging
import inspect
import os
import re
import sys
import time
import threading
from collections import deque
from contextlib import nullcontext
from typing import TypedDict
import speech_recognition as sr

from core.resource_manager import is_bundled
from agent.assistant_text_utils import strip_trailing_symbol_tokens
from core.emotions import parse_emotion_text

# SSL 인증서 경로 설정 (PyInstaller/Nuitka 배포 환경)
if is_bundled():
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()

from core.rp_generator import RPGenerator
from core.constants import (
    SPEECH_TIMEOUT,
    SPEECH_PHRASE_LIMIT,
    SPEECH_REPEAT_SUPPRESSION_SECONDS,
    TTS_CHARS_PER_SECOND_BY_LANGUAGE,
    TTS_CHARS_PER_SECOND_DEFAULT,
    TTS_WAKE_GUARD_BUFFER_SECONDS,
)

# 모듈 및 오디오 관리
from audio.audio_manager import GlobalAudio
from commands.command_registry import CommandRegistry
from services.weather_service import WeatherService
from services.timer_manager import TimerManager
from i18n import translator
from i18n.translator import _


class LearningModeState(TypedDict):
    enabled: bool

class AppState:
    """앱 전체 가변 상태를 한 곳에서 관리하는 컨테이너."""
    def __init__(self):
        self.ai_assistant = None
        self.learning_mode: LearningModeState = {'enabled': False}
        self.fish_tts = None
        self.rp_gen = None
        self.character_widget = None
        self.command_registry = None
        self.tts_thread = None
        self.tts_signature = None
        self.tts_init_event = threading.Event()
        self.tts_playback_finished_event = threading.Event()
        self.tts_init_started = False
        self.game_mode = False
        self.last_bubble_signature = ("", 0.0)
        self.listening_indicator_active = False
        self.listening_indicator_text = _("말씀해주세요")
        self.tts_resume_guard_until = 0.0
        self.active_conversation_response = ""
        self.active_response_lock = threading.Lock()
        self.session_locked = False
        self.session_lock_monitoring_available = True
        self.activity_quiet = False

_state = AppState()
# 시작 시 초기화와 설정 저장의 재초기화가 겹쳐 프로바이더가 둘 생기지 않게 한다.
_TTS_INIT_LOCK = threading.Lock()
_LOCAL_TTS_CLEANUP_THREAD = None
_TTS_WAKE_GUARD_SECONDS = 1.2


def _tts_wake_guard_seconds() -> float:
    try:
        from core.config_manager import ConfigManager
        return float(ConfigManager.get("tts_wake_guard_seconds", _TTS_WAKE_GUARD_SECONDS) or _TTS_WAKE_GUARD_SECONDS)
    except Exception:
        return _TTS_WAKE_GUARD_SECONDS


class SharedMicrophone(sr.Microphone):
    """전역 PyAudio 인스턴스를 공유하는 마이크 클래스.

    sr.Microphone은 생성·열기·닫기마다 PyAudio()를 새로 만들고 terminate()한다.
    PortAudio 초기화·종료는 스레드 안전하지 않아 다른 스레드의 오디오 사용과
    겹치면 네이티브 크래시가 나므로, 전역 인스턴스만 쓰고 종료는 앱 정리 때 한 번만 한다.
    """
    # sr.Microphone.__init__은 임시 PyAudio를 만들고 terminate()하므로 호출하지 않는다.
    def __init__(  # pylint: disable=super-init-not-called
        self, device_index=None, sample_rate=None, chunk_size=1024,
    ):
        if device_index is not None and not isinstance(device_index, int):
            raise ValueError("Device index must be None or an integer")
        if sample_rate is not None and (not isinstance(sample_rate, int) or sample_rate <= 0):
            raise ValueError("Sample rate must be None or a positive integer")
        if not isinstance(chunk_size, int) or chunk_size <= 0:
            raise ValueError("Chunk size must be a positive integer")

        pyaudio_module = self.get_pyaudio()
        audio = GlobalAudio.get_instance()
        count = audio.get_device_count()
        if device_index is not None and not 0 <= device_index < count:
            raise OSError(f"Device index out of range ({count} devices available)")
        if sample_rate is None:
            # 기본 입력 장치가 없으면 PyAudio가 OSError를 낸다.
            device_info = (
                audio.get_device_info_by_index(device_index)
                if device_index is not None
                else audio.get_default_input_device_info()
            )
            default_rate = device_info.get("defaultSampleRate")
            if not isinstance(default_rate, (float, int)) or default_rate <= 0:
                raise OSError(f"Invalid device info returned from PyAudio: {device_info}")
            sample_rate = int(default_rate)

        self.device_index = device_index
        self.format = pyaudio_module.paInt16
        self.SAMPLE_WIDTH = pyaudio_module.get_sample_size(self.format)
        self.SAMPLE_RATE = sample_rate
        self.CHUNK = chunk_size
        self.audio = None
        self.stream = None

    def __enter__(self):
        if self.stream is not None:
            raise RuntimeError("This audio source is already inside a context manager")
        self.audio = GlobalAudio.get_instance()
        try:
            self.stream = sr.Microphone.MicrophoneStream(
                GlobalAudio.open_stream(
                    input_device_index=self.device_index, channels=1, format=self.format,
                    rate=self.SAMPLE_RATE, frames_per_buffer=self.CHUNK, input=True,
                )
            )
        except (OSError, ValueError) as exc:
            # stream을 None으로 남겨 호출자가 OSError로 처리하게 한다.
            logging.debug("마이크 스트림 열기 실패: %s", exc)
            self.stream = None
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if self.stream is not None:
                GlobalAudio.close_stream(self.stream.pyaudio_stream)
                self.stream.pyaudio_stream = None
        finally:
            self.stream = None
            self.audio = None


def list_microphone_names() -> list:
    """전역 PyAudio 인스턴스로 오디오 장치 이름 목록을 반환한다."""
    audio = GlobalAudio.get_instance()
    return [
        audio.get_device_info_by_index(index).get("name")
        for index in range(audio.get_device_count())
    ]


# ── 초기화 및 설정 ───────────────────────────────────────────────────────────

def set_tts_thread(thread: object) -> None:
    _state.tts_thread = thread


def set_ai_assistant(assistant: object) -> None:
    _state.ai_assistant = assistant
    if _state.command_registry:
        from commands.ai_command import AICommand
        for i, cmd in enumerate(_state.command_registry.commands):
            if isinstance(cmd, AICommand):
                _state.command_registry.commands[i] = AICommand(
                    ai_assistant=assistant,
                    tts_func=tts_wrapper,
                    learning_mode_ref=_state.learning_mode
                )
                break


def set_character_widget(widget: object) -> None:
    _state.character_widget = widget
    
    # 오케스트레이터 생각 중 상태 연결
    try:
        from agent.agent_orchestrator import get_orchestrator
        orch = get_orchestrator()
        orch.set_thinking_callback(widget.thinking_signal.emit)
    except Exception as e:
        logging.warning("오케스트레이터 생각 콜백 연결 실패: %s", e)
        
    reconnect_tts_signals()


def start_tts_background():
    if _state.tts_init_started:
        return
    _state.tts_init_started = True

    try:
        from core.config_manager import ConfigManager
        with _TTS_INIT_LOCK:
            tts_mode = _effective_tts_settings(ConfigManager.load_settings()).get("tts_mode", "fish")

        if tts_mode == "local":
            def _run():
                try:
                    initialize_tts()
                    _state.tts_init_event.set()
                    tts_wrapper(_("로딩이 완료되었습니다. 이제 대화할 수 있어요!"))
                except Exception as e:
                    logging.error("TTS 초기화 실패: %s", e)
                    _state.tts_init_event.set()

            threading.Thread(target=_run, daemon=True).start()
        else:
            try:
                initialize_tts()
            except Exception as e:
                logging.error("TTS 초기화 실패 (동기): %s", e)
            finally:
                _state.tts_init_event.set()
    except Exception as e:
        logging.error("TTS 초기화 준비 실패: %s", e, exc_info=True)
        _state.tts_init_event.set()


def _cleanup_tts_provider(provider) -> None:
    if provider is not None and hasattr(provider, "cleanup"):
        try:
            provider.cleanup()
        except Exception as exc:
            logging.debug("TTS 프로바이더 정리 중 무시된 오류: %s", exc)


def _cleanup_tts_provider_async(provider, local=False):
    global _LOCAL_TTS_CLEANUP_THREAD
    if provider is None or not hasattr(provider, "cleanup"):
        return None
    thread = threading.Thread(
        target=_cleanup_tts_provider,
        args=(provider,),
        daemon=True,
        name="TTS-Cleanup",
    )
    if local:
        _LOCAL_TTS_CLEANUP_THREAD = thread
    thread.start()
    return thread


def _effective_tts_settings(settings: dict) -> dict:
    effective = dict(settings)
    if _state.game_mode:
        effective["tts_mode"] = "edge"
    return effective


def _create_fallback_tts(settings: dict):
    from tts.tts_factory import create_tts_provider
    fallback = settings.get("tts_fallback_provider", "edge")
    if fallback == settings.get("tts_mode"):
        fallback = "edge"
    fallback_settings = dict(settings)
    fallback_settings["tts_mode"] = fallback
    logging.warning("[TTS] 폴백으로 전환: %s", fallback)
    return create_tts_provider(fallback_settings)[0]


def initialize_tts():
    from core.config_manager import ConfigManager
    from tts.tts_factory import create_tts_provider, build_tts_signature
    warming_provider = None
    old_provider = None
    old_provider_was_local = False
    # 로컬 엔진끼리는 GPU 자원을 공유하므로 이전 워커 종료 후 새 워커를 만든다.
    with _TTS_INIT_LOCK:
        settings = _effective_tts_settings(ConfigManager.load_settings())
        next_signature = build_tts_signature(settings)
        if _state.fish_tts is not None and _state.tts_signature == next_signature:
            logging.info("TTS 설정 변경 없음 - 기존 프로바이더 재사용")
        else:
            current_provider = _state.fish_tts
            old_provider_was_local = bool(
                _state.tts_signature and _state.tts_signature[0] == "local"
            )
            local_provider_cleaned = False
            if (
                current_provider is not None
                and _state.tts_signature is not None
                and _state.tts_signature[0] == "local"
                and next_signature[0] == "local"
            ):
                _cleanup_tts_provider(current_provider)
                _state.fish_tts = None
                local_provider_cleaned = True
            try:
                provider, provider_mode = create_tts_provider(settings, wait_ready=False)
                # 준비 중에도 등록해 둔다. 로컬 엔진의 speak()는 READY까지 기다린다.
                _state.fish_tts = provider
                old_provider = (
                    None
                    if local_provider_cleaned or current_provider is _state.fish_tts
                    else current_provider
                )
                if provider_mode == "local" and hasattr(provider, "wait_until_warmup_done"):
                    warming_provider = provider
            except (ImportError, OSError, RuntimeError, ValueError) as exc:
                logging.error("[TTS] 기본 프로바이더 초기화 실패: %s", exc)
                if _state.game_mode:
                    raise
                _state.fish_tts = _create_fallback_tts(settings)
                old_provider = (
                    None
                    if local_provider_cleaned or current_provider is _state.fish_tts
                    else current_provider
                )
            _state.tts_signature = next_signature
        _finish_tts_setup(settings)

    _cleanup_tts_provider_async(old_provider, local=old_provider_was_local)

    if warming_provider is not None and not (
        warming_provider.wait_until_ready() and warming_provider.wait_until_warmup_done()
    ):
        reason = (
            getattr(warming_provider, "_warmup_error", None)
            or getattr(warming_provider, "_worker_error", None)
            or "CosyVoice3 warmup did not complete"
        )
        logging.error("[TTS] 기본 프로바이더 초기화 실패: %s", reason)
        old_provider = None
        with _TTS_INIT_LOCK:
            if (
                _state.fish_tts is not warming_provider
                or getattr(warming_provider, "_stopping", False) is True
            ):
                # 그사이 다른 초기화나 게임 모드 전환이 프로바이더를 교체·정리했다.
                return
            old_provider = _state.fish_tts
            _state.fish_tts = None
            _state.tts_signature = None
            try:
                fallback_provider = _create_fallback_tts(settings)
            except Exception:
                _cleanup_tts_provider_async(old_provider)
                raise
            _state.fish_tts = fallback_provider
            _state.tts_signature = next_signature
            _finish_tts_setup(settings)
        _cleanup_tts_provider_async(old_provider)


def _finish_tts_setup(settings: dict) -> None:
    if _state.character_widget and hasattr(_state.fish_tts, 'playback_finished'):
        try:
            try:
                _state.fish_tts.playback_finished.disconnect(_handle_tts_playback_finished)
            except (AttributeError, RuntimeError, TypeError) as exc:
                logging.debug("기존 TTS 시그널 분리 생략: %s", exc)
            _state.fish_tts.playback_finished.connect(_handle_tts_playback_finished)
        except (AttributeError, RuntimeError, TypeError) as exc:
            logging.debug("TTS 시그널 연결 실패: %s", exc)

    if hasattr(_state.fish_tts, "schedule_fixed_message_cache_warmup"):
        _state.fish_tts.schedule_fixed_message_cache_warmup(
            is_idle=lambda: not is_tts_playing()
        )

    _state.rp_gen = RPGenerator()
    _state.rp_gen.set_config(
        personality=settings.get("personality", ""),
        scenario=settings.get("scenario", ""),
        system_prompt=settings.get("system_prompt", ""),
        history_instruction=settings.get("history_instruction", ""),
        response_verbosity=settings.get("response_verbosity", "concise"),
    )


def reconnect_tts_signals():
    """현재 TTS 프로바이더와 캐릭터 위젯 시그널을 다시 연결."""
    if not _state.fish_tts or not _state.character_widget or not hasattr(_state.fish_tts, 'playback_finished'):
        return
    try:
        try:
            _state.fish_tts.playback_finished.disconnect(_handle_tts_playback_finished)
        except (AttributeError, RuntimeError, TypeError) as exc:
            logging.debug("기존 재생 완료 시그널 해제 생략: %s", exc)
        _state.fish_tts.playback_finished.connect(_handle_tts_playback_finished)
    except (AttributeError, RuntimeError, TypeError) as e:
        logging.debug("TTS 시그널 재연결 실패: %s", e)


# ── 실행 로직 ───────────────────────────────────────────────────────────────

def _show_tts_bubble(text, duration: int = 0):
    """어떤 TTS 경로든 동일한 말풍선을 표시하되, 직전 중복 표시는 짧게 억제."""
    _, pure_text = parse_emotion_text(text)
    display_text = strip_trailing_symbol_tokens(pure_text or text)
    now = time.monotonic()
    last_text, last_ts = _state.last_bubble_signature
    if display_text == last_text and (now - last_ts) < 0.5:
        return
    _state.last_bubble_signature = (display_text, now)
    if _state.character_widget:
        _state.character_widget.say(display_text, duration=duration)


def _show_listening_bubble() -> None:
    if _state.character_widget:
        _state.character_widget.say(_state.listening_indicator_text, duration=0)


def set_listening_indicator(active: bool, text: str | None = None) -> None:
    """음성 인식 대기 상태 말풍선을 제어한다."""
    if text:
        _state.listening_indicator_text = text
    _state.listening_indicator_active = active

    if not _state.character_widget:
        return

    if active:
        _show_listening_bubble()
    elif not is_tts_playing():
        _state.character_widget.hide_speech_bubble()


def _estimate_tts_duration(text: str) -> float:
    """오디오 길이를 알 수 없는 TTS 제공자를 위한 보수적 재생 시간 추정."""
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return _tts_wake_guard_seconds()
    language = translator.get_language().split("-", 1)[0].split("_", 1)[0].lower()
    chars_per_second = TTS_CHARS_PER_SECOND_BY_LANGUAGE.get(
        language,
        TTS_CHARS_PER_SECOND_DEFAULT,
    )
    return max(
        _tts_wake_guard_seconds(),
        min(30.0, len(normalized) / chars_per_second),
    )


def emit_plugin_event(event_name: str, payload: dict | None = None) -> None:
    """플러그인 이벤트 버스가 준비된 경우 이벤트를 발행한다."""
    try:
        from core.plugin_loader import get_plugin_manager
        get_plugin_manager().emit_event(event_name, payload or {})
    except Exception as exc:
        logging.debug("플러그인 이벤트 발행 생략 (%s): %s", event_name, exc)


def extend_tts_resume_guard(duration: float | None = None) -> None:
    """TTS 재생 예상 시간(초)과 버퍼를 반영해 웨이크워드 보호 구간을 연장한다."""
    if duration is None:
        duration = _tts_wake_guard_seconds()
    guard_duration = max(0.0, duration) + TTS_WAKE_GUARD_BUFFER_SECONDS
    _state.tts_resume_guard_until = max(
        _state.tts_resume_guard_until,
        time.monotonic() + guard_duration,
    )


def _handle_tts_playback_finished() -> None:
    """TTS 종료 후 현재 상태에 맞게 말풍선을 정리한다."""
    if is_tts_playing():
        return
    _state.tts_playback_finished_event.set()
    _state.tts_resume_guard_until = (
        time.monotonic() + TTS_WAKE_GUARD_BUFFER_SECONDS
    )
    with _state.active_response_lock:
        _state.active_conversation_response = ""
    emit_plugin_event("on_tts_end", {})
    emit_plugin_event("tts.playback.finished", {})

    if _state.listening_indicator_active:
        _show_listening_bubble()
    elif _state.character_widget:
        _state.character_widget.hide_speech_bubble()


def set_active_conversation_response(text: str) -> None:
    """현재 재생 중인 대화 응답을 기록한다."""
    with _state.active_response_lock:
        _state.active_conversation_response = str(text or "")


def _stop_active_llm_stream() -> bool:
    assistant = _state.ai_assistant
    if not hasattr(assistant, "stop_stream"):
        return False
    try:
        return bool(assistant.stop_stream())
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        logging.debug("LLM 스트림 중단 생략: %s", exc)
        return False


def stop_speaking() -> bool:
    """재생·생성 중인 응답과 대기열을 중단한다."""
    was_playing = is_tts_playing()
    turn_cancelled = False
    registry = _state.command_registry
    if registry is not None:
        for command in getattr(registry, "commands", ()):
            cancel = getattr(command, "cancel_current_response", None)
            if callable(cancel):
                turn_cancelled = bool(cancel()) or turn_cancelled

    stream_stopped = _stop_active_llm_stream()
    thread = _state.tts_thread
    current_text = str(getattr(thread, "current_text", "") or "").strip()
    removed_count = thread.clear() if hasattr(thread, "clear") else 0
    if was_playing:
        with _state.active_response_lock:
            full_response = _state.active_conversation_response.strip()
            response = full_response
        if full_response and current_text:
            current_position = response.find(current_text)
            if current_position >= 0:
                response = response[:current_position + len(current_text)].strip()
        if full_response and response:
            interrupted_response = f"{response}\n\n{_('(응답 중단)')}"
            try:
                from memory.conversation_history import get_conversation_history

                get_conversation_history().mark_last_response_interrupted(
                    full_response,
                    interrupted_response,
                )
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
                logging.debug("중단된 대화 기록 갱신 생략: %s", exc)

            assistant = _state.ai_assistant
            if hasattr(assistant, "mark_last_response_interrupted"):
                try:
                    assistant.mark_last_response_interrupted(
                        full_response,
                        interrupted_response,
                    )
                except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
                    logging.debug("LLM 대화 기록 갱신 생략: %s", exc)

    provider = _state.fish_tts
    if hasattr(provider, "stop"):
        try:
            provider.stop()
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            logging.debug("TTS 재생 중단 생략: %s", exc)
    else:
        stop_event = getattr(provider, "stop_event", None)
        if callable(getattr(stop_event, "set", None)):
            stop_event.set()

    _state.tts_resume_guard_until = (
        time.monotonic() + TTS_WAKE_GUARD_BUFFER_SECONDS
    )
    did_stop = was_playing or bool(removed_count) or turn_cancelled or stream_stopped
    if (was_playing or removed_count) and not is_tts_playing():
        _handle_tts_playback_finished()
    with _state.active_response_lock:
        _state.active_conversation_response = ""
    if _state.character_widget:
        text_interface = getattr(_state.character_widget, "text_interface", None)
        mark_stopped = getattr(text_interface, "_mark_speaking_stopped", None)
        if callable(mark_stopped):
            mark_stopped()
        reset_stream = getattr(_state.character_widget, "_reset_stream_buffer", None)
        if callable(reset_stream):
            reset_stream()
        if _state.listening_indicator_active:
            _show_listening_bubble()
        else:
            _state.character_widget.hide_speech_bubble()
    return did_stop


def _quiet_bubble_only_enabled() -> bool:
    if not _state.activity_quiet:
        return False
    from core.config_manager import ConfigManager

    return bool(ConfigManager.get("activity_quiet_bubble_only_enabled", False))


def text_to_speech(
    text: str,
    show_bubble: bool = True,
    stop_event: threading.Event | None = None,
) -> bool:
    """TTS로 음성 출력 (최종 최적화 버전)"""
    if stop_event is not None and stop_event.is_set():
        return False
    emotion, text = parse_emotion_text(text)
    text = strip_trailing_symbol_tokens(text)

    if _quiet_bubble_only_enabled():
        if _state.character_widget:
            _state.character_widget.set_emotion(emotion)
            if show_bubble:
                _show_tts_bubble(text)
        return True

    if _state.character_widget:
        _state.character_widget.set_emotion(emotion)
        if show_bubble:
            _show_tts_bubble(text)

    if _state.fish_tts is None:
        if _state.tts_init_started:
            if not _state.tts_init_event.wait(timeout=10.0):
                logging.warning("TTS 초기화 대기 타임아웃")
                if show_bubble and _state.character_widget:
                    _handle_tts_playback_finished()
                return False
        else:
            initialize_tts()

    if _state.fish_tts is None:
        logging.error("TTS 프로바이더가 없습니다.")
        if show_bubble and _state.character_widget:
            _handle_tts_playback_finished()
        return False

    if stop_event is not None and stop_event.is_set():
        return False

    try:
        if _state.rp_gen:
            text = _state.rp_gen.generate(text)
        estimated_duration = _estimate_tts_duration(text)
        extend_tts_resume_guard(estimated_duration)
        emit_plugin_event(
            "tts.playback.started",
            {"text": text, "estimated_duration": estimated_duration},
        )
        emit_plugin_event("on_tts_start", {"text": text, "estimated_duration": estimated_duration})
        speak = _state.fish_tts.speak
        speak_kwargs = {"emotion": emotion}
        if stop_event is not None:
            try:
                if "stop_event" in inspect.signature(speak).parameters:
                    speak_kwargs["stop_event"] = stop_event
            except (TypeError, ValueError):
                pass
        ok = speak(text, **speak_kwargs)
        if not ok and show_bubble and _state.character_widget:
            _handle_tts_playback_finished()
        return ok
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as e:
        logging.error("TTS 오류: %s", e)
        if show_bubble and _state.character_widget:
            _handle_tts_playback_finished()
        return False


def play_cached_tts(
    text: str,
    request_cancel_event: threading.Event | None = None,
) -> bool:
    """이미 합성된 Edge TTS 문구만 재생한다."""
    provider = _state.fish_tts
    if not hasattr(provider, "speak_cached"):
        return False
    emotion, text = parse_emotion_text(text)
    text = strip_trailing_symbol_tokens(text)
    try:
        return bool(
            provider.speak_cached(
                text,
                emotion=emotion,
                request_cancel_event=request_cancel_event,
            )
        )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        logging.debug("TTS 캐시 문구 재생을 건너뜁니다: %s", exc)
        return False


def tts_wrapper(text: str, show_bubble: bool = True) -> None:
    """TTS 재생 + 말풍선 표시 (감정 이모지 및 동기화 최적화)"""
    if _quiet_bubble_only_enabled():
        if show_bubble and _state.character_widget:
            _show_tts_bubble(text)
        return
    if _state.tts_thread:
        queued = _state.tts_thread.speak(text)
        if queued and show_bubble:
            _show_tts_bubble(text)
            emit_plugin_event("on_tts_start", {"text": text, "queued": True})
        elif not queued and _state.character_widget:
            _handle_tts_playback_finished()
    else:
        text_to_speech(text, show_bubble=show_bubble)


def is_tts_playing() -> bool:
    """현재 TTS가 큐 대기 중, 처리 중, 또는 재생 중인지 확인"""
    if _state.tts_thread:
        if not _state.tts_thread.queue.empty():
            return True
        if getattr(_state.tts_thread, 'is_processing', False):
            return True
    if _state.fish_tts and getattr(_state.fish_tts, 'is_playing', False):
        return True
    return False


def is_session_lock_blocked() -> bool:
    """잠금 상태이거나 잠금 감지를 사용할 수 없으면 참을 반환한다."""
    return _state.session_locked or (
        sys.platform == "win32" and not _state.session_lock_monitoring_available
    )


def should_pause_wake_detection(now: float | None = None) -> bool:
    """잠금·TTS 재생 중이거나 직후 보호 구간이면 웨이크 감지를 멈춘다."""
    if is_session_lock_blocked():
        return True
    if is_tts_playing():
        return True
    current = time.monotonic() if now is None else now
    return current < _state.tts_resume_guard_until


def set_session_locked(locked: bool) -> None:
    _state.session_locked = bool(locked)


def set_session_lock_monitoring_available(available: bool) -> None:
    _state.session_lock_monitoring_available = bool(available)


def set_activity_quiet(quiet: bool) -> None:
    _state.activity_quiet = bool(quiet)


def execute_command(command):
    if _state.command_registry:
        _state.command_registry.execute(command)


# ── 스레드용 헬퍼 함수 ────────────────────────────────────────────────────────

def get_microphone_index_helper(microphone_name):
    if not microphone_name:
        return None
    for index, name in enumerate(list_microphone_names()):
        if name and microphone_name in name:
            return index
    return None


class _PushToTalkAudioStream:
    def __init__(self, stream, released, sample_rate, sample_width):
        self._stream = stream
        self._released = released
        self._sample_rate = sample_rate
        self._sample_width = sample_width

    def read(self, size):
        if self._released.is_set():
            time.sleep(size / self._sample_rate)
            return bytes(size * self._sample_width)
        audio = self._stream.read(size)
        if self._released.is_set():
            return bytes(size * self._sample_width)
        return audio


def recognize_speech_helper(
    recognizer,
    source,
    signal,
    stt_provider=None,
    previous_texts=None,
    continue_check=None,
    push_to_talk_released=None,
    source_context=None,
) -> str | None:
    audio_capture_active = source_context is not None
    try:
        if continue_check is not None and not continue_check():
            return None
        logging.info("말씀해 주세요...")
        source_manager = source_context() if source_context is not None else nullcontext(source)
        with source_manager as source:
            original_stream = None
            if push_to_talk_released is not None:
                original_stream = source.stream
                source.stream = _PushToTalkAudioStream(
                    original_stream,
                    push_to_talk_released,
                    source.SAMPLE_RATE,
                    source.SAMPLE_WIDTH,
                )
            try:
                audio = recognizer.listen(
                    source,
                    timeout=SPEECH_TIMEOUT,
                    phrase_time_limit=SPEECH_PHRASE_LIMIT,
                )
            finally:
                if original_stream is not None:
                    source.stream = original_stream
        audio_capture_active = False
        if continue_check is not None and not continue_check():
            return None
        provider = stt_provider
        if provider is None:
            from core.config_manager import ConfigManager
            from core.stt_provider import create_stt_provider

            provider = create_stt_provider(ConfigManager.load_settings())
        if continue_check is not None and not continue_check():
            return None
        text = provider.transcribe(audio, mode="command")
        if continue_check is not None and not continue_check():
            return None
        if not text:
            logging.warning("음성 인식 불가")
            return
        text = text.strip()
        if len(text) < 2:
            logging.debug("[STT] 너무 짧은 인식 결과 무시 (%d자)", len(text))
            return
        history = previous_texts if previous_texts is not None else deque(maxlen=3)
        current_time = time.monotonic()
        if history and history[-1][0] == text:
            previous_time = history[-1][1]
            if current_time - previous_time < SPEECH_REPEAT_SUPPRESSION_SECONDS:
                logging.debug("[STT] 반복 명령 무시 (%d자)", len(text))
                return _("같은 명령을 방금 들어서 무시했어요.")
        history.clear()
        history.append((text, current_time))
        logging.info("인식된 텍스트 수신 (%d자)", len(text))
        signal.emit(text)
    except sr.WaitTimeoutError:
        logging.debug("음성 입력 시간이 초과되었습니다.")
    except sr.UnknownValueError:
        logging.warning("음성 인식 불가")
    except (sr.RequestError, OSError, RuntimeError, ValueError) as e:
        if audio_capture_active:
            raise
        logging.error("음성 인식 오류: %s", e)
    return None


def wake_detector_recalibrate_helper(detector, source):
    try:
        detector.recalibrate(source)
    except (AttributeError, OSError, RuntimeError) as exc:  # nosec B110
        logging.debug("웨이크 디텍터 재보정 실패, 계속 진행: %s", exc)
        pass


# ── 모듈 초기화 ──────────────────────────────────────────────────────────────

weather_service = WeatherService(api_key="")
timer_manager = TimerManager(tts_callback=lambda text: tts_wrapper(text=text))

# 스피커가 없으면 pycaw는 OSError가 아닌 COMError를 낸다. COMError는 Windows에만 있다.
_COM_ERROR = getattr(_ctypes, "COMError", OSError)
_com_thread_state = threading.local()


def adjust_volume(change, *, amount=None, announce=True):
    """시스템 볼륨을 수치 또는 방향과 백분율로 조절한다."""
    try:
        from ctypes import cast, POINTER
        import comtypes
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        # 볼륨 조절은 여러 워커 스레드에서 불리는데 comtypes는 처음 import한 스레드만 COM을 초기화한다.
        # ponytail: 스레드마다 한 번만 초기화하고 해제하지 않는다.
        # 해제 뒤 COM 포인터가 늦게 풀리면 크래시가 날 수 있어서다.
        if not getattr(_com_thread_state, "initialized", False):
            comtypes.CoInitialize()
            _com_thread_state.initialized = True

        mute = False
        unmute = False
        if isinstance(change, bool):
            raise ValueError("invalid volume change")
        if isinstance(change, (int, float)):
            delta = float(change)
        elif isinstance(change, str):
            normalized = change.strip().casefold()
            if normalized in {"mute", "음소거", "ミュート"}:
                mute = True
                delta = 0.0
            elif normalized in {"unmute", "음소거 해제", "ミュート解除"}:
                unmute = True
                delta = 0.0
            elif normalized in {"up", "올려", "上げて", "down", "줄여", "下げて"}:
                sign = 1.0 if normalized in {"up", "올려", "上げて"} else -1.0
                if amount in (None, ""):
                    step = 10.0
                elif isinstance(amount, bool):
                    raise ValueError("invalid volume amount")
                else:
                    step = float(str(amount).strip().rstrip("%"))
                    if not 1.0 <= step <= 100.0:
                        raise ValueError("invalid volume amount")
                delta = sign * (step / 100.0)
            else:
                delta = float(normalized)
        else:
            delta = float(change)

        if not (mute or unmute) and not (-1.0 <= delta <= 1.0):
            raise ValueError("volume change out of range")

        devices = AudioUtilities.GetSpeakers()
        # 새 pycaw의 GetSpeakers()는 Activate 대신 EndpointVolume 속성을 가진 장치 객체를 돌려준다.
        volume = getattr(devices, "EndpointVolume", None)
        if volume is None:
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
        if mute:
            volume.SetMute(1, None)
            if announce:
                tts_wrapper(_("음소거했습니다."))
            return True
        if unmute:
            volume.SetMute(0, None)
            if announce:
                tts_wrapper(_("음소거를 해제했습니다."))
            return True
        curr = volume.GetMasterVolumeLevelScalar()
        new_v = max(0.0, min(1.0, curr + delta))
        volume.SetMasterVolumeLevelScalar(new_v, None)
        if announce:
            tts_wrapper(_("볼륨을 {volume}%로 조절했습니다.").format(volume=int(new_v * 100)))
        return True
    except (
        AttributeError,
        ImportError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        _COM_ERROR,
    ) as exc:
        logging.warning("시스템 볼륨 조절 실패: %s", exc)
        if announce:
            tts_wrapper(_("볼륨 조절 실패"))
        return False

_state.command_registry = CommandRegistry(
    ai_assistant=None,
    weather_service=weather_service,
    timer_manager=timer_manager,
    adjust_volume_func=adjust_volume,
    tts_func=tts_wrapper,
    learning_mode_ref=_state.learning_mode
)

# ── 게임 모드 ─────────────────────────────────────────────────────────────────

def enable_game_mode():
    """게임 모드 활성화: GPU TTS를 정리하고 Edge TTS로 전환해 VRAM을 확보한다."""
    if _state.game_mode:
        return

    with _TTS_INIT_LOCK:
        _state.game_mode = True
    try:
        initialize_tts()
        reconnect_tts_signals()
        emit_plugin_event("on_game_mode_change", {"enabled": True})
        logging.info("게임 모드 활성화: Edge TTS로 전환, GPU 메모리 해제됨")
    except Exception as e:
        logging.error("게임 모드 전환 실패: %s", e)
        with _TTS_INIT_LOCK:
            _state.game_mode = False


def disable_game_mode():
    """게임 모드 비활성화: Fish Audio 해제 → 원래 TTS(CosyVoice3 등)로 복원"""
    if not _state.game_mode:
        return

    with _TTS_INIT_LOCK:
        old_provider = _state.fish_tts
        _state.fish_tts = None
        _state.tts_signature = None
        _state.game_mode = False
        # 복원이 끝날 때까지 들어오는 발화가 버려지지 않고 기다리게 한다.
        _state.tts_init_event.clear()
    _cleanup_tts_provider_async(old_provider)
    emit_plugin_event("on_game_mode_change", {"enabled": False})

    def _reinit():
        try:
            cleanup_thread = _LOCAL_TTS_CLEANUP_THREAD
            if cleanup_thread is not None:
                cleanup_thread.join(timeout=5)
            initialize_tts()
        except Exception as e:
            logging.error("TTS 복원 실패: %s", e)
            return
        finally:
            _state.tts_init_event.set()
        tts_wrapper(_("게임 모드 해제. 원래 TTS로 복원되었습니다."))

    threading.Thread(target=_reinit, daemon=True, name="TTS-GameModeRestore").start()
    logging.info("게임 모드 비활성화: 원래 TTS 복원 중")


def is_game_mode() -> bool:
    return _state.game_mode


# ── 하위 호환 모듈 수준 별칭 ──────────────────────────────────────────────────
# 이전에 모듈 전역으로 노출됐던 이름들. 같은 객체를 가리키므로 변경이 양쪽에 반영됨.
learning_mode = _state.learning_mode          # dict, 재할당 없음 → 안전한 별칭
_tts_init_event = _state.tts_init_event       # threading.Event, 재할당 없음 → 안전한 별칭


import logging
import os
import sys
import time
import warnings
import random
import threading
from collections import deque
from typing import Any, Optional, Tuple
import speech_recognition as sr

# SSL 인증서 경로 설정 (PyInstaller 환경)
if getattr(sys, 'frozen', False):
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()

from PySide6.QtCore import Signal
from core.rp_generator import RPGenerator
from core.constants import (
    SPEECH_LANGUAGE, SPEECH_TIMEOUT, SPEECH_PHRASE_LIMIT, AMBIENT_NOISE_DURATION
)

# 모듈 및 오디오 관리
from audio.audio_manager import GlobalAudio, _audio_lock
from services.weather_service import WeatherService
from services.timer_manager import TimerManager

class AppState:
    """앱 전체 가변 상태를 한 곳에서 관리하는 컨테이너."""
    def __init__(self):
        self.ai_assistant = None
        self.learning_mode = {'enabled': False}
        self.fish_tts = None
        self.rp_gen = None
        self.character_widget = None
        self.command_registry = None
        self.tts_thread = None
        self.tts_signature = None
        self.tts_init_event = threading.Event()
        self.tts_init_started = False
        self.game_mode = False
        self.saved_tts_mode = None
        self.last_bubble_signature = ("", 0.0)

_state = AppState()


class SharedMicrophone(sr.Microphone):
    """전역 PyAudio 인스턴스를 공유하는 마이크 클래스"""
    def __enter__(self):
        if self.audio is None:
            self.audio = GlobalAudio.get_instance()
        return super().__enter__()


# ── 초기화 및 설정 ───────────────────────────────────────────────────────────

def set_tts_thread(thread: Any) -> None:
    _state.tts_thread = thread


def set_ai_assistant(assistant: Any) -> None:
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


def set_character_widget(widget: Any) -> None:
    _state.character_widget = widget
    
    # 오케스트레이터 생각 중 상태 연결
    try:
        from agent.agent_orchestrator import get_orchestrator
        orch = get_orchestrator()
        orch.set_thinking_callback(widget.thinking_signal.emit)
    except Exception as e:
        logging.warning(f"오케스트레이터 생각 콜백 연결 실패: {e}")
        
    reconnect_tts_signals()


def start_tts_background():
    if _state.tts_init_started: return
    _state.tts_init_started = True

    from core.config_manager import ConfigManager
    tts_mode = ConfigManager.load_settings().get("tts_mode", "fish")

    if tts_mode == "local":
        def _run():
            try:
                initialize_tts()
                if _state.fish_tts and hasattr(_state.fish_tts, 'wait_until_warmup_done'):
                    _state.fish_tts.wait_until_warmup_done()
                _state.tts_init_event.set()
                tts_wrapper("로딩이 완료되었습니다. 이제 대화할 수 있어요!")
            except Exception as e:
                logging.error(f"TTS 초기화 실패: {e}")
                _state.tts_init_event.set()
        threading.Thread(target=_run, daemon=True).start()
    else:
        try:
            initialize_tts()
        except Exception as e:
            logging.error(f"TTS 초기화 실패 (동기): {e}")
        finally:
            _state.tts_init_event.set()


def initialize_tts():
    from core.config_manager import ConfigManager
    from tts.tts_factory import create_tts_provider, build_tts_signature
    settings = ConfigManager.load_settings()
    next_signature = build_tts_signature(settings)
    if _state.fish_tts is not None and _state.tts_signature == next_signature:
        logging.info("TTS 설정 변경 없음 - 기존 프로바이더 재사용")
    else:
        if _state.fish_tts and hasattr(_state.fish_tts, "cleanup"):
            try:
                _state.fish_tts.cleanup()
            except Exception as e:
                logging.debug(f"기존 TTS 정리 중 무시된 오류: {e}")
        try:
            _state.fish_tts, _ = create_tts_provider()
        except Exception as exc:
            logging.error(f"[TTS] 기본 프로바이더 초기화 실패: {exc}")
            fallback = settings.get("tts_fallback_provider", "edge")
            fallback_settings = dict(settings)
            fallback_settings["tts_mode"] = fallback
            logging.warning(f"[TTS] 폴백으로 전환: {fallback}")
            _state.fish_tts, _ = create_tts_provider(fallback_settings)
        _state.tts_signature = next_signature

    if _state.character_widget and hasattr(_state.fish_tts, 'playback_finished'):
        try:
            try:
                _state.fish_tts.playback_finished.disconnect(_state.character_widget.hide_speech_bubble)
            except Exception:
                pass
            _state.fish_tts.playback_finished.connect(_state.character_widget.hide_speech_bubble)
        except Exception:
            pass

    _state.rp_gen = RPGenerator()
    _state.rp_gen.set_config(
        personality=settings.get("personality", ""),
        scenario=settings.get("scenario", ""),
        system_prompt=settings.get("system_prompt", ""),
        history_instruction=settings.get("history_instruction", "")
    )


def reconnect_tts_signals():
    """현재 TTS 프로바이더와 캐릭터 위젯 시그널을 다시 연결."""
    if not _state.fish_tts or not _state.character_widget or not hasattr(_state.fish_tts, 'playback_finished'):
        return
    try:
        try:
            _state.fish_tts.playback_finished.disconnect(_state.character_widget.hide_speech_bubble)
        except Exception:
            pass
        _state.fish_tts.playback_finished.connect(_state.character_widget.hide_speech_bubble)
    except Exception as e:
        logging.debug(f"TTS 시그널 재연결 실패: {e}")


# ── 실행 로직 ───────────────────────────────────────────────────────────────

import re

# 감정 태그 파싱용 정규표현식 사전 컴파일 (성능 최적화)
_EMOTION_NAMES = "기쁨|슬픔|화남|놀람|평온|수줍|기대|진지|걱정"
EMOTION_PATTERN = re.compile(rf'[\(\[]({_EMOTION_NAMES})[\)\]]')

# 감정별 이모지 매핑 (이미지 제작 부담 완화 및 표현력 강화)
EMOTION_EMOJI = {
    "기쁨": "😊", "슬픔": "😭", "화남": "💢", "놀람": "😲",
    "평온": "☕", "수줍": "☺️", "기대": "✨", "진지": "🧐", "걱정": "😟"
}


def parse_emotion_text(text: str) -> Tuple[str, str]:
    """감정 태그를 제거하고 대표 감정/표시용 텍스트를 반환."""
    emotion = "평온"
    matches = EMOTION_PATTERN.findall(text or "")
    if matches:
        emotion = matches[-1]
    pure_text = EMOTION_PATTERN.sub("", text or "")
    pure_text = re.sub(r'\s+', ' ', pure_text).strip()
    return emotion, pure_text


def _show_tts_bubble(text):
    """어떤 TTS 경로든 동일한 말풍선을 표시하되, 직전 중복 표시는 짧게 억제."""
    emotion, pure_text = parse_emotion_text(text)
    emoji = EMOTION_EMOJI.get(emotion, "")
    display_text = f"{emoji} {pure_text}" if emoji and pure_text else (pure_text or text)
    now = time.monotonic()
    last_text, last_ts = _state.last_bubble_signature
    if display_text == last_text and (now - last_ts) < 0.5:
        return
    _state.last_bubble_signature = (display_text, now)
    if _state.character_widget:
        _state.character_widget.say(display_text, duration=0)


def text_to_speech(text: str, show_bubble: bool = True) -> bool:
    """TTS로 음성 출력 (최종 최적화 버전)"""
    emotion, text = parse_emotion_text(text)

    if _state.character_widget:
        _state.character_widget.set_emotion(emotion)
        if show_bubble:
            _show_tts_bubble(text)

    if _state.fish_tts is None:
        if _state.tts_init_started:
            if not _state.tts_init_event.wait(timeout=10.0):
                logging.warning("TTS 초기화 대기 타임아웃")
                if show_bubble and _state.character_widget:
                    _state.character_widget.hide_speech_bubble()
                return False
        else:
            initialize_tts()

    if _state.fish_tts is None:
        logging.error("TTS 프로바이더가 없습니다.")
        if show_bubble and _state.character_widget:
            _state.character_widget.hide_speech_bubble()
        return False

    try:
        if _state.rp_gen: text = _state.rp_gen.generate(text)
        ok = _state.fish_tts.speak(text, emotion=emotion)
        if not ok and show_bubble and _state.character_widget:
            _state.character_widget.hide_speech_bubble()
        return ok
    except Exception as e:
        logging.error(f"TTS 오류: {e}")
        if show_bubble and _state.character_widget:
            _state.character_widget.hide_speech_bubble()
        return False


def tts_wrapper(text: str, show_bubble: bool = True) -> None:
    """TTS 재생 + 말풍선 표시 (감정 이모지 및 동기화 최적화)"""
    if _state.tts_thread:
        queued = _state.tts_thread.speak(text)
        if queued and show_bubble:
            _show_tts_bubble(text)
        elif not queued and _state.character_widget:
            _state.character_widget.hide_speech_bubble()
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


def execute_command(command):
    if _state.command_registry: _state.command_registry.execute(command)


# ── 스레드용 헬퍼 함수 ────────────────────────────────────────────────────────

def get_microphone_index_helper(microphone_name):
    if not microphone_name: return None
    for index, name in enumerate(sr.Microphone.list_microphone_names()):
        if microphone_name in name: return index
    return None


def recognize_speech_helper(recognizer, source, signal, stt_provider=None, previous_texts=None):
    try:
        logging.info("말씀해 주세요...")
        audio = recognizer.listen(source, timeout=SPEECH_TIMEOUT, phrase_time_limit=SPEECH_PHRASE_LIMIT)
        provider = stt_provider
        if provider is None:
            from core.config_manager import ConfigManager
            from core.stt_provider import create_stt_provider

            provider = create_stt_provider(ConfigManager.load_settings())
        text = provider.transcribe(audio)
        if not text:
            logging.warning("음성 인식 불가")
            return
        text = text.strip()
        if len(text) < 2:
            logging.debug(f"[STT] 너무 짧은 인식 결과 무시: '{text}'")
            return
        history = previous_texts if previous_texts is not None else deque(maxlen=3)
        if history.count(text) >= 2:
            logging.debug(f"[STT] 반복 오인식 무시: '{text}'")
            return
        history.append(text)
        logging.info(f"인식된 텍스트: {text}")
        signal.emit(text)
    except sr.UnknownValueError: logging.warning("음성 인식 불가")
    except Exception as e: logging.error(f"음성 인식 오류: {e}")


def wake_detector_recalibrate_helper(detector, source):
    try:
        detector.recalibrate(source)
    except Exception:  # nosec B110
        pass


# ── 모듈 초기화 ──────────────────────────────────────────────────────────────

weather_service = WeatherService(api_key="")
timer_manager = TimerManager(tts_callback=lambda t: tts_wrapper(text=t))

def adjust_volume(change):
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        curr = volume.GetMasterVolumeLevelScalar()
        new_v = max(0.0, min(1.0, curr + change))
        volume.SetMasterVolumeLevelScalar(new_v, None)
        tts_wrapper(f"볼륨을 {int(new_v * 100)}%로 조절했습니다.")
    except Exception:
        tts_wrapper("볼륨 조절 실패")

from commands.command_registry import CommandRegistry
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
    """게임 모드 활성화: CosyVoice3 서브프로세스 종료 → VRAM 해제 → Fish Audio로 전환"""
    if _state.game_mode:
        return

    from core.config_manager import ConfigManager
    _state.saved_tts_mode = ConfigManager.load_settings().get("tts_mode", "fish")

    if _state.fish_tts and hasattr(_state.fish_tts, 'cleanup'):
        try:
            _state.fish_tts.cleanup()
        except Exception as e:
            logging.warning(f"기존 TTS 정리 오류 (무시): {e}")
    _state.fish_tts = None

    try:
        from tts.fish_tts_ws import FishTTSWebSocket
        settings = ConfigManager.load_settings()
        _state.fish_tts = FishTTSWebSocket(
            api_key=settings.get("fish_api_key", ""),
            reference_id=settings.get("fish_reference_id", "")
        )
        _state.game_mode = True
        logging.info("게임 모드 활성화: Fish Audio TTS로 전환, GPU 메모리 해제됨")
    except Exception as e:
        logging.error(f"게임 모드 전환 실패: {e}")
        try:
            initialize_tts()
        except Exception as fallback_exc:
            logging.error(f"게임 모드 실패 후 TTS 복원 실패: {fallback_exc}")


def disable_game_mode():
    """게임 모드 비활성화: Fish Audio 해제 → 원래 TTS(CosyVoice3 등)로 복원"""
    if not _state.game_mode:
        return

    if _state.fish_tts and hasattr(_state.fish_tts, 'cleanup'):
        try:
            _state.fish_tts.cleanup()
        except Exception as e:
            logging.warning(f"Fish TTS 정리 오류 (무시): {e}")
    _state.fish_tts = None
    _state.game_mode = False

    def _reinit():
        try:
            initialize_tts()
            if _state.fish_tts and hasattr(_state.fish_tts, 'wait_until_warmup_done'):
                _state.fish_tts.wait_until_warmup_done()
            tts_wrapper("게임 모드 해제. CosyVoice로 복원되었습니다.")
        except Exception as e:
            logging.error(f"TTS 복원 실패: {e}")

    threading.Thread(target=_reinit, daemon=True, name="TTS-GameModeRestore").start()
    logging.info("게임 모드 비활성화: 원래 TTS 복원 중")


def is_game_mode() -> bool:
    return _state.game_mode


# ── 하위 호환 모듈 수준 별칭 ──────────────────────────────────────────────────
# 이전에 모듈 전역으로 노출됐던 이름들. 같은 객체를 가리키므로 변경이 양쪽에 반영됨.
learning_mode = _state.learning_mode          # dict, 재할당 없음 → 안전한 별칭
_tts_init_event = _state.tts_init_event       # threading.Event, 재할당 없음 → 안전한 별칭

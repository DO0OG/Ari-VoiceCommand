import os
import sys
import time
import logging
import warnings
import random
import threading
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

# 전역 변수
ai_assistant = None
learning_mode = {'enabled': False}
fish_tts = None
rp_gen = None
character_widget = None
_command_registry = None
_tts_thread = None

_tts_init_event = threading.Event()
_tts_init_started = False
_game_mode = False          # 게임 모드 상태
_saved_tts_mode = None      # 게임 모드 진입 전 원래 TTS 모드
_last_bubble_signature = ("", 0.0)


class SharedMicrophone(sr.Microphone):
    """전역 PyAudio 인스턴스를 공유하는 마이크 클래스"""
    def __enter__(self):
        if self.audio is None:
            self.audio = GlobalAudio.get_instance()
        return super().__enter__()


# ── 초기화 및 설정 ───────────────────────────────────────────────────────────

def set_tts_thread(thread):
    global _tts_thread
    _tts_thread = thread


def set_ai_assistant(assistant):
    global ai_assistant, _command_registry
    ai_assistant = assistant
    if _command_registry:
        from commands.ai_command import AICommand
        for i, cmd in enumerate(_command_registry.commands):
            if isinstance(cmd, AICommand):
                _command_registry.commands[i] = AICommand(
                    ai_assistant=assistant,
                    tts_func=tts_wrapper,
                    learning_mode_ref=learning_mode
                )
                break


def set_character_widget(widget):
    global character_widget
    character_widget = widget
    reconnect_tts_signals()


def start_tts_background():
    global _tts_init_started
    if _tts_init_started: return
    _tts_init_started = True

    from core.config_manager import ConfigManager
    tts_mode = ConfigManager.load_settings().get("tts_mode", "fish")

    if tts_mode == "local":
        def _run():
            try:
                initialize_tts()
                if fish_tts and hasattr(fish_tts, 'wait_until_warmup_done'):
                    fish_tts.wait_until_warmup_done()
                _tts_init_event.set()
                tts_wrapper("로딩이 완료되었습니다. 이제 대화할 수 있어요!")
            except Exception as e:
                logging.error(f"TTS 초기화 실패: {e}")
                _tts_init_event.set()
        threading.Thread(target=_run, daemon=True).start()
    else:
        try:
            initialize_tts()
        except Exception as e:
            logging.error(f"TTS 초기화 실패 (동기): {e}")
        finally:
            _tts_init_event.set()


def initialize_tts():
    global fish_tts, rp_gen
    from core.config_manager import ConfigManager
    from tts.tts_factory import create_tts_provider
    settings = ConfigManager.load_settings()
    fish_tts, _ = create_tts_provider()
    
    # 캐릭터 위젯이 이미 있으면 시그널 재연결 (필요 시)
    if character_widget and hasattr(fish_tts, 'playback_finished'):
        try:
            # 기존 연결이 있을 수 있으므로 안전하게 처리
            try:
                fish_tts.playback_finished.disconnect(character_widget.hide_speech_bubble)
            except Exception:
                pass  # 이미 연결 해제된 경우 무시
            fish_tts.playback_finished.connect(character_widget.hide_speech_bubble)
        except Exception:
            pass  # 시그널 미지원 프로바이더 무시

    rp_gen = RPGenerator()
    rp_gen.set_config(
        personality=settings.get("personality", ""),
        scenario=settings.get("scenario", ""),
        system_prompt=settings.get("system_prompt", ""),
        history_instruction=settings.get("history_instruction", "")
    )


def reconnect_tts_signals():
    """사용되지 않음 (하위 호환 유지)"""
    pass


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


def parse_emotion_text(text):
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
    global _last_bubble_signature
    emotion, pure_text = parse_emotion_text(text)
    emoji = EMOTION_EMOJI.get(emotion, "")
    display_text = f"{emoji} {pure_text}" if emoji and pure_text else (pure_text or text)
    now = time.monotonic()
    last_text, last_ts = _last_bubble_signature
    if display_text == last_text and (now - last_ts) < 0.5:
        return
    _last_bubble_signature = (display_text, now)
    if character_widget:
        character_widget.say(display_text, duration=0)


def text_to_speech(text):
    """TTS로 음성 출력 (최종 최적화 버전)"""
    global fish_tts, rp_gen
    
    # 감정 태그 파싱 (사전 컴파일된 패턴 사용)
    emotion, text = parse_emotion_text(text)
    
    # 캐릭터 감정 표현 실행
    if character_widget:
        character_widget.set_emotion(emotion)
        _show_tts_bubble(text)

    if fish_tts is None:
        if _tts_init_started:
            if not _tts_init_event.wait(timeout=10.0): # 타임아웃 360 -> 10초로 단축 (행 걸림 방지)
                logging.warning("TTS 초기화 대기 타임아웃")
                return False
        else:
            initialize_tts()
    
    if fish_tts is None:
        logging.error("TTS 프로바이더가 없습니다.")
        return False

    try:
        if rp_gen: text = rp_gen.generate(text)
        return fish_tts.speak(text)
    except Exception as e:
        logging.error(f"TTS 오류: {e}")
        return False


def tts_wrapper(text, show_bubble=True):
    """TTS 재생 + 말풍선 표시 (감정 이모지 및 동기화 최적화)"""
    if show_bubble:
        _show_tts_bubble(text)

    if _tts_thread:
        # 단순 큐잉으로 최적화 유지
        _tts_thread.speak(text)
    else:
        text_to_speech(text)


def is_tts_playing():
    """현재 TTS가 큐 대기 중, 처리 중, 또는 재생 중인지 확인"""
    global _tts_thread, fish_tts
    if _tts_thread:
        if not _tts_thread.queue.empty():
            return True
        if getattr(_tts_thread, 'is_processing', False):
            return True
    if fish_tts and getattr(fish_tts, 'is_playing', False):
        return True
    return False


def execute_command(command):
    global _command_registry
    if _command_registry: _command_registry.execute(command)


# ── 스레드용 헬퍼 함수 ────────────────────────────────────────────────────────

def get_microphone_index_helper(microphone_name):
    if not microphone_name: return None
    for index, name in enumerate(sr.Microphone.list_microphone_names()):
        if microphone_name in name: return index
    return None


def recognize_speech_helper(recognizer, source, signal):
    try:
        logging.info("말씀해 주세요...")
        audio = recognizer.listen(source, timeout=SPEECH_TIMEOUT, phrase_time_limit=SPEECH_PHRASE_LIMIT)
        text = recognizer.recognize_google(audio, language=SPEECH_LANGUAGE)
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
_command_registry = CommandRegistry(
    ai_assistant=None,
    weather_service=weather_service,
    timer_manager=timer_manager,
    adjust_volume_func=adjust_volume,
    tts_func=tts_wrapper,
    learning_mode_ref=learning_mode
)

# ── 게임 모드 ─────────────────────────────────────────────────────────────────

def enable_game_mode():
    """게임 모드 활성화: CosyVoice3 서브프로세스 종료 → VRAM 해제 → Fish Audio로 전환"""
    global fish_tts, _game_mode, _saved_tts_mode

    if _game_mode:
        return  # 이미 활성화됨

    from core.config_manager import ConfigManager
    _saved_tts_mode = ConfigManager.load_settings().get("tts_mode", "fish")

    # CosyVoice3 워커 프로세스 종료 (VRAM 해제)
    if fish_tts and hasattr(fish_tts, 'cleanup'):
        try:
            fish_tts.cleanup()
        except Exception as e:
            logging.warning(f"기존 TTS 정리 오류 (무시): {e}")
    fish_tts = None

    # Fish Audio TTS로 교체
    try:
        from fish_tts_ws import FishTTSWebSocket
        settings = ConfigManager.load_settings()
        fish_tts = FishTTSWebSocket(
            api_key=settings.get("fish_api_key", ""),
            reference_id=settings.get("fish_reference_id", "")
        )
        _game_mode = True
        logging.info("게임 모드 활성화: Fish Audio TTS로 전환, GPU 메모리 해제됨")
    except Exception as e:
        logging.error(f"게임 모드 전환 실패: {e}")


def disable_game_mode():
    """게임 모드 비활성화: Fish Audio 해제 → 원래 TTS(CosyVoice3 등)로 복원"""
    global fish_tts, _game_mode, _saved_tts_mode

    if not _game_mode:
        return

    # Fish Audio 정리
    if fish_tts and hasattr(fish_tts, 'cleanup'):
        try:
            fish_tts.cleanup()
        except Exception as e:
            logging.warning(f"Fish TTS 정리 오류 (무시): {e}")
    fish_tts = None
    _game_mode = False

    # 원래 TTS 재초기화 (백그라운드)
    def _reinit():
        try:
            initialize_tts()
            if fish_tts and hasattr(fish_tts, 'wait_until_warmup_done'):
                fish_tts.wait_until_warmup_done()
            tts_wrapper("게임 모드 해제. CosyVoice로 복원되었습니다.")
        except Exception as e:
            logging.error(f"TTS 복원 실패: {e}")

    import threading as _threading
    _threading.Thread(target=_reinit, daemon=True, name="TTS-GameModeRestore").start()
    logging.info("게임 모드 비활성화: 원래 TTS 복원 중")


def is_game_mode() -> bool:
    return _game_mode

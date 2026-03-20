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
from rp_generator import RPGenerator
from constants import (
    SPEECH_LANGUAGE, SPEECH_TIMEOUT, SPEECH_PHRASE_LIMIT, AMBIENT_NOISE_DURATION
)

# 모듈 및 오디오 관리
from audio_manager import GlobalAudio, _audio_lock
from weather_service import WeatherService
from timer_manager import TimerManager

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

    from config_manager import ConfigManager
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
        try: initialize_tts()
        except: pass
        finally: _tts_init_event.set()


def initialize_tts():
    global fish_tts, rp_gen
    from config_manager import ConfigManager
    from tts_factory import create_tts_provider
    settings = ConfigManager.load_settings()
    fish_tts, _ = create_tts_provider()
    reconnect_tts_signals()
    rp_gen = RPGenerator()
    rp_gen.set_config(
        personality=settings.get("personality", ""),
        scenario=settings.get("scenario", ""),
        system_prompt=settings.get("system_prompt", ""),
        history_instruction=settings.get("history_instruction", "")
    )


def reconnect_tts_signals():
    """TTS 시그널 재연결 (필요 시 활용을 위해 유지)"""
    global fish_tts, character_widget
    # 기존: fish_tts.playback_finished.connect(character_widget.hide_speech_bubble)
    # 수정: TTSThread에서 큐 상태를 확인하여 직접 숨기도록 변경했으므로 자동 연결은 제거
    pass


# ── 실행 로직 ───────────────────────────────────────────────────────────────

import re

# 감정 태그 파싱용 정규표현식 사전 컴파일 (성능 최적화)
EMOTION_PATTERN = re.compile(r'\((기쁨|슬픔|화남|놀람|평온|수줍|기대|진지|걱정)\)')

# 감정별 이모지 매핑 (이미지 제작 부담 완화 및 표현력 강화)
EMOTION_EMOJI = {
    "기쁨": "😊", "슬픔": "😭", "화남": "💢", "놀람": "😲",
    "평온": "☕", "수줍": "☺️", "기대": "✨", "진지": "🧐", "걱정": "😟"
}


def text_to_speech(text):
    """TTS로 음성 출력 (최종 최적화 버전)"""
    global fish_tts, rp_gen
    
    # 감정 태그 파싱 (사전 컴파일된 패턴 사용)
    emotion = "평온"
    match = EMOTION_PATTERN.search(text)
    if match:
        emotion = match.group(1)
        text = EMOTION_PATTERN.sub("", text).strip()
    
    # 캐릭터 감정 표현 실행
    if character_widget:
        character_widget.set_emotion(emotion)

    if fish_tts is None:
        if _tts_init_started: _tts_init_event.wait(timeout=360)
        else: initialize_tts()
    reconnect_tts_signals()
    
    if fish_tts is None: return False
    try:
        if rp_gen: text = rp_gen.generate(text)
        return fish_tts.speak(text)
    except Exception as e:
        logging.error(f"TTS 오류: {e}")
        return False


def tts_wrapper(text, show_bubble=True):
    """TTS 재생 + 말풍선 표시 (감정 이모지 및 동기화 최적화)"""
    # 표시용 텍스트에서 감정 태그 파싱 및 이모지 추가
    display_text = text
    match = EMOTION_PATTERN.search(text)
    if match:
        emotion = match.group(1)
        emoji = EMOTION_EMOJI.get(emotion, "")
        pure_text = EMOTION_PATTERN.sub("", text).strip()
        display_text = f"{emoji} {pure_text}" if emoji else pure_text

    if show_bubble and character_widget:
        # duration=0은 무한 유지가 아니라 TTS 완료 시그널 대기 모드임
        character_widget.say(display_text, duration=0)

    if _tts_thread:
        # 단순 큐잉으로 최적화 유지
        _tts_thread.speak(text)
    else:
        text_to_speech(text)



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
    try: detector.recalibrate(source)
    except: pass


# ── 모듈 초기화 ──────────────────────────────────────────────────────────────

weather_service = WeatherService(api_key="")
timer_manager = TimerManager(tts_callback=lambda t: tts_wrapper(text=t))

from commands.command_registry import CommandRegistry
_command_registry = CommandRegistry(
    ai_assistant=None,
    weather_service=weather_service,
    timer_manager=timer_manager,
    adjust_volume_func=None, # 아래에서 정의
    tts_func=tts_wrapper,
    learning_mode_ref=learning_mode
)

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
    except: tts_wrapper("볼륨 조절 실패")

_command_registry.adjust_volume_func = adjust_volume

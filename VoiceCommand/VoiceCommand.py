import os
import sys
import time
import logging
import warnings
import random
import speech_recognition as sr

# SSL 인증서 경로 설정 (PyInstaller 환경)
if getattr(sys, 'frozen', False):
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
from datetime import datetime
from queue import Queue
from PySide6.QtCore import QThread, Signal
from pydub import AudioSegment
from pydub.playback import play
from Config import use_api
import json
from fish_tts_ws import FishTTSWebSocket
from rp_generator import RPGenerator
from simple_wake import SimpleWakeWord
from constants import (
    WAKE_WORDS, WAKE_RESPONSES, SPEECH_LANGUAGE,
    SPEECH_TIMEOUT, SPEECH_PHRASE_LIMIT, AMBIENT_NOISE_DURATION
)

# 새로운 모듈 import
from weather_service import WeatherService
from timer_manager import TimerManager

# 전역 변수 선언
ai_assistant = None
learning_mode = {'enabled': False}  # dict로 변경하여 참조 전달
fish_tts = None
rp_gen = None
character_widget = None
_command_registry = None  # 명령 레지스트리 (나중에 초기화)

import threading
_tts_init_event = threading.Event()   # TTS 초기화 완료 신호
_tts_init_started = False             # 백그라운드 초기화 시작 여부


def start_tts_background():
    """앱 시작 시 TTS를 백그라운드 스레드에서 미리 초기화"""
    global _tts_init_started
    if _tts_init_started:
        return
    _tts_init_started = True

    def _run():
        try:
            initialize_tts()
        except Exception as e:
            logging.error(f"백그라운드 TTS 초기화 실패: {e}")
        finally:
            _tts_init_event.set()

    t = threading.Thread(target=_run, daemon=True, name="TTS-Init")
    t.start()
    logging.info("TTS 백그라운드 초기화 시작")


def initialize_tts():
    """TTS 초기화 — tts_mode 설정에 따라 Fish Audio 또는 로컬 CosyVoice3 선택"""
    global fish_tts, rp_gen
    from config_manager import ConfigManager

    settings = ConfigManager.load_settings()
    tts_mode = settings.get("tts_mode", "fish")  # "fish" | "local"

    if tts_mode == "local":
        try:
            from cosyvoice_tts import CosyVoiceTTS
            fish_tts = CosyVoiceTTS(
                reference_text=settings.get("cosyvoice_reference_text", ""),
                speed=float(settings.get("cosyvoice_speed", 0.9)),
            )
            logging.info("CosyVoice3 로컬 TTS 초기화 완료")
        except Exception as e:
            logging.error(f"CosyVoice3 초기화 실패, Fish Audio로 fallback: {e}")
            tts_mode = "fish"

    if tts_mode == "fish":
        api_key = settings.get("fish_api_key", "")
        if not api_key:
            logging.warning("Fish API key가 설정되지 않았습니다")
        fish_tts = FishTTSWebSocket(
            api_key=api_key,
            reference_id=settings.get("fish_reference_id", "")
        )
        logging.info("Fish Audio TTS 초기화 완료")

    rp_gen = RPGenerator()
    rp_gen.set_config(
        personality=settings.get("personality", ""),
        scenario=settings.get("scenario", ""),
        system_prompt=settings.get("system_prompt", ""),
        history_instruction=settings.get("history_instruction", "")
    )
    _tts_init_event.set()  # 직접 호출된 경우에도 완료 신호


# 초기화 제거 - lazy loading으로 변경
# initialize_tts()

# 모듈 인스턴스 초기화
weather_service = None
timer_manager = None


def initialize_modules():
    """기능 모듈 초기화"""
    global weather_service, timer_manager

    def tts_callback(text):
        tts_wrapper(text)

    weather_service = WeatherService(api_key="")
    timer_manager = TimerManager(tts_callback=tts_callback)

    logging.info("기능 모듈 초기화 완료")


def _initialize_command_registry():
    """명령 레지스트리 초기화 (adjust_volume 정의 이후 호출)"""
    global _command_registry
    from commands.command_registry import CommandRegistry
    _command_registry = CommandRegistry(
        ai_assistant=None,  # 나중에 set_ai_assistant()에서 설정
        weather_service=weather_service,
        timer_manager=timer_manager,
        adjust_volume_func=adjust_volume,
        tts_func=tts_wrapper,
        learning_mode_ref=learning_mode
    )
    logging.info("명령 레지스트리 초기화 완료")


# 기능 모듈 초기화 (weather_service, timer_manager)
initialize_modules()


def set_ai_assistant(assistant):
    global ai_assistant, _command_registry
    ai_assistant = assistant

    # 명령 레지스트리에 AI 어시스턴트 설정
    if _command_registry:
        from commands.ai_command import AICommand
        # AI 명령 찾아서 업데이트
        for i, cmd in enumerate(_command_registry.commands):
            if isinstance(cmd, AICommand):
                _command_registry.commands[i] = AICommand(
                    ai_assistant=assistant,
                    tts_func=tts_wrapper,
                    learning_mode_ref=learning_mode
                )
                break


def set_character_widget(widget):
    global character_widget, fish_tts
    character_widget = widget

    # TTS 완료 시 말풍선 숨김 연결
    if fish_tts and hasattr(fish_tts, 'playback_finished'):
        fish_tts.playback_finished.connect(
            lambda: character_widget.hide_speech_bubble_signal.emit()
        )


warnings.filterwarnings("ignore", category=DeprecationWarning)


def text_to_speech(text):
    """Fish TTS로 음성 출력"""
    global fish_tts, rp_gen, character_widget

    # 백그라운드 초기화 완료 대기 (최대 360초)
    if fish_tts is None:
        if _tts_init_started:
            logging.info("TTS 초기화 완료 대기 중...")
            _tts_init_event.wait(timeout=360)
        else:
            # 백그라운드 초기화가 시작되지 않은 경우 직접 초기화
            initialize_tts()

        # 초기화 후 character_widget 연결 설정
        if fish_tts and character_widget and hasattr(fish_tts, 'playback_finished'):
            try:
                fish_tts.playback_finished.disconnect()
            except:
                pass
            fish_tts.playback_finished.connect(
                lambda: character_widget.hide_speech_bubble_signal.emit()
            )
            logging.info("TTS playback_finished 시그널 연결됨")

    if fish_tts is None:
        logging.error("TTS를 초기화할 수 없습니다")
        return False

    try:
        # RP 텍스트 생성
        if rp_gen:
            text = rp_gen.generate(text)

        # TTS 재생
        success = fish_tts.speak(text)
        if not success:
            logging.error("TTS 재생 실패")
        return success
    except Exception as e:
        logging.error(f"TTS 오류: {e}")
        return False


def tts_wrapper(text, show_bubble=True):
    """TTS 재생 + 말풍선 표시"""
    # 말풍선 표시 (duration=0: TTS 끝날 때까지 유지)
    if show_bubble and character_widget:
        character_widget.say(text, duration=0)

    # TTS 재생 (끝나면 자동으로 말풍선 숨김)
    text_to_speech(text)


def execute_command(command):
    """명령 실행"""
    global _command_registry
    logging.info(f"실행할 명령: {command}")

    if _command_registry:
        _command_registry.execute(command)
    else:
        logging.error("명령 레지스트리가 초기화되지 않았습니다.")


def listen_for_speech(timeout: int = 5, phrase_time_limit: int = 5,
                      prompt: str = None):
    """
    음성 입력을 듣고 텍스트로 변환

    Args:
        timeout: 음성 입력 대기 시간 (초)
        phrase_time_limit: 최대 녹음 시간 (초)
        prompt: 사용자에게 먼저 말할 메시지 (선택)

    Returns:
        인식된 텍스트 또는 None
    """
    if prompt:
        tts_wrapper(prompt)

    try:
        recognizer = sr.Recognizer()
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=AMBIENT_NOISE_DURATION)
            audio = recognizer.listen(
                source,
                timeout=timeout,
                phrase_time_limit=phrase_time_limit
            )
            text = recognizer.recognize_google(audio, language=SPEECH_LANGUAGE)
            logging.info(f"음성 인식: {text}")
            return text
    except sr.WaitTimeoutError:
        logging.warning("음성 입력 시간 초과")
        return None
    except sr.UnknownValueError:
        logging.warning("음성을 이해할 수 없습니다")
        return None
    except sr.RequestError as e:
        logging.error(f"Google Speech Recognition 오류: {e}")
        return None
    except Exception as e:
        logging.error(f"음성 인식 오류: {e}")
        return None


def adjust_volume(change):
    """Windows 볼륨 조절"""
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))

        current_volume = volume.GetMasterVolumeLevelScalar()
        new_volume = max(0.0, min(1.0, current_volume + change))
        volume.SetMasterVolumeLevelScalar(new_volume, None)

        tts_wrapper(f"볼륨을 {int(new_volume * 100)}%로 조절했습니다.")
    except Exception as e:
        logging.error(f"볼륨 조절 실패: {str(e)}")
        tts_wrapper("볼륨 조절에 실패했습니다.")


class VoiceRecognitionThread(QThread):
    result = Signal(str)
    listening_state_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.running = True
        self.selected_microphone = None
        self.microphone_index = None

        # 간단한 웨이크워드
        self.wake_detector = SimpleWakeWord(wake_words=WAKE_WORDS)

        # 마이크 초기화
        self.speech_recognizer = sr.Recognizer()
        self.microphone = sr.Microphone(device_index=self.microphone_index)

    def init_microphone(self):
        # 기본 마이크 사용
        logging.info("기본 오디오 입력 장치를 사용합니다.")

    def set_microphone(self, microphone):
        if self.selected_microphone != microphone:
            self.selected_microphone = microphone
            self.microphone_index = self.get_microphone_index(microphone)
            # 마이크 인덱스 업데이트
            self.microphone = sr.Microphone(device_index=self.microphone_index)

    def get_microphone_index(self, microphone_name):
        import speech_recognition as sr
        for index, name in enumerate(sr.Microphone.list_microphone_names()):
            if microphone_name in name:
                return index
        return None

    def run(self):
        try:
            logging.info("음성 감지 시작 (웨이크워드: 아리야, 시작)")
            while self.running:
                if self.wake_detector.listen_for_wake_word():
                    self.handle_wake_word()
                time.sleep(0.1)
        except Exception as e:
            logging.error(f"오류 발생: {str(e)}", exc_info=True)
        finally:
            self.cleanup()


    def handle_wake_word(self):
        logging.info("웨이크 워드 감지!")
        response = random.choice(WAKE_RESPONSES)
        tts_wrapper(response)
        time.sleep(0.3)  # TTS 에코 정착 대기
        self.listening_state_changed.emit(True)
        self.recognize_speech()
        self.listening_state_changed.emit(False)
        # 대화 후 재캘리브레이션 (주변 소음이 변했을 경우 대비)
        self.wake_detector.recalibrate()

    def recognize_speech(self):
        try:
            with self.microphone as source:
                logging.info("말씀해 주세요...")
                audio = self.speech_recognizer.listen(
                    source,
                    timeout=SPEECH_TIMEOUT,
                    phrase_time_limit=SPEECH_PHRASE_LIMIT
                )

            text = self.speech_recognizer.recognize_google(audio, language=SPEECH_LANGUAGE)
            logging.info(f"인식된 텍스트: {text}")
            self.result.emit(text)

        except sr.UnknownValueError:
            logging.warning("음성을 인식할 수 없습니다.")
        except sr.RequestError as e:
            logging.error(f"음성 인식 서비스 오류: {e}")
        except Exception as e:
            logging.error(f"음성 인식 중 오류: {str(e)}")

    def cleanup(self):
        logging.info("음성 인식 스레드 종료 중...")
        if hasattr(self, 'wake_detector'):
            # SimpleWakeWord에 stop 플래그 전달
            self.wake_detector.should_stop = True
        # 마이크 리소스 해제
        if hasattr(self, 'microphone'):
            self.microphone = None
        logging.info("음성 인식 스레드 종료 완료")

    def get_voice_feedback(self):
        pass

    def stop(self):
        logging.info("VoiceRecognitionThread.stop() called")
        self.running = False
        if hasattr(self, 'wake_detector'):
            self.wake_detector.should_stop = True
        # 타임아웃 추가
        if not self.wait(5000):
            logging.warning("VoiceRecognitionThread timeout")


# TTS 스레드
class TTSThread(QThread):
    def __init__(self):
        super().__init__()
        self.queue = Queue()

    def run(self):
        logging.info("TTSThread started")
        while True:
            try:
                text = self.queue.get(timeout=1.0)  # 타임아웃 추가
                if text is None:
                    logging.info("TTSThread stop signal received")
                    break
                text_to_speech(text)
                self.queue.task_done()
            except Exception as e:
                if "Empty" not in str(type(e).__name__):
                    logging.error(f"TTSThread error: {e}")
                continue  # 다시 체크

    def speak(self, text):
        self.queue.put(text)


# 명령 실행 스레드

class CommandExecutionThread(QThread):
    def __init__(self):
        super().__init__()
        self.queue = Queue()

    def run(self):
        logging.info("CommandExecutionThread started")
        while True:
            try:
                command = self.queue.get(timeout=1.0)  # 타임아웃 추가
                if command is None:
                    logging.info("CommandExecutionThread stop signal received")
                    break
                execute_command(command)
                self.queue.task_done()
            except Exception as e:
                if "Empty" not in str(type(e).__name__):
                    logging.error(f"CommandExecutionThread error: {e}")
                continue  # 다시 체크

    def execute(self, command):
        self.queue.put(command)


# 명령 레지스트리 초기화 (모든 함수 정의 이후)
_initialize_command_registry()

"""Fish Audio HTTP PCM TTS."""

import logging
import threading

import ormsgpack
import requests
from PySide6.QtCore import QObject, Signal

from core.emotions import DEFAULT_EMOTION
from tts.pcm_playback import play_pcm_stream, response_pcm_chunks


class FishTTSWebSocket(QObject):
    playback_finished = Signal()

    # Fish doesn't document PCM byte order; assume little-endian S16LE.
    _SAMPLE_RATE = 44100
    # SDK 기본 백엔드(speech-1.5)는 유료 등급이라 명시하지 않으면 과금된다.
    _DEFAULT_MODEL = "s2.1-pro-free"
    # __init__을 거치지 않는 경우에도 기본값을 유지한다.
    model = _DEFAULT_MODEL

    def __init__(self, api_key="", reference_id="", model=""):
        super().__init__()
        from audio.audio_manager import GlobalAudio

        self.api_key = api_key
        self.reference_id = reference_id
        self.model = model or self._DEFAULT_MODEL
        self.pa = GlobalAudio.get_instance()
        self.is_playing = False
        self._last_playback_success = None
        self._state_lock = threading.Lock()
        self._speak_lock = threading.RLock()
        self._active_stop_event = None
        self._active_response = None
        logging.info("Fish Audio streaming TTS initialized")

    def _stream_tts(self, text):
        payload = {
            "text": text,
            "chunk_length": 200,
            "format": "pcm",
            "sample_rate": self._SAMPLE_RATE,
            "mp3_bitrate": 128,
            "opus_bitrate": 32,
            "references": [],
            "reference_id": self.reference_id or None,
            "normalize": True,
            "latency": "balanced",
            "prosody": None,
            "top_p": 0.7,
            "temperature": 0.7,
        }
        return requests.post(
            "https://api.fish.audio/v1/tts",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/msgpack",
                "model": self.model,
            },
            data=ormsgpack.packb(payload),
            stream=True,
            timeout=(10, 60),
        )

    def _set_active_response(self, response, stop_event):
        with self._state_lock:
            if self._active_stop_event is stop_event:
                self._active_response = response

    def _close_response(self, response):
        if response is None:
            return
        try:
            response.close()
        except Exception as exc:
            logging.debug("Fish Audio response close failed: %s", exc)
        finally:
            with self._state_lock:
                if self._active_response is response:
                    self._active_response = None

    def _check_response(self, response):
        if 200 <= response.status_code < 300:
            return
        try:
            error_body = response.json()
        except ValueError:
            error_body = None
        if isinstance(error_body, dict):
            message = error_body.get("detail") or error_body.get("message")
        else:
            message = None
        if not message:
            message = response.text.strip() or "No error detail returned"
        raise RuntimeError(
            f"Fish Audio API request failed ({response.status_code}): {message}"
        )

    def _open_playback_stream(self, output_device_index):
        from audio.audio_manager import GlobalAudio, get_audio_output_lock

        with get_audio_output_lock():
            return GlobalAudio.open_stream(
                format=self.pa.get_format_from_width(2),
                channels=1,
                rate=self._SAMPLE_RATE,
                output=True,
                output_device_index=output_device_index,
                frames_per_buffer=1024,
            )

    def _close_playback_stream(self, stream):
        from audio.audio_manager import GlobalAudio, get_audio_output_lock

        with get_audio_output_lock():
            GlobalAudio.close_stream(stream)

    def _play_response(self, response, stop_event):
        self._check_response(response)
        chunks = response_pcm_chunks(response, "Fish Audio", 1024)
        from audio.audio_manager import get_output_device_index

        output_device_index = get_output_device_index()
        return play_pcm_stream(
            lambda: self._open_playback_stream(output_device_index),
            self._close_playback_stream,
            chunks,
            stop_event,
            self._SAMPLE_RATE,
            on_start=lambda: logging.info("[TTS] Fish Audio playback started"),
        )

    def speak(
        self,
        text,
        emotion: str = DEFAULT_EMOTION,
        stop_event: threading.Event | None = None,
    ) -> bool:
        """텍스트를 PCM 스트리밍 음성으로 변환하여 재생한다."""
        if not text:
            return False

        stop_event = stop_event or threading.Event()
        with self._state_lock:
            active_stop_event = self._active_stop_event
        if active_stop_event is not None and active_stop_event is not stop_event:
            self.stop()

        with self._speak_lock:
            with self._state_lock:
                self._active_stop_event = stop_event
                self.is_playing = True
            response = None
            success = False
            try:
                if not stop_event.is_set():
                    logging.info("Fish Audio TTS request: %s...", text[:30])
                    response = self._stream_tts(text)
                    self._set_active_response(response, stop_event)
                    if not stop_event.is_set():
                        success = self._play_response(response, stop_event)
            except Exception as exc:
                if not stop_event.is_set():
                    logging.error("Fish Audio TTS failed: %s", exc)
            finally:
                self._close_response(response)
                with self._state_lock:
                    if self._active_stop_event is stop_event:
                        self._active_stop_event = None
                        self.is_playing = False
                self._last_playback_success = success
                self.playback_finished.emit()
            return success

    def stop(self):
        with self._state_lock:
            stop_event = self._active_stop_event
            response = self._active_response
            if stop_event is not None:
                stop_event.set()
        if response is not None:
            # 읽는 중인 응답을 닫으면 읽기 타임아웃까지 막힐 수 있어 호출 스레드를 붙잡지 않는다.
            threading.Thread(target=self._close_response, args=(response,), daemon=True).start()

    def cleanup(self):
        self.stop()
        with self._speak_lock:
            pass

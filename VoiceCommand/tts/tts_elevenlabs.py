"""
ElevenLabs TTS 제공자.
Fish Audio / CosyVoice3와 동일한 인터페이스: speak() / playback_finished / cleanup()
"""
import logging
import threading
import time
from pathlib import Path

import pyaudio
from PySide6.QtCore import QObject, Signal

from audio.audio_manager import GlobalAudio, get_audio_output_lock
from core.emotions import DEFAULT_EMOTION, get_emotion_details
from tts.pcm_playback import play_pcm_stream, response_pcm_chunks
from tts.secret_utils import redact_secret as _redact_secret

_DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel (다국어)
_SAMPLE_RATE = 24000
_API_URL = "https://api.elevenlabs.io"
_LIST_TIMEOUT = (10, 30)
_UPLOAD_TIMEOUT = (10, 60)


def _require_api_key(api_key: str) -> None:
    if not api_key:
        raise ValueError("ElevenLabs API key is missing")


def _check_response(response, requests, api_key: str) -> None:
    try:
        response.raise_for_status()
    except requests.RequestException:
        status = getattr(response, "status_code", "unknown")
        detail = _redact_secret(str(getattr(response, "text", "")), api_key).strip()
        detail = detail[:1000]
        message = detail or f"HTTP {status}"
        raise RuntimeError(f"ElevenLabs API error: {message}") from None


def _get_json(api_key: str, url: str, params=None):
    _require_api_key(api_key)
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests package is required") from exc

    try:
        response = requests.get(
            url,
            headers={"xi-api-key": api_key},
            params=params,
            timeout=_LIST_TIMEOUT,
        )
    except requests.RequestException as exc:
        detail = _redact_secret(str(exc), api_key)
        raise RuntimeError(f"ElevenLabs API request failed: {detail}") from None
    _check_response(response, requests, api_key)
    try:
        return response.json()
    except ValueError:
        raise RuntimeError("ElevenLabs returned invalid JSON") from None


def fetch_models(api_key: str) -> list[dict]:
    """TTS를 지원하는 모델을 API에서 읽는다."""
    data = _get_json(api_key, f"{_API_URL}/v1/models")
    if not isinstance(data, list):
        raise RuntimeError("ElevenLabs returned an invalid model list")
    return [
        {"model_id": item["model_id"], "name": item.get("name") or item["model_id"]}
        for item in data
        if isinstance(item, dict)
        and item.get("can_do_text_to_speech") is True
        and isinstance(item.get("model_id"), str)
    ]


def fetch_voices(api_key: str) -> list[dict]:
    """다음 페이지 토큰을 따라 사용 가능한 음성을 읽는다."""
    voices = []
    token = None
    seen_tokens = set()
    while True:
        params = {"page_size": 100}
        if token:
            params["next_page_token"] = token
        data = _get_json(api_key, f"{_API_URL}/v2/voices", params=params)
        if not isinstance(data, dict) or not isinstance(data.get("voices"), list):
            raise RuntimeError("ElevenLabs returned an invalid voice list")
        voices.extend(
            {"voice_id": item["voice_id"], "name": item.get("name") or item["voice_id"]}
            for item in data["voices"]
            if isinstance(item, dict)
            and isinstance(item.get("voice_id"), str)
        )
        token = data.get("next_page_token")
        if not data.get("has_more"):
            break
        if not isinstance(token, str) or not token:
            raise RuntimeError("ElevenLabs voice list is missing the next page token")
        if token in seen_tokens:
            raise RuntimeError("ElevenLabs voice pagination token did not advance")
        seen_tokens.add(token)
    return voices


def create_voice_clone(api_key: str, wav_path: str, name: str) -> tuple[str, bool]:
    """참조 WAV를 올려 클론 음성 ID와 추가 인증 필요 여부를 반환한다."""
    _require_api_key(api_key)
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests package is required") from exc

    path = Path(wav_path)
    if not path.is_file():
        raise FileNotFoundError(f"Reference WAV not found: {path}")
    try:
        with path.open("rb") as audio_file:
            response = requests.post(
                f"{_API_URL}/v1/voices/add",
                headers={"xi-api-key": api_key},
                data={"name": name},
                files={"files": (path.name, audio_file, "audio/wav")},
                timeout=_UPLOAD_TIMEOUT,
            )
    except requests.RequestException as exc:
        detail = _redact_secret(str(exc), api_key)
        raise RuntimeError(f"ElevenLabs API request failed: {detail}") from None
    _check_response(response, requests, api_key)
    try:
        result = response.json()
        voice_id = result.get("voice_id") if isinstance(result, dict) else None
        requires_verification = (
            result.get("requires_verification") is True
            if isinstance(result, dict)
            else False
        )
    except (AttributeError, ValueError):
        voice_id = None
    if not isinstance(voice_id, str) or not voice_id:
        detail = _redact_secret(str(getattr(response, "text", "")), api_key).strip()
        detail = detail[:1000]
        raise RuntimeError(detail or "ElevenLabs did not return a voice ID")
    return voice_id, requires_verification


class ElevenLabsTTS(QObject):
    playback_finished = Signal()

    def __init__(self, api_key="", voice_id="",
                 model_id="eleven_multilingual_v2",
                 stability=0.5, similarity_boost=0.75, emotion_enabled=True,
                 tts_volume=1.0):
        super().__init__()
        _require_api_key(api_key)
        self.api_key = api_key
        self.voice_id = voice_id or _DEFAULT_VOICE_ID
        self.model_id = model_id
        self.stability = stability
        self.similarity_boost = similarity_boost
        self.emotion_enabled = bool(emotion_enabled)
        self.tts_volume = tts_volume
        self.is_playing = False
        self._session = None
        self._state_lock = threading.Lock()
        self._active_stop_event = None
        self._active_response = None

        logging.info("ElevenLabs TTS 초기화 완료 (voice_id=%s)", self.voice_id)

    def _get_session(self):
        if self._session is not None:
            return self._session
        try:
            import requests
        except ImportError:
            logging.error("requests 패키지가 필요합니다: pip install requests")
            return None
        self._session = requests.Session()
        return self._session

    def _voice_settings(self, emotion: str) -> dict:
        stability_offset, style_offset = get_emotion_details(emotion)["elevenlabs"]
        if not self.emotion_enabled:
            stability_offset = 0.0
            style_offset = 0.0
        stability = max(0.0, min(1.0, self.stability + stability_offset))
        style = max(0.0, min(1.0, style_offset))
        return {
            "stability": stability,
            "similarity_boost": self.similarity_boost,
            "style": style,
        }

    def _speech_payload(self, text: str, emotion: str) -> dict:
        payload = {"text": text, "model_id": self.model_id}
        if self.model_id.startswith(("eleven_v3", "eleven_v4")):
            tag = get_emotion_details(emotion).get("elevenlabs_tag", "")
            if self.emotion_enabled and tag:
                payload["text"] = f"{tag} {text}"
        else:
            payload["voice_settings"] = self._voice_settings(emotion)
        return payload

    def _close_response(self, response):
        try:
            response.close()
        finally:
            with self._state_lock:
                if self._active_response is response:
                    self._active_response = None

    def _close_active_response(self):
        with self._state_lock:
            response = self._active_response
        if response is not None:
            try:
                self._close_response(response)
            except Exception as exc:
                logging.debug("ElevenLabs response close failed: %s", exc)

    def _finish_playback(self, stop_event):
        with self._state_lock:
            if self._active_stop_event is not stop_event:
                return
            self._active_stop_event = None
            self.is_playing = False
        self.playback_finished.emit()

    def _complete_response(self, response, stop_event):
        self._close_response(response)
        self._finish_playback(stop_event)

    def _play_response(self, response, stop_event, started_at):
        from audio.audio_manager import get_output_device_index

        chunks = response_pcm_chunks(response, "ElevenLabs", 1024)
        bytes_received = 0
        first_chunk_at = None

        def pcm_chunks():
            nonlocal bytes_received, first_chunk_at
            for chunk in chunks:
                if stop_event.is_set():
                    return
                if not chunk:
                    continue
                if first_chunk_at is None:
                    first_chunk_at = time.time()
                    logging.info(
                        "[TTS] ElevenLabs 첫 청크: %.2fs",
                        first_chunk_at - started_at,
                    )
                bytes_received += len(chunk)
                yield chunk

        def open_stream():
            with get_audio_output_lock():
                return GlobalAudio.open_stream(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=_SAMPLE_RATE,
                    output=True,
                    output_device_index=get_output_device_index(),
                )

        def close_stream(stream):
            with get_audio_output_lock():
                GlobalAudio.close_stream(stream)

        def on_complete(_success):
            self._complete_response(response, stop_event)

        success = play_pcm_stream(
            open_stream,
            close_stream,
            pcm_chunks(),
            stop_event,
            _SAMPLE_RATE,
            on_start=lambda: logging.info("[TTS] ElevenLabs 재생 시작"),
            on_complete=on_complete,
            volume=self.tts_volume,
        )
        if not success or stop_event.is_set():
            return False
        logging.info(
            "[TTS] ElevenLabs 수신 완료: %.2fs, %s bytes (%.2fs PCM)",
            time.time() - started_at,
            f"{bytes_received:,}",
            bytes_received / (_SAMPLE_RATE * 2),
        )
        return True

    def speak(
        self,
        text: str,
        emotion: str = DEFAULT_EMOTION,
        stop_event: threading.Event | None = None,
    ) -> bool:
        if not text:
            return False
        session = self._get_session()
        if session is None:
            return False

        stop_event = stop_event or threading.Event()
        with self._state_lock:
            self._active_stop_event = stop_event
            self.is_playing = True
        response = None
        try:
            started_at = time.time()
            if stop_event.is_set():
                return False
            url = f"{_API_URL}/v1/text-to-speech/{self.voice_id}/stream"
            response = session.post(
                url,
                params={"output_format": "pcm_24000"},
                json=self._speech_payload(text, emotion),
                headers={
                    "xi-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=30,
                stream=True,
            )
            with self._state_lock:
                self._active_response = response
            response.raise_for_status()
            return self._play_response(response, stop_event, started_at)
        except Exception as exc:
            detail = _redact_secret(str(exc), self.api_key)
            logging.error("ElevenLabs TTS speak 오류: %s", detail)
            return False
        finally:
            try:
                if response is not None:
                    self._close_response(response)
            except Exception as exc:
                logging.debug("ElevenLabs response cleanup failed: %s", exc)
            self._finish_playback(stop_event)

    def stop(self) -> None:
        with self._state_lock:
            stop_event = self._active_stop_event
        if stop_event is not None:
            stop_event.set()
        # 읽는 중인 응답을 닫으면 읽기 타임아웃까지 막힐 수 있어 호출 스레드를 붙잡지 않는다.
        threading.Thread(target=self._close_active_response, daemon=True).start()

    def cleanup(self):
        self.stop()
        try:
            if self._session is not None:
                self._session.close()
                self._session = None
        except Exception as exc:
            logging.debug("ElevenLabs 세션 정리 중 무시된 오류: %s", exc)
        # 전역 PyAudio 인스턴스는 AriCore.cleanup()의 GlobalAudio.terminate()에서만 종료한다.

    def __del__(self):
        try:
            self.cleanup()
        except Exception as exc:
            logging.debug("ElevenLabs TTS 소멸자 정리 실패: %s", exc)

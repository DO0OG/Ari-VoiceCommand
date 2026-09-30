"""로컬 경량 GPT-SoVITS 음성 합성 제공자."""

import logging
import os
import re
import threading

import numpy as np
import pyaudio
from PySide6.QtCore import QObject, Signal

from audio.audio_manager import GlobalAudio, get_audio_output_lock
from core.emotions import DEFAULT_EMOTION, normalize_emotion
from tts.gsv.engine import GSVEngine, ReferenceFeatures
from tts.gsv.model_store import get_model_dir, is_model_installed
from tts.gsv.text_splitter import split_text
from tts.pcm_playback import write_pcm_chunks
from tts.voice_reference import get_reference_text, get_reference_wav


_HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
_JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")


def detect_language(text: str) -> str:
    """문장에 포함된 문자로 한국어·일본어·영어를 고른다."""
    if _HANGUL_RE.search(text):
        return "ko"
    if _JAPANESE_RE.search(text):
        return "ja"
    return "en"


def reference_cache_key(wav_path: str, text: str, language: str) -> tuple[str, int, str, str]:
    """참조 음성 변경을 반영하는 캐시 키를 만든다."""
    path = os.path.abspath(wav_path)
    return path, os.stat(path).st_mtime_ns, text, language


class _CombinedStopEvent:
    def __init__(self, internal: threading.Event, external: threading.Event | None):
        self._internal = internal
        self._external = external

    def is_set(self) -> bool:
        return self._internal.is_set() or bool(
            self._external and self._external.is_set()
        )


class LocalGSVTTS(QObject):
    playback_finished = Signal()

    def __init__(self, settings: dict | None = None):
        super().__init__()
        self.settings = dict(settings or {})
        self.reference_wav = get_reference_wav(self.settings)
        self.reference_text = get_reference_text(self.settings)
        self.reference_language = str(
            self.settings.get("local_gsv_reference_language", "ko") or "ko"
        )
        if self.reference_language not in {"ko", "en", "ja"}:
            self.reference_language = "ko"
        self.device = str(self.settings.get("local_gsv_device", "auto") or "auto")
        self.volume = self._load_volume(self.settings)
        self.is_playing = False
        self.stop_event = threading.Event()
        self._loader_done = threading.Event()
        self._shutdown = threading.Event()
        self._speak_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._reference_lock = threading.Lock()
        self._engine: GSVEngine | None = None
        self._load_error: Exception | None = None
        self._reference_cache: dict[
            tuple[str, int, str, str], ReferenceFeatures
        ] = {}

        # 해시는 설치 때 검증했으므로 여기서는 파일 존재와 크기만 본다(약 750MB 재해시 방지).
        if not is_model_installed(verify_hash=False):
            raise RuntimeError("로컬 GPT-SoVITS 모델이 설치되지 않았습니다.")
        self._loader_thread = threading.Thread(
            target=self._load_engine, name="LocalGSVLoader", daemon=True
        )
        self._loader_thread.start()

    @staticmethod
    def _load_volume(settings: dict) -> float:
        try:
            value = float(settings.get("tts_volume", 1.0))
        except (TypeError, ValueError):
            return 1.0
        return min(max(value, 0.0), 2.0)

    def _load_engine(self) -> None:
        engine = None
        try:
            engine = GSVEngine(get_model_dir(), self.device)
            if self._shutdown.is_set():
                engine.cleanup()
            else:
                self._engine = engine
        except (ImportError, OSError, RuntimeError, ValueError, TypeError) as exc:
            self._load_error = exc
            logging.error("로컬 GPT-SoVITS 모델 로드 실패: %s", exc)
        finally:
            self._loader_done.set()

    def wait_until_warmup_done(self, timeout: float = 300) -> bool:
        """백그라운드 ONNX 세션 초기화를 기다린다."""
        return self._loader_done.wait(timeout)

    def _select_reference(self, emotion: str) -> tuple[str, str, str]:
        references = self.settings.get("local_gsv_emotion_refs", {})
        if not isinstance(references, dict):
            references = {}
        item = references.get(normalize_emotion(emotion))
        if isinstance(item, dict):
            wav_path = str(item.get("wav", "") or "").strip()
            text = str(item.get("text", "") or "").strip()
            if wav_path and text:
                return wav_path, text, self.reference_language
        return self.reference_wav, self.reference_text, self.reference_language

    def _get_reference(self, emotion: str) -> ReferenceFeatures:
        wav_path, text, language = self._select_reference(emotion)
        if not wav_path or not os.path.isfile(wav_path):
            raise FileNotFoundError(f"참조 WAV 파일을 찾을 수 없습니다: {wav_path}")
        if not text:
            raise ValueError("참조 음성의 대본을 입력해야 합니다.")
        key = reference_cache_key(wav_path, text, language)
        with self._reference_lock:
            cached = self._reference_cache.get(key)
            if cached is not None:
                return cached
            if self._engine is None:
                raise RuntimeError("로컬 GPT-SoVITS 세션이 준비되지 않았습니다.")
            reference = self._engine.prepare_reference(wav_path, text, language)
            self._reference_cache[key] = reference
            return reference

    def _should_stop(self, external: threading.Event | None) -> bool:
        return self.stop_event.is_set() or bool(external and external.is_set())

    def _synthesize_pcm(
        self,
        sentence: str,
        emotion: str,
        stop_event: threading.Event | None,
    ) -> bytes | None:
        engine = self._engine
        if engine is None:
            return None
        language = detect_language(sentence)
        reference = self._get_reference(emotion)
        audio = engine.synthesize(
            sentence,
            reference,
            language,
            lambda: self._should_stop(stop_event),
        )
        if audio is None or self._should_stop(stop_event):
            return None
        samples = np.asarray(audio, dtype=np.float32).squeeze()
        if samples.ndim != 1:
            raise ValueError("음성 모델이 모노 오디오를 반환하지 않았습니다.")
        samples = np.clip(samples * self.volume, -1.0, 1.0)
        return (samples * 32767).astype("<i2").tobytes()

    def speak(
        self,
        text: str,
        emotion: str = DEFAULT_EMOTION,
        stop_event: threading.Event | None = None,
    ) -> bool:
        if not text or self._shutdown.is_set():
            return False
        if not self._loader_done.wait(timeout=300):
            logging.error("로컬 GPT-SoVITS 세션 준비 시간이 초과되었습니다.")
            return False
        if self._load_error is not None or self._engine is None:
            logging.error("로컬 GPT-SoVITS 세션을 사용할 수 없습니다.")
            return False

        self._speak_lock.acquire()
        with self._state_lock:
            if self._shutdown.is_set():
                self._speak_lock.release()
                return False
            self.stop_event.clear()
            combined_stop = _CombinedStopEvent(self.stop_event, stop_event)
            self.is_playing = True
        success = False
        stream = None
        try:
            if combined_stop.is_set():
                return False
            from audio.audio_manager import get_output_device_index

            stream = GlobalAudio.open_stream(
                format=pyaudio.paInt16,
                channels=1,
                rate=32000,
                output=True,
                output_device_index=get_output_device_index(),
            )
            success = True
            for sentence in split_text(text):
                if combined_stop.is_set():
                    success = False
                    break
                pcm = self._synthesize_pcm(sentence, emotion, stop_event)
                if not pcm or not write_pcm_chunks(stream, pcm, combined_stop, 32000):
                    success = False
                    break
        except (OSError, RuntimeError, ValueError, ImportError) as exc:
            logging.error("로컬 GPT-SoVITS 합성 실패: %s", exc)
            success = False
        finally:
            if stream is not None:
                with get_audio_output_lock():
                    GlobalAudio.close_stream(stream)
            with self._state_lock:
                self.is_playing = False
            self.playback_finished.emit()
            self._speak_lock.release()
        return success

    def stop(self) -> None:
        with self._state_lock:
            self.stop_event.set()

    def cleanup(self) -> None:
        with self._state_lock:
            self._shutdown.set()
            self.stop_event.set()
        if self._loader_thread.is_alive():
            self._loader_thread.join(timeout=5)
        with self._speak_lock:
            if self._engine is not None:
                self._engine.cleanup()
                self._engine = None
            with self._reference_lock:
                self._reference_cache.clear()
        self.is_playing = False


__all__ = ["LocalGSVTTS", "detect_language", "reference_cache_key"]

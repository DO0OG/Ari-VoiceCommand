"""STT 백엔드 추상화 레이어."""
from __future__ import annotations

import base64
import io
import logging
import os
import queue
import subprocess
import sys
import threading
import wave
from typing import Optional


class STTProvider:
    """STT 백엔드 공통 인터페이스."""

    def transcribe(self, audio_data) -> Optional[str]:
        raise NotImplementedError

    def is_healthy(self) -> bool:
        return True


class GoogleSTTProvider(STTProvider):
    """speech_recognition 기반 Google STT 래퍼."""

    def __init__(self, language: str = "ko-KR"):
        import speech_recognition as sr

        self._language = language
        self._recognizer = sr.Recognizer()

    def transcribe(self, audio_data) -> Optional[str]:
        import speech_recognition as sr

        try:
            return self._recognizer.recognize_google(audio_data, language=self._language)
        except sr.UnknownValueError:
            return None
        except sr.RequestError as exc:
            logging.error(f"[GoogleSTT] 요청 실패: {exc}")
            return None


class WhisperSTTProvider(STTProvider):
    """faster-whisper 기반 오프라인 STT (서브프로세스 격리).

    CTranslate2(MKL)와 torch/numpy(MKL)의 DLL 충돌을 피하기 위해
    Whisper 모델을 별도 프로세스(_whisper_worker.py)에서 실행한다.
    메인 프로세스와는 stdin/stdout base64 IPC로 통신한다.
    """

    _WORKER = os.path.join(os.path.dirname(__file__), "_whisper_worker.py")
    _STARTUP_TIMEOUT_SECONDS = 30.0
    _TRANSCRIBE_TIMEOUT_SECONDS = 20.0

    def __init__(self, model_size: str = "small", device: str = "auto", compute_type: str = "int8"):
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._start_worker()

    def transcribe(self, audio_data) -> Optional[str]:
        try:
            wav_bytes = audio_data.get_wav_data()
            b64 = base64.b64encode(wav_bytes).decode("ascii")
        except Exception as exc:
            logging.error("[WhisperSTT] 오디오 직렬화 실패: %s", exc)
            return None

        with self._lock:
            if not self._ensure_worker_locked():
                return None
            try:
                assert self._proc is not None and self._proc.stdin is not None and self._proc.stdout is not None
                self._proc.stdin.write((b64 + "\n").encode("ascii"))
                self._proc.stdin.flush()
                line = self._read_process_line(self._proc.stdout, self._TRANSCRIBE_TIMEOUT_SECONDS)
                if line is None:
                    logging.error("[WhisperSTT] 전사 응답 timeout — 워커를 재시작합니다.")
                    self._restart_worker_locked("transcribe timeout")
                    return None
                line = line.strip()
                if not line or line == "__NONE__":
                    return None
                return line
            except Exception as exc:
                logging.error("[WhisperSTT] 전사 실패: %s", exc)
                self._restart_worker_locked("transcribe failure")
                return None

    def is_healthy(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def __del__(self):
        try:
            with self._lock:
                self._terminate_worker_locked()
        except Exception as exc:
            logging.debug("[WhisperSTT] 워커 종료 중 오류 (무시): %s", exc)

    def _start_worker(self) -> None:
        actual_device = _resolve_device(self._device)
        logging.info("[WhisperSTT] 워커 시작: %s / %s / %s", self._model_size, actual_device, self._compute_type)
        env = {**os.environ, "KMP_DUPLICATE_LIB_OK": "TRUE"}
        self._proc = subprocess.Popen(  # nosemgrep
            [sys.executable, self._WORKER, self._model_size, actual_device, self._compute_type],  # nosemgrep
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        ready_line = self._read_process_line(self._proc.stdout, self._STARTUP_TIMEOUT_SECONDS) if self._proc.stdout else None
        if ready_line != "READY":
            stderr_out = self._read_stderr_snapshot()
            self._terminate_worker_locked()
            reason = stderr_out or "READY 신호를 받지 못했습니다."
            raise RuntimeError(f"[WhisperSTT] 워커 초기화 실패:\n{reason}")
        logging.info("[WhisperSTT] 워커 준비 완료")

    def _ensure_worker_locked(self) -> bool:
        if self.is_healthy():
            return True
        logging.warning("[WhisperSTT] 비정상 워커 감지 — 재시작합니다.")
        return self._restart_worker_locked("worker unhealthy")

    def _restart_worker_locked(self, reason: str) -> bool:
        logging.warning("[WhisperSTT] 워커 재시작: %s", reason)
        self._terminate_worker_locked()
        try:
            self._start_worker()
            return True
        except Exception as exc:
            logging.error("[WhisperSTT] 워커 재시작 실패: %s", exc)
            return False

    def _terminate_worker_locked(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None and proc.stdin is not None:
                proc.stdin.write(b"QUIT\n")
                proc.stdin.flush()
                proc.wait(timeout=3)
        except Exception:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def _read_stderr_snapshot(self) -> str:
        try:
            if self._proc is None or self._proc.stderr is None:
                return ""
            return self._proc.stderr.read().decode("utf-8", errors="replace").strip()
        except Exception:
            return ""

    def _read_process_line(self, stream, timeout_seconds: float) -> Optional[str]:
        if stream is None:
            return None
        result_queue: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=1)

        def _reader() -> None:
            try:
                result_queue.put(stream.readline())
            except Exception:
                result_queue.put(None)

        threading.Thread(target=_reader, daemon=True).start()
        try:
            raw = result_queue.get(timeout=max(float(timeout_seconds or 0.0), 0.1))
        except queue.Empty:
            return None
        if raw is None:
            return None
        return raw.decode("utf-8", errors="replace").strip()


def _resolve_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _wav_bytes_to_numpy(wav_bytes: bytes):
    """메인 프로세스용 WAV→numpy 변환 (GoogleSTT 등에서는 불필요하지만 테스트용으로 유지)."""
    import numpy as np

    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        frames = wav_file.readframes(wav_file.getnframes())
        sample_width = wav_file.getsampwidth()
        channels = wav_file.getnchannels()

        if sample_width == 1:
            audio = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        elif sample_width == 2:
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        elif sample_width == 4:
            audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            raise ValueError(f"지원하지 않는 오디오 샘플 너비: {sample_width}바이트")

        if channels > 1:
            audio = audio.reshape(-1, channels).mean(axis=1)
        return audio


def create_stt_provider(settings: dict) -> STTProvider:
    provider_name = settings.get("stt_provider", "google")
    if provider_name == "whisper":
        return WhisperSTTProvider(
            model_size=settings.get("whisper_model", "small"),
            device=settings.get("whisper_device", "auto"),
            compute_type=settings.get("whisper_compute_type", "int8"),
        )
    return GoogleSTTProvider(language=settings.get("speech_language", "ko-KR"))

"""STT 백엔드 추상화 레이어."""
from __future__ import annotations

import base64
import io
import logging
import os
import subprocess
import sys
import threading
import wave
from typing import Optional


class STTProvider:
    """STT 백엔드 공통 인터페이스."""

    def transcribe(self, audio_data) -> Optional[str]:
        raise NotImplementedError


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

    def __init__(self, model_size: str = "small", device: str = "auto", compute_type: str = "int8"):
        actual_device = _resolve_device(device)
        logging.info(f"[WhisperSTT] 워커 시작: {model_size} / {actual_device} / {compute_type}")

        env = {**os.environ, "KMP_DUPLICATE_LIB_OK": "TRUE"}
        # _WORKER는 패키지 내부 스크립트 고정 경로; 사용자 입력 아님 — nosec
        cmd = [sys.executable, self._WORKER, model_size, actual_device, compute_type]
        self._proc = subprocess.Popen(  # nosec B603 B607
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

        # 워커가 모델 로드를 완료하고 "READY"를 보낼 때까지 대기
        ready_line = self._proc.stdout.readline().decode("utf-8", errors="replace").strip()
        if ready_line != "READY":
            stderr_out = self._proc.stderr.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"[WhisperSTT] 워커 초기화 실패:\n{stderr_out}")

        self._lock = threading.Lock()
        logging.info("[WhisperSTT] 워커 준비 완료")

    def transcribe(self, audio_data) -> Optional[str]:
        if self._proc.poll() is not None:
            logging.error("[WhisperSTT] 워커 프로세스가 종료됨")
            return None
        try:
            wav_bytes = audio_data.get_wav_data()
            b64 = base64.b64encode(wav_bytes).decode("ascii")
            with self._lock:
                self._proc.stdin.write((b64 + "\n").encode())
                self._proc.stdin.flush()
                line = self._proc.stdout.readline().decode("utf-8", errors="replace").strip()
            if not line or line == "__NONE__":
                return None
            return line
        except Exception as exc:
            logging.error(f"[WhisperSTT] 전사 실패: {exc}")
            return None

    def __del__(self):
        try:
            if self._proc and self._proc.poll() is None:
                self._proc.stdin.write(b"QUIT\n")
                self._proc.stdin.flush()
                self._proc.wait(timeout=3)
        except Exception as exc:
            logging.debug("[WhisperSTT] 워커 종료 중 오류 (무시): %s", exc)


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

"""Genie 참조 음성 WAV 전처리."""

# Genie (MIT), High-Logic, Audio/ReferenceAudio.py에서 오디오 전처리를 이식했습니다.

from __future__ import annotations

import math
import wave

import numpy as np
from scipy.signal import resample_poly


def read_wav(path: str) -> tuple[np.ndarray, int]:
    """PCM WAV를 모노 float32로 읽는다."""
    try:
        with wave.open(path, "rb") as source:
            channels = source.getnchannels()
            sample_rate = source.getframerate()
            sample_width = source.getsampwidth()
            frame_count = source.getnframes()
            if source.getcomptype() != "NONE":
                raise ValueError("압축되지 않은 PCM WAV 파일만 지원합니다.")
            if channels < 1 or sample_rate < 1 or sample_width not in (1, 2, 3, 4):
                raise ValueError("지원하지 않는 WAV 형식입니다.")
            raw = source.readframes(frame_count)
    except (wave.Error, EOFError) as exc:
        raise ValueError("참조 음성은 유효한 PCM WAV 파일이어야 합니다.") from exc

    if sample_width == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128
    elif sample_width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    elif sample_width == 3:
        bytes_ = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        values = (
            bytes_[:, 0].astype(np.int32)
            | (bytes_[:, 1].astype(np.int32) << 8)
            | (bytes_[:, 2].astype(np.int32) << 16)
        )
        values = (values ^ 0x800000) - 0x800000
        samples = values.astype(np.float32) / 8388608
    else:
        samples = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648

    if samples.size % channels:
        raise ValueError("WAV 데이터가 채널 프레임과 맞지 않습니다.")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples.astype(np.float32, copy=False), sample_rate


def resample_audio(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """scipy polyphase 필터로 음성을 재표본화한다."""
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("샘플레이트는 양수여야 합니다.")
    if source_rate == target_rate:
        return np.asarray(samples, dtype=np.float32)
    divisor = math.gcd(source_rate, target_rate)
    result = resample_poly(
        np.asarray(samples, dtype=np.float32),
        target_rate // divisor,
        source_rate // divisor,
    )
    return result.astype(np.float32, copy=False)


def load_reference_audio(path: str) -> tuple[np.ndarray, np.ndarray]:
    """32kHz/16kHz 모노 음성과 끝부분 무음을 반환한다."""
    audio, sample_rate = read_wav(path)
    audio_32k = resample_audio(audio, sample_rate, 32000)
    audio_32k = np.concatenate((audio_32k, np.zeros(9600, dtype=np.float32)))
    audio_16k = resample_audio(audio_32k, 32000, 16000)
    return audio_32k[None, :], audio_16k[None, :]

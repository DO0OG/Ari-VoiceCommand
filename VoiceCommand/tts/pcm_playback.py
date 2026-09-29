"""PCM 오디오를 취소 가능한 짧은 조각으로 재생한다."""

import threading

from audio.audio_manager import get_audio_output_lock


def write_pcm_chunks(
    stream, pcm: bytes, stop_event: threading.Event, sample_rate: int
) -> bool:
    """모노 16비트 PCM을 최대 100ms 조각으로 쓴다."""
    chunk_bytes = max(2, sample_rate * 2 // 10)
    for offset in range(0, len(pcm), chunk_bytes):
        if stop_event.is_set():
            return False
        with get_audio_output_lock():
            stream.write(pcm[offset : offset + chunk_bytes])
    return bool(pcm) and not stop_event.is_set()

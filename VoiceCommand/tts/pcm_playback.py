"""PCM 오디오를 취소 가능한 짧은 조각으로 재생한다."""

import math
import threading
from collections.abc import Callable, Iterable

import numpy as np

from audio.audio_manager import get_audio_output_lock


def write_pcm_chunks(
    stream,
    pcm: bytes,
    stop_event: threading.Event,
    sample_rate: int,
    on_write: Callable[[], None] | None = None,
    volume: float = 1.0,
) -> bool:
    """모노 16비트 PCM을 최대 100ms 조각으로 쓴다."""
    try:
        volume = float(volume)
    except (TypeError, ValueError):
        volume = 1.0
    if not math.isfinite(volume):
        volume = 1.0
    volume = min(max(volume, 0.0), 2.0)
    sample_bytes = len(pcm) & ~1
    if volume != 1.0 and sample_bytes:
        samples = np.frombuffer(pcm[:sample_bytes], dtype=np.int16).astype(np.float32)
        pcm = (
            np.clip(samples * volume, -32768, 32767).astype(np.int16).tobytes()
            + pcm[sample_bytes:]
        )

    chunk_bytes = max(2, sample_rate * 2 // 10)
    for offset in range(0, len(pcm), chunk_bytes):
        if stop_event.is_set():
            return False
        with get_audio_output_lock():
            stream.write(pcm[offset : offset + chunk_bytes])
        if on_write:
            on_write()
    return bool(pcm) and not stop_event.is_set()


def write_pcm_stream_chunks(
    stream,
    chunks: Iterable[bytes],
    stop_event: threading.Event,
    sample_rate: int,
    on_start: Callable[[], None] | None = None,
    volume: float = 1.0,
) -> bool:
    """스트리밍 모노 S16LE PCM을 쓰고 청크 경계의 홀수 바이트를 보관한다."""
    remainder = b""
    wrote_audio = False

    def on_first_write():
        nonlocal wrote_audio
        if not wrote_audio and on_start:
            on_start()
        wrote_audio = True

    for chunk in chunks:
        if stop_event.is_set():
            return False
        if not chunk:
            continue

        pcm = remainder + chunk
        complete_bytes = len(pcm) & ~1
        remainder = pcm[complete_bytes:]
        if complete_bytes:
            if not write_pcm_chunks(
                stream,
                pcm[:complete_bytes],
                stop_event,
                sample_rate,
                on_write=on_first_write,
                volume=volume,
            ):
                return False

    if stop_event.is_set():
        return False
    if remainder:
        raise ValueError("PCM stream ended with an incomplete 16-bit sample")
    return wrote_audio


def response_pcm_chunks(response, provider: str, chunk_size: int | None):
    """Reject successful HTTP responses that do not contain an audio body."""
    raw_content_type = (getattr(response, "headers", None) or {}).get(
        "Content-Type", ""
    )
    if not isinstance(raw_content_type, str):
        raw_content_type = str(raw_content_type)
    content_type = raw_content_type.split(";", 1)[0].strip().lower()
    is_audio = content_type.startswith("audio/") and bool(content_type[6:])
    if is_audio or content_type == "application/octet-stream":
        return response.iter_content(chunk_size=chunk_size)

    try:
        body = next(response.iter_content(chunk_size=256), b"")
    except Exception:
        body = b""
    if isinstance(body, bytes):
        snippet = body[:256].decode("utf-8", errors="replace")
    else:
        snippet = str(body)[:256]
    raise ValueError(
        f"{provider} expected an audio response, got "
        f"{content_type or 'missing Content-Type'}; body={snippet!r}"
    )


def play_pcm_stream(
    open_stream: Callable[[], object],
    close_stream: Callable[[object], None],
    chunks: Iterable[bytes],
    stop_event: threading.Event,
    sample_rate: int,
    on_start: Callable[[], None] | None = None,
    on_complete: Callable[[bool], None] | None = None,
    volume: float = 1.0,
) -> bool:
    """Open, stream, close, then report whether playback completed."""
    stream = None
    success = False
    try:
        if not stop_event.is_set():
            stream = open_stream()
            success = write_pcm_stream_chunks(
                stream, chunks, stop_event, sample_rate, on_start=on_start,
                volume=volume,
            )
        return success
    finally:
        try:
            if stream is not None:
                close_stream(stream)
        except Exception:
            success = False
            raise
        finally:
            if on_complete:
                on_complete(success and not stop_event.is_set())

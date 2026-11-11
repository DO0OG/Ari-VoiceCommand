"""Decode MP3 audio to mono signed 16-bit PCM using the bundled PyAV codecs."""

import io


def decode_mp3_to_pcm(mp3_data: bytes, sample_rate: int) -> bytes:
    """Decode MP3 bytes without invoking a system ffmpeg executable."""
    return _decode_to_pcm(mp3_data, sample_rate, "mp3", "MP3")


class AudioTooLongError(ValueError):
    """Raised when decoded audio exceeds the caller's sample limit."""


def decode_ogg_to_pcm(ogg_data: bytes, sample_rate: int, max_samples: int | None = None) -> bytes:
    """Decode OGG (Opus/Vorbis) bytes, such as a Telegram voice note, to mono s16 PCM.

    Decoding stops with AudioTooLongError as soon as more than ``max_samples`` samples are produced.
    """
    return _decode_to_pcm(ogg_data, sample_rate, "ogg", "OGG", max_samples)


def _decode_to_pcm(data: bytes, sample_rate: int, container_format: str, label: str,
                   max_samples: int | None = None) -> bytes:
    if not data:
        raise ValueError(f"{label} data is empty")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")

    import av

    container = av.open(io.BytesIO(data), format=container_format)
    try:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)
        chunks = []
        total_bytes = 0

        def collect(frames) -> None:
            nonlocal total_bytes
            for frame in frames:
                chunk = frame.to_ndarray().tobytes()
                total_bytes += len(chunk)
                if max_samples is not None and total_bytes > max_samples * 2:
                    raise AudioTooLongError(f"{label} audio is longer than {max_samples} samples")
                chunks.append(chunk)

        for frame in container.decode(audio=0):
            collect(resampler.resample(frame))
        collect(resampler.resample(None))
        pcm = b"".join(chunks)
    finally:
        container.close()

    if not pcm:
        raise ValueError(f"{label} contained no decodable audio frames")
    return pcm
"""Decode MP3 audio to mono signed 16-bit PCM using the bundled PyAV codecs."""

import io


def decode_mp3_to_pcm(mp3_data: bytes, sample_rate: int) -> bytes:
    """Decode MP3 bytes without invoking a system ffmpeg executable."""
    if not mp3_data:
        raise ValueError("MP3 data is empty")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")

    import av

    container = av.open(io.BytesIO(mp3_data), format="mp3")
    try:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)
        pcm_frames = []
        for frame in container.decode(audio=0):
            pcm_frames.extend(resampler.resample(frame))
        pcm_frames.extend(resampler.resample(None))
        pcm = b"".join(frame.to_ndarray().tobytes() for frame in pcm_frames)
    finally:
        container.close()

    if not pcm:
        raise ValueError("MP3 contained no decodable audio frames")
    return pcm
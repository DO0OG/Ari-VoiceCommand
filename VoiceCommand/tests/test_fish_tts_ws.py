import io
import threading
import unittest
import wave
from unittest.mock import patch

from tts.fish_tts_ws import (
    FishTTSWebSocket,
    _estimate_pcm_duration_seconds,
    _playback_join_timeout,
)


class FishTTSWebSocketTests(unittest.TestCase):
    def test_estimate_pcm_duration_seconds_from_wav_params(self):
        duration = _estimate_pcm_duration_seconds(
            frame_bytes=3_308_630,
            sample_rate=44_100,
            channels=1,
            sample_width=2,
        )

        self.assertAlmostEqual(duration, 37.5, places=1)

    def test_playback_join_timeout_scales_with_long_audio_duration(self):
        timeout = _playback_join_timeout(37.5)

        self.assertGreater(timeout, 37.5)
        self.assertGreater(timeout, 30.0)

    def test_playback_join_timeout_keeps_short_audio_floor(self):
        self.assertEqual(_playback_join_timeout(3.0), 30.0)

    def test_speak_streams_wav_chunks_and_emits_completion(self):
        class _DummySignal:
            def __init__(self):
                self.emitted = 0

            def emit(self):
                self.emitted += 1

        class _FakeAudioStream:
            def __init__(self):
                self.writes = []

            def write(self, data):
                self.writes.append(data)

            def is_active(self):
                return False

            def close(self):
                return None

        class _FakeAudio:
            def __init__(self):
                self.stream = _FakeAudioStream()

            def get_format_from_width(self, width):
                return width

            def open(self, **_kwargs):
                return self.stream

        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8000)
            handle.writeframes(b"\x00\x00" * 800)
        wav_bytes = wav_buffer.getvalue()

        with patch.object(FishTTSWebSocket, "__init__", lambda self, *args, **kwargs: None):
            tts = FishTTSWebSocket()
        tts.session = type(
            "_Session",
            (),
            {"tts": lambda self, req: iter([wav_bytes[:32], wav_bytes[32:]])},
        )()
        tts.reference_id = ""
        tts.pa = _FakeAudio()
        tts.is_playing = False
        tts.play_thread = None
        tts.stop_event = threading.Event()
        tts.playback_finished = _DummySignal()

        result = tts.speak("안녕하세요")

        self.assertTrue(result)
        self.assertFalse(tts.is_playing)
        self.assertEqual(tts.playback_finished.emitted, 1)
        self.assertTrue(tts.pa.stream.writes)


if __name__ == "__main__":
    unittest.main()

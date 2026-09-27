import io
import threading
import unittest
import wave
from unittest.mock import patch

import ormsgpack

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
        sent = {}

        def _fake_stream(text):
            sent["text"] = text
            return iter([wav_bytes[:32], wav_bytes[32:]])

        tts._stream_tts = _fake_stream
        tts.reference_id = ""
        tts.model = "s2.1-pro-free"
        tts.pa = _FakeAudio()
        tts.is_playing = False
        tts.play_thread = None
        tts.stop_event = threading.Event()
        tts.playback_finished = _DummySignal()

        result = tts.speak("안녕하세요")

        self.assertTrue(result)
        self.assertEqual(sent["text"], "안녕하세요")
        self.assertFalse(tts.is_playing)
        self.assertEqual(tts.playback_finished.emitted, 1)
        self.assertTrue(tts.pa.stream.writes)

    def test_stream_tts_posts_sdk_compatible_msgpack_request(self):
        class _FakeResponse:
            status_code = 200

            def __init__(self):
                self.closed = False

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.closed = True

            def iter_content(self, chunk_size=None):
                return iter([b"audio"])

        response = _FakeResponse()
        with patch.object(FishTTSWebSocket, "__init__", lambda self, *args, **kwargs: None):
            tts = FishTTSWebSocket()
        tts.api_key = "test-api-key"
        tts.reference_id = "voice-123"
        tts.model = "s2.1-pro-free"

        with patch("tts.fish_tts_ws.requests.post", return_value=response) as post:
            chunks = list(tts._stream_tts("Hello Fish Audio"))

        self.assertEqual(chunks, [b"audio"])
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.fish.audio/v1/tts")
        self.assertEqual(
            kwargs["headers"],
            {
                "Authorization": "Bearer test-api-key",
                "Content-Type": "application/msgpack",
                "model": "s2.1-pro-free",
            },
        )
        self.assertEqual(
            ormsgpack.unpackb(kwargs["data"]),
            {
                "text": "Hello Fish Audio",
                "chunk_length": 200,
                "format": "wav",
                "sample_rate": None,
                "mp3_bitrate": 128,
                "opus_bitrate": 32,
                "references": [],
                "reference_id": "voice-123",
                "normalize": True,
                "latency": "balanced",
                "prosody": None,
                "top_p": 0.7,
                "temperature": 0.7,
            },
        )
        self.assertTrue(kwargs["stream"])
        self.assertEqual(kwargs["timeout"], (10, 60))
        self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()

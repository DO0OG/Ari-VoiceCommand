import threading
import unittest
from unittest.mock import patch

import ormsgpack
from PySide6.QtCore import Qt

from audio.audio_manager import GlobalAudio
from tts.fish_tts_ws import FishTTSWebSocket


class _FakeAudioStream:
    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(data)


class _FakeAudio:
    @staticmethod
    def get_format_from_width(width):
        return width


class _FakeResponse:
    status_code = 200

    def __init__(self, chunks=(), content_type="audio/pcm"):
        self.headers = {"Content-Type": content_type}
        self.chunks = chunks
        self.closed = False

    def iter_content(self, chunk_size=None):
        self.chunk_size = chunk_size
        return iter(self.chunks)

    def close(self):
        self.closed = True


class FishTTSWebSocketTests(unittest.TestCase):
    def _provider(self):
        with patch.object(GlobalAudio, "get_instance", return_value=_FakeAudio()):
            return FishTTSWebSocket(api_key="test-api-key", reference_id="voice-123")

    def test_speak_writes_first_pcm_before_response_finishes(self):
        stream = _FakeAudioStream()

        class _StreamingResponse(_FakeResponse):
            def __init__(self):
                super().__init__()
                self.complete = False
                self.first_write_before_complete = False

            def iter_content(self, chunk_size=None):
                self.chunk_size = chunk_size
                yield b"\x01"
                yield b"\x02\x03"
                self.first_write_before_complete = bool(stream.writes) and not self.complete
                yield b"\x04"
                self.complete = True

        response = _StreamingResponse()
        provider = self._provider()
        provider._stream_tts = lambda _text: response
        finished = []
        provider.playback_finished.connect(
            lambda: finished.append(True), Qt.ConnectionType.DirectConnection
        )

        with (
            patch.object(GlobalAudio, "open_stream", return_value=stream) as open_stream,
            patch.object(GlobalAudio, "close_stream") as close_stream,
            patch("audio.audio_manager.get_output_device_index", return_value=3),
        ):
            self.assertTrue(provider.speak("hello"))

        self.assertTrue(response.first_write_before_complete)
        self.assertEqual(b"".join(stream.writes), b"\x01\x02\x03\x04")
        self.assertTrue(response.closed)
        self.assertFalse(provider.is_playing)
        self.assertEqual(finished, [True])
        self.assertEqual(open_stream.call_args.kwargs["rate"], 44100)
        self.assertEqual(open_stream.call_args.kwargs["output_device_index"], 3)
        close_stream.assert_called_once()

    def test_speak_rejects_non_audio_success_response(self):
        response = _FakeResponse([b'{"message":"not audio"}'], "application/json")
        provider = self._provider()
        provider._stream_tts = lambda _text: response
        finished = []
        provider.playback_finished.connect(
            lambda: finished.append(True), Qt.ConnectionType.DirectConnection
        )

        with patch.object(GlobalAudio, "open_stream") as open_stream:
            self.assertFalse(provider.speak("hello"))

        self.assertTrue(response.closed)
        self.assertFalse(provider.is_playing)
        self.assertEqual(finished, [True])
        open_stream.assert_not_called()

    def test_speak_redacts_api_key_from_error_log(self):
        provider = self._provider()

        def fail_request(_text):
            raise RuntimeError(f"failed with {provider.api_key}")

        provider._stream_tts = fail_request

        with self.assertLogs(level="ERROR") as captured:
            self.assertFalse(provider.speak("hello"))

        self.assertNotIn(provider.api_key, "\n".join(captured.output))
        self.assertIn("[redacted]", "\n".join(captured.output))

    def test_stop_cancels_worker_speak_and_emits_once(self):
        read_started = threading.Event()
        response_closed = threading.Event()
        stream = _FakeAudioStream()

        class _BlockingResponse(_FakeResponse):
            def iter_content(self, chunk_size=None):
                def chunks():
                    read_started.set()
                    response_closed.wait(timeout=3)
                    if False:
                        yield b""

                return chunks()

            def close(self):
                super().close()
                response_closed.set()

        response = _BlockingResponse()
        provider = self._provider()
        provider._stream_tts = lambda _text: response
        finished = []
        provider.playback_finished.connect(
            lambda: finished.append(True), Qt.ConnectionType.DirectConnection
        )
        result = []

        with (
            patch.object(GlobalAudio, "open_stream", return_value=stream),
            patch.object(GlobalAudio, "close_stream"),
            patch("audio.audio_manager.get_output_device_index", return_value=0),
        ):
            worker = threading.Thread(target=lambda: result.append(provider.speak("hello")))
            worker.start()
            self.assertTrue(read_started.wait(timeout=2))
            stop_event = provider._active_stop_event
            provider.stop()
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertTrue(stop_event.is_set())
        self.assertTrue(response.closed)
        self.assertFalse(result[0])
        self.assertFalse(provider.is_playing)
        self.assertEqual(finished, [True])

    def test_output_device_override_is_read_on_speak_caller_thread(self):
        from audio.audio_manager import get_configured_output_device_name, output_device_override

        provider = self._provider()
        provider._stream_tts = lambda _text: _FakeResponse([b"\x00\x00"])
        stream = _FakeAudioStream()
        selected = []
        lookup_threads = []

        def get_device_index():
            selected.append(get_configured_output_device_name())
            lookup_threads.append(threading.current_thread())
            return 17

        with (
            output_device_override("Diagnostic Device"),
            patch.object(GlobalAudio, "open_stream", return_value=stream) as open_stream,
            patch.object(GlobalAudio, "close_stream"),
            patch("audio.audio_manager.get_output_device_index", side_effect=get_device_index),
        ):
            caller_thread = threading.current_thread()
            self.assertTrue(provider.speak("hello"))

        self.assertEqual(selected, ["Diagnostic Device"])
        self.assertEqual(lookup_threads, [caller_thread])
        self.assertEqual(open_stream.call_args.kwargs["output_device_index"], 17)

    def test_stream_tts_posts_pcm_request(self):
        response = _FakeResponse()
        provider = self._provider()

        with patch("tts.fish_tts_ws.requests.post", return_value=response) as post:
            self.assertIs(provider._stream_tts("Hello Fish Audio"), response)

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
                "format": "pcm",
                "sample_rate": 44100,
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


if __name__ == "__main__":
    unittest.main()

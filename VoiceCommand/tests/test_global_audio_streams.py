import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from audio.audio_manager import GlobalAudio


class _ObservedRLock:
    def __init__(self):
        self._lock = threading.RLock()
        self.depth = 0

    @property
    def held(self):
        return self.depth > 0

    def __enter__(self):
        self._lock.acquire()
        self.depth += 1
        return self

    def __exit__(self, *_args):
        self.depth -= 1
        self._lock.release()


class GlobalAudioStreamTests(unittest.TestCase):
    def test_get_instance_creates_instance_under_api_lock(self):
        api_lock = _ObservedRLock()
        audio = object()

        def create_audio():
            self.assertTrue(api_lock.held)
            return audio

        pyaudio_module = SimpleNamespace(PyAudio=create_audio)
        with (
            patch.object(GlobalAudio, "_pa_api_lock", api_lock),
            patch.object(GlobalAudio, "_instance", None),
            patch.dict(sys.modules, {"pyaudio": pyaudio_module}),
        ):
            self.assertIs(GlobalAudio.get_instance(), audio)

        self.assertFalse(api_lock.held)

    def test_open_stream_calls_pyaudio_under_api_lock(self):
        api_lock = _ObservedRLock()
        stream = Mock()
        audio = Mock()

        def open_under_lock(**kwargs):
            self.assertTrue(api_lock.held)
            self.assertEqual(kwargs, {"rate": 16000, "input": True})
            return stream

        audio.open.side_effect = open_under_lock
        with (
            patch.object(GlobalAudio, "_pa_api_lock", api_lock),
            patch.object(GlobalAudio, "_instance", audio),
        ):
            self.assertIs(
                GlobalAudio.open_stream(rate=16000, input=True),
                stream,
            )

        self.assertFalse(api_lock.held)

    def test_close_stream_stops_active_stream_and_closes_under_api_lock(self):
        api_lock = _ObservedRLock()
        stream = Mock()
        stream.is_active.return_value = True
        stream.stop_stream.side_effect = lambda: self.assertTrue(api_lock.held)
        stream.close.side_effect = lambda: self.assertTrue(api_lock.held)

        with patch.object(GlobalAudio, "_pa_api_lock", api_lock):
            GlobalAudio.close_stream(stream)

        stream.is_active.assert_called_once_with()
        stream.stop_stream.assert_called_once_with()
        stream.close.assert_called_once_with()
        self.assertFalse(api_lock.held)

    def test_close_stream_none_is_safe(self):
        api_lock = Mock()
        with patch.object(GlobalAudio, "_pa_api_lock", api_lock):
            GlobalAudio.close_stream(None)

        api_lock.assert_not_called()

    def test_close_stream_ignores_closed_stream_errors(self):
        stream = Mock()
        stream.is_active.side_effect = OSError("stream is closed")
        stream.close.side_effect = OSError("stream is closed")

        GlobalAudio.close_stream(stream)

        stream.close.assert_called_once_with()

    def test_terminate_runs_under_api_lock(self):
        api_lock = _ObservedRLock()
        audio = Mock()
        audio.terminate.side_effect = lambda: self.assertTrue(api_lock.held)

        with (
            patch.object(GlobalAudio, "_pa_api_lock", api_lock),
            patch.object(GlobalAudio, "_instance", audio),
        ):
            GlobalAudio.terminate()
            self.assertIsNone(GlobalAudio._instance)

        self.assertFalse(api_lock.held)


if __name__ == "__main__":
    unittest.main()

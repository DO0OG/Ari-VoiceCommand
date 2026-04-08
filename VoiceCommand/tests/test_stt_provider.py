import unittest
from types import SimpleNamespace
from unittest.mock import patch


from audio.simple_wake import SimpleWakeWord
from core.stt_provider import WhisperSTTProvider


class _FakePipe:
    def __init__(self):
        self.writes = []

    def write(self, payload):
        self.writes.append(payload)

    def flush(self):
        return None


class _FakeStream:
    def __init__(self, read_payload=b""):
        self._read_payload = read_payload

    def readline(self):
        return b""

    def read(self):
        return self._read_payload


class _FakeProcess:
    def __init__(self, stderr_payload=b"stderr"):
        self.stdin = _FakePipe()
        self.stdout = _FakeStream()
        self.stderr = _FakeStream(stderr_payload)
        self._alive = True
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self._alive else 0

    def wait(self, timeout=None):
        self._alive = False
        return 0

    def terminate(self):
        self.terminated = True
        self._alive = False

    def kill(self):
        self.killed = True
        self._alive = False


class _FakeAudioData:
    def get_wav_data(self):
        return b"wav-bytes"


class _ExplodingProcess(_FakeProcess):
    def wait(self, timeout=None):
        raise RuntimeError("wait failed")

    def terminate(self):
        raise RuntimeError("terminate failed")

    def kill(self):
        raise RuntimeError("kill failed")


class STTProviderTests(unittest.TestCase):
    def test_startup_timeout_raises_and_terminates_worker(self):
        fake_proc = _FakeProcess(stderr_payload=b"startup timeout")

        with patch("core.stt_provider.subprocess.Popen", return_value=fake_proc):
            with patch.object(WhisperSTTProvider, "_read_process_line", return_value=None):
                with self.assertRaises(RuntimeError):
                    WhisperSTTProvider(device="cpu")

        self.assertFalse(fake_proc._alive)

    def test_transcribe_timeout_restarts_worker(self):
        first_proc = _FakeProcess()
        second_proc = _FakeProcess()

        with patch("core.stt_provider.subprocess.Popen", side_effect=[first_proc, second_proc]):
            with patch.object(WhisperSTTProvider, "_read_process_line", side_effect=["READY", None, "READY"]):
                provider = WhisperSTTProvider(device="cpu")
                result = provider.transcribe(_FakeAudioData())

        self.assertIsNone(result)
        self.assertFalse(first_proc._alive)
        self.assertTrue(second_proc._alive)

    def test_wake_word_refresh_recreates_unhealthy_provider(self):
        settings = {
            "wake_words": ["아리야"],
            "stt_energy_threshold": 300,
            "stt_dynamic_energy": True,
            "stt_provider": "whisper",
            "whisper_model": "small",
            "whisper_device": "auto",
            "whisper_compute_type": "int8",
        }
        unhealthy = SimpleNamespace(is_healthy=lambda: False)
        healthy = SimpleNamespace(is_healthy=lambda: True)
        wake = SimpleWakeWord.__new__(SimpleWakeWord)
        wake.wake_words = ["아리야"]
        wake.recognizer = SimpleNamespace(energy_threshold=0, dynamic_energy_threshold=False)
        wake._provider_signature = (
            "whisper",
            "small",
            "auto",
            "int8",
        )
        wake._stt = unhealthy
        wake._calibrated = True

        with patch("audio.simple_wake.ConfigManager.load_settings", return_value=settings):
            with patch("audio.simple_wake.create_stt_provider", return_value=healthy):
                wake.refresh_settings()

        self.assertIs(wake._stt, healthy)
        self.assertFalse(wake._calibrated)

    def test_terminate_worker_logs_each_fallback_failure(self):
        provider = WhisperSTTProvider.__new__(WhisperSTTProvider)
        provider._proc = _ExplodingProcess()

        with patch("core.stt_provider.logging.debug") as debug_log:
            provider._terminate_worker_locked()

        self.assertIsNone(provider._proc)
        self.assertEqual(debug_log.call_count, 3)


if __name__ == "__main__":
    unittest.main()

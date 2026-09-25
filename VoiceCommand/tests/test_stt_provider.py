import base64
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


from audio.simple_wake import SimpleWakeWord
from core.stt_provider import WhisperSTTProvider, create_stt_provider


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
        stderr_read_while_running = []
        read_stderr = fake_proc.stderr.read

        def read_stderr_after_shutdown():
            stderr_read_while_running.append(fake_proc.poll() is None)
            return read_stderr()

        fake_proc.stderr.read = read_stderr_after_shutdown

        with patch("core.stt_provider.subprocess.Popen", return_value=fake_proc):
            with patch.object(WhisperSTTProvider, "_read_process_line", return_value=None):
                with self.assertRaises(RuntimeError):
                    WhisperSTTProvider(device="cpu")

        self.assertFalse(fake_proc._alive)
        self.assertEqual(stderr_read_while_running, [False])

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

    def test_stderr_snapshot_does_not_read_from_a_live_worker(self):
        provider = WhisperSTTProvider.__new__(WhisperSTTProvider)
        proc = _FakeProcess(stderr_payload=b"not ready")
        stderr_reads = []
        original_read = proc.stderr.read
        proc.stderr.read = lambda: (stderr_reads.append(True) or original_read())

        provider._proc = proc
        result = provider._read_stderr_snapshot(proc)

        self.assertEqual(result, "")
        self.assertEqual(stderr_reads, [])

    def test_source_worker_command_passes_normalized_speech_language(self):
        fake_proc = _FakeProcess()

        with patch("core.stt_provider.subprocess.Popen", return_value=fake_proc) as popen:
            with patch.object(WhisperSTTProvider, "_read_process_line", return_value="READY"):
                provider = WhisperSTTProvider(device="cpu", language="en-US")

        self.assertEqual(
            popen.call_args.args[0],
            [
                sys.executable,
                WhisperSTTProvider._WORKER,
                "small",
                "cpu",
                "int8",
                "en",
            ],
        )
        provider._terminate_worker_locked()

    def test_frozen_worker_command_reenters_executable_with_worker_sentinel(self):
        fake_proc = _FakeProcess()

        with patch("core.stt_provider.subprocess.Popen", return_value=fake_proc) as popen:
            with patch.object(WhisperSTTProvider, "_read_process_line", return_value="READY"):
                with patch.object(sys, "frozen", True, create=True):
                    provider = WhisperSTTProvider(device="cpu", language="ja-JP")

        self.assertEqual(
            popen.call_args.args[0],
            [
                sys.executable,
                "--ari-whisper-worker",
                "small",
                "cpu",
                "int8",
                "ja",
            ],
        )
        provider._terminate_worker_locked()

    def test_nuitka_worker_command_uses_compiled_module_marker(self):
        fake_proc = _FakeProcess()

        with patch("core.stt_provider.subprocess.Popen", return_value=fake_proc) as popen:
            with patch.object(WhisperSTTProvider, "_read_process_line", return_value="READY"):
                with patch.dict("core.stt_provider.__dict__", {"__compiled__": object()}):
                    provider = WhisperSTTProvider(device="cpu", language="ko-KR")

        self.assertEqual(
            popen.call_args.args[0],
            [
                sys.executable,
                "--ari-whisper-worker",
                "small",
                "cpu",
                "int8",
                "ko",
            ],
        )
        provider._terminate_worker_locked()

    def test_create_whisper_provider_passes_configured_speech_language(self):
        with patch("core.stt_provider.WhisperSTTProvider") as provider_factory:
            create_stt_provider({"stt_provider": "whisper", "speech_language": "ja-JP"})

        self.assertEqual(provider_factory.call_args.kwargs["language"], "ja-JP")

    def test_worker_transcribes_using_normalized_language_and_legacy_default(self):
        import core._whisper_worker as worker

        encoded_audio = base64.b64encode(b"test-audio-payload").decode("ascii")

        for worker_args, expected_language in (
            (["small", "cpu", "int8", "en-US"], "en"),
            (["small", "cpu", "int8", "ja-JP"], "ja"),
            (["small", "cpu", "int8"], "ko"),
            (["small", "cpu", "int8", "fr-FR"], "ko"),
        ):
            transcribe_calls = []
            fake_model = SimpleNamespace(
                transcribe=lambda audio, **kwargs: (
                    transcribe_calls.append(kwargs) or [SimpleNamespace(text="ok")],
                    None,
                )
            )
            fake_module = SimpleNamespace(WhisperModel=lambda *args, **kwargs: fake_model)
            stdout = io.StringIO()

            with patch.dict(sys.modules, {"faster_whisper": fake_module}):
                with patch("core._whisper_worker._wav_bytes_to_numpy", return_value=object()):
                    with patch("core._whisper_worker.sys.stdin", io.StringIO(f"{encoded_audio}\nQUIT\n")):
                        with patch("core._whisper_worker.sys.stdout", stdout):
                            result = worker.main(worker_args)

            self.assertEqual(result, 0)
            self.assertEqual(transcribe_calls[0]["language"], expected_language)
            self.assertEqual(stdout.getvalue().splitlines(), ["READY", "ok"])

    def test_model_free_worker_self_test_checks_language_and_writes_result_file(self):
        import core._whisper_worker as worker

        with tempfile.TemporaryDirectory(prefix="ari stt self test ") as temp_dir:
            result_path = Path(temp_dir) / "worker-self-test.json"
            result = worker.run_worker_self_test(
                language="ja-JP",
                result_path=str(result_path),
                timeout_seconds=5,
            )

            self.assertEqual(result, 0)
            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertEqual(payload, {"ok": True, "scope": "worker_ipc_only", "language": "ja"})

    def test_worker_self_test_fails_without_standard_streams(self):
        import core._whisper_worker as worker

        with patch("core._whisper_worker.sys.stdin", None), patch(
            "core._whisper_worker.sys.stdout", None
        ):
            self.assertEqual(worker._run_worker_self_test("ko"), 2)

    def test_model_free_worker_self_test_rejects_unexpected_ipc_protocol(self):
        import core._whisper_worker as worker

        fake_proc = SimpleNamespace(communicate=lambda *args, **kwargs: ("READY\n", ""), returncode=0)
        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "worker-self-test.json"
            with patch("core._whisper_worker.subprocess.Popen", return_value=fake_proc):
                result = worker.run_worker_self_test(result_path=str(result_path))
            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertEqual(result, 1)
        self.assertEqual(payload["error"], "worker_protocol_failed")

    def test_model_free_worker_self_test_kills_child_after_timeout(self):
        import core._whisper_worker as worker

        fake_proc = SimpleNamespace(
            communicate=lambda *args, **kwargs: (_ for _ in ()).throw(
                subprocess.TimeoutExpired("worker", 0.01)
            ),
            kill=lambda: setattr(fake_proc, "killed", True),
            killed=False,
        )

        def communicate_after_kill(*args, **kwargs):
            return "", ""

        fake_proc.communicate = lambda *args, **kwargs: (
            (_ for _ in ()).throw(subprocess.TimeoutExpired("worker", 0.01))
            if not fake_proc.killed
            else communicate_after_kill(*args, **kwargs)
        )

        with patch("core._whisper_worker.subprocess.Popen", return_value=fake_proc):
            result = worker.run_worker_self_test(timeout_seconds=0.01)

        self.assertEqual(result, 1)
        self.assertTrue(fake_proc.killed)

    def test_model_free_worker_self_test_reports_cleanup_failure(self):
        import core._whisper_worker as worker

        def fail_kill():
            raise OSError("private diagnostic")

        def timeout_communicate(*args, **kwargs):
            raise subprocess.TimeoutExpired("worker", 0.01)

        fake_proc = SimpleNamespace(kill=fail_kill, communicate=timeout_communicate)

        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "worker-self-test.json"
            with patch("core._whisper_worker.subprocess.Popen", return_value=fake_proc):
                result = worker.run_worker_self_test(result_path=str(result_path), timeout_seconds=0.01)
            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertEqual(result, 1)
        self.assertEqual(payload["ok"], False)
        self.assertEqual(payload["error"], "worker_cleanup_failed")

    def test_nuitka_worker_self_test_uses_worker_mode_and_language_argument(self):
        import core._whisper_worker as worker

        fake_proc = SimpleNamespace(
            communicate=lambda *args, **kwargs: ("READY\nSELFTEST_OK:en\n", ""),
            returncode=0,
        )

        with patch.dict(worker.__dict__, {"__compiled__": object()}):
            with patch("core._whisper_worker.subprocess.Popen", return_value=fake_proc) as popen:
                result = worker.run_worker_self_test(language="en-US")

        self.assertEqual(result, 0)
        self.assertEqual(
            popen.call_args.args[0],
            [sys.executable, "--ari-whisper-worker", "--self-test", "en"],
        )

    def test_main_worker_self_test_uses_early_dispatch_and_result_file(self):
        main_path = Path(__file__).parents[1] / "Main.py"

        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "worker-self-test.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(main_path),
                    "--ari-whisper-worker-self-test",
                    "ja-JP",
                    str(result_path),
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                json.loads(result_path.read_text(encoding="utf-8")),
                {"ok": True, "scope": "worker_ipc_only", "language": "ja"},
            )

    def test_main_worker_entrypoint_rejects_missing_model_args_without_gui(self):
        main_path = Path(__file__).parents[1] / "Main.py"
        completed = subprocess.run(
            [sys.executable, str(main_path), "--ari-whisper-worker"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("Usage: _whisper_worker.py", completed.stderr)

    def test_main_routes_worker_self_test_before_gui_imports(self):
        main_path = Path(__file__).parents[1] / "Main.py"
        main_source = main_path.read_text(encoding="utf-8")

        self.assertLess(
            main_source.index("dispatch_worker_command(sys.argv)"),
            main_source.index("from PySide6.QtWidgets"),
        )
        worker_source = (main_path.parent / "core" / "_whisper_worker.py").read_text(encoding="utf-8")
        self.assertIn("--ari-whisper-worker-self-test", worker_source)


if __name__ == "__main__":
    unittest.main()

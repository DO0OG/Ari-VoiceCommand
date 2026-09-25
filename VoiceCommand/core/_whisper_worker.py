"""
Whisper STT 워커 프로세스.
메인 프로세스와 stdin/stdout IPC로 통신:
  - 초기화 완료 시 stdout에 "READY\\n" 출력
  - 입력: base64 인코딩된 WAV 바이트 한 줄
  - 출력: 전사 텍스트 한 줄, 결과 없으면 "__NONE__"
  - "QUIT" 수신 시 종료
"""
import base64
import io
import json
import logging
import os
import subprocess
import sys
import wave

# 메인 프로세스와 동일한 KMP 설정 상속 (혹은 기본 적용)
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")


WORKER_ARGUMENT = "--ari-whisper-worker"
WORKER_SELF_TEST_ARGUMENT = "--ari-whisper-worker-self-test"


def normalize_language(language: str = "ko") -> str:
    """Normalize supported speech locale tags for faster-whisper."""
    value = str(language or "ko").strip().lower().replace("_", "-").split("-", 1)[0]
    return value if value in {"ko", "en", "ja"} else "ko"


def _is_bundled_executable() -> bool:
    """Return whether this module runs inside a frozen/Nuitka executable."""
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def _worker_process_command(worker_args: list[str]) -> list[str]:
    if _is_bundled_executable():
        return [sys.executable, WORKER_ARGUMENT, *worker_args]
    return [sys.executable, os.path.abspath(__file__), *worker_args]


def dispatch_worker_command(argv: list[str]) -> int | None:
    """Handle worker-only CLI modes before Main.py imports its GUI/runtime."""
    if len(argv) < 2:
        return None
    if argv[1] == WORKER_ARGUMENT:
        return main(argv[2:])
    if argv[1] == WORKER_SELF_TEST_ARGUMENT:
        language = argv[2] if len(argv) > 2 else "ko"
        result_path = argv[3] if len(argv) > 3 else None
        return run_worker_self_test(language=language, result_path=result_path)
    return None


def _stop_worker_process(process) -> bool:
    """Best-effort kill and bounded reap for a failed IPC self-test child."""
    try:
        process.kill()
    except (OSError, ValueError) as exc:
        # The child can exit between the timeout and this termination attempt.
        logging.debug("Whisper worker self-test child kill failed: %s", type(exc).__name__)

    try:
        process.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except (OSError, ValueError) as exc:
            # The second bounded reap below still determines whether it stopped.
            logging.debug("Whisper worker self-test retry kill failed: %s", type(exc).__name__)
        try:
            process.communicate(timeout=3)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False
    except (OSError, ValueError):
        return False
    return True


def run_worker_self_test(
    language: str = "ko",
    result_path: str | None = None,
    timeout_seconds: float = 10.0,
) -> int:
    """Verify self-executable worker IPC without loading a model or audio device."""
    language = normalize_language(language)
    result = {"ok": False, "scope": "worker_ipc_only", "language": language}
    process = None

    try:
        process = subprocess.Popen(
            _worker_process_command(["--self-test", language]),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        stdout, _stderr = process.communicate("SELFTEST\nQUIT\n", timeout=timeout_seconds)
        result["ok"] = process.returncode == 0 and stdout.splitlines() == [
            "READY",
            f"SELFTEST_OK:{language}",
        ]
        if not result["ok"]:
            result["error"] = "worker_protocol_failed"
    except subprocess.TimeoutExpired:
        result["error"] = "worker_timeout"
        if process is not None and not _stop_worker_process(process):
            result["error"] = "worker_cleanup_failed"
    except (OSError, ValueError):
        result["error"] = "worker_ipc_failed"
        if process is not None:
            if not _stop_worker_process(process):
                result["error"] = "worker_cleanup_failed"

    if result_path:
        try:
            with open(result_path, "w", encoding="utf-8") as result_file:
                json.dump(result, result_file, ensure_ascii=False)
                result_file.write("\n")
        except OSError:
            return 1
    return 0 if result["ok"] else 1


def _run_worker_self_test(language: str) -> int:
    """Serve the private no-model protocol used only by run_worker_self_test."""
    if sys.stdin is None or sys.stdout is None:
        return 2
    sys.stdout.write("READY\n")
    sys.stdout.flush()
    for raw in sys.stdin:
        command = raw.strip()
        if command == "QUIT":
            break
        if command == "SELFTEST":
            sys.stdout.write(f"SELFTEST_OK:{normalize_language(language)}\n")
            sys.stdout.flush()
    return 0


def _wav_bytes_to_numpy(wav_bytes: bytes):
    import numpy as np

    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
        sample_width = wf.getsampwidth()
        channels = wf.getnchannels()
        sample_rate = wf.getframerate()

    if sample_width == 1:
        audio = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        return None

    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if sample_rate != 16000 and audio.size:
        from math import gcd
        from scipy.signal import resample_poly

        divisor = gcd(sample_rate, 16000)
        audio = resample_poly(audio, 16000 // divisor, sample_rate // divisor).astype(np.float32)
    return audio


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--self-test":
        return _run_worker_self_test(args[1] if len(args) > 1 else "ko")
    if len(args) < 3:
        if sys.stderr is not None:
            sys.stderr.write(
                "Usage: _whisper_worker.py <model_size> <device> <compute_type> [language]\n"
            )
        return 2

    model_size, device, compute_type = args[:3]
    language = normalize_language(args[3] if len(args) > 3 else "ko")

    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as exc:
        if sys.stderr is not None:
            sys.stderr.write(f"MODEL_LOAD_ERROR: {exc}\n")
            sys.stderr.flush()
        return 1

    sys.stdout.write("READY\n")
    sys.stdout.flush()

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        if line == "QUIT":
            break
        try:
            wav_bytes = base64.b64decode(line)
            audio_np = _wav_bytes_to_numpy(wav_bytes)
            if audio_np is None:
                sys.stdout.write("__NONE__\n")
                sys.stdout.flush()
                continue
            segments, _ = model.transcribe(
                audio_np,
                language=language,
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            sys.stdout.write((text if text else "__NONE__") + "\n")
            sys.stdout.flush()
        except Exception:
            sys.stdout.write("__NONE__\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())

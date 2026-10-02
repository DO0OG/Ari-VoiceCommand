"""
CosyVoice3 Local TTS — 서브프로세스 격리 + 이진 스트리밍
- cosyvoice_worker.py를 별도 프로세스로 실행 (DLL 충돌 방지)
- stdout 이진 스트림으로 첫 청크 즉시 재생 (저레이턴시)
- Fish Audio와 동일한 인터페이스: speak() / playback_finished / cleanup()
"""
import sys
import os
import shutil
import struct
import logging
import threading
import time
import subprocess
from collections import deque
from typing import Optional

import numpy as np
import pyaudio
from PySide6.QtCore import QObject, Signal
from audio.audio_manager import GlobalAudio
from core.emotions import DEFAULT_EMOTION
from core.resource_manager import is_bundled
from tts.cosyvoice_utils import _PCMChunkBuffer, _normalize_text_cached, apply_emotion_prosody, inject_breath_cues

_HERE = os.path.dirname(os.path.abspath(__file__))


def _find_tts_venv_python() -> str:
    """TTS 전용 venv 인터프리터 경로(없으면 빈 문자열).

    CosyVoice 의존성(hyperpyyaml, CUDA torch, librosa 등)은 .venv-tts에만
    있다. 메인 .venv에는 이 의존성이 없어 워커를 거기서 띄우면 즉시 실패한다.
    """
    from core.resource_manager import ResourceManager

    app_root = os.path.dirname(_HERE)
    writable_venv = ResourceManager.get_writable_path(".venv-tts")
    for venv_dir in (writable_venv, os.path.join(app_root, ".venv-tts")):
        candidates = (
            os.path.join(venv_dir, "Scripts", "python.exe"),
            os.path.join(venv_dir, "bin", "python"),
        )
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
    return ""


def _get_python_exe() -> str:
    """실제 Python 인터프리터 경로 반환.
    배포판에서는 sys.executable이 Ari.exe(PyInstaller)이거나 없는 python.exe(Nuitka)이므로
    PATH에서 python을 찾아야 한다."""
    tts_python = _find_tts_venv_python()
    if tts_python:
        return tts_python
    if is_bundled():
        python = shutil.which('python') or shutil.which('python3')
        if not python:
            raise RuntimeError(
                "Python 인터프리터를 찾을 수 없습니다.\n"
                "Python을 설치하고 PATH에 추가한 후 다시 시도하세요."
            )
        return python
    return sys.executable

def _get_cosyvoice_dir() -> str:
    """CosyVoice 설치 경로: 설정값 → 자동 탐색 순으로 결정."""
    try:
        from core.config_manager import ConfigManager
        configured = ConfigManager.load_settings().get("cosyvoice_dir", "")
        if configured and os.path.isdir(configured):
            return configured
    except Exception as exc:
        logging.debug("cosyvoice_dir 설정 조회 실패, 자동 탐색으로 폴백: %s", exc)
        pass
    # 자동 탐색: 프로젝트 루트 인근 경로 후보
    candidates = [
        os.path.join(os.path.dirname(_HERE), "..", "CosyVoice"),
        os.path.join(os.path.dirname(_HERE), "..", "..", "CosyVoice"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return os.path.abspath(c)
    return ""

# 첫 사용 시 1회만 확인 — 경로 문자열 자체를 캐시
_cached_cosyvoice_dir: Optional[str] = None

def _get_cosyvoice_dir_cached() -> str:
    """_get_cosyvoice_dir()의 결과를 캐시해서 반복 fs 탐색 방지."""
    global _cached_cosyvoice_dir
    if _cached_cosyvoice_dir is None:
        _cached_cosyvoice_dir = _get_cosyvoice_dir()
    return _cached_cosyvoice_dir

def _reset_cosyvoice_dir_cache() -> None:
    global _cached_cosyvoice_dir
    _cached_cosyvoice_dir = None

def _get_reference_wav() -> str:
    """reference.wav 경로: appdata 우선, 없으면 번들"""
    from tts.voice_reference import get_reference_wav

    return get_reference_wav()

def _get_worker_script() -> str:
    """cosyvoice_worker.py 경로: 배포판이면 번들 폴더(PyInstaller는 _MEIPASS, Nuitka는 실행 파일 옆), 아니면 _HERE"""
    if is_bundled():
        from core.resource_manager import ResourceManager
        return ResourceManager.get_bundle_path("cosyvoice_worker.py")
    return os.path.join(_HERE, "cosyvoice_worker.py")


def _load_tts_volume() -> float:
    """설정된 재생 볼륨 배율(0.0~2.0). 읽기 실패하면 원본 그대로."""
    try:
        from core.config_manager import ConfigManager
        value = float(ConfigManager.get("tts_volume", 1.0))
    except (ImportError, TypeError, ValueError) as exc:
        logging.debug("tts_volume 조회 실패, 1.0 사용: %s", exc)
        return 1.0
    return min(max(value, 0.0), 2.0)


class CosyVoiceTTS(QObject):
    playback_finished = Signal()
    _MAX_PCM_BUFFER_BYTES = 24000 * 4 * 12
    _AUDIO_FRAMES_PER_BUFFER = 512
    _DRAIN_TIMEOUT = 30
    # __init__을 우회해 생성되는 경우(테스트 등)에도 값이 있어야 한다.
    volume = 1.0

    def __init__(self, model_dir=None, reference_wav=None, reference_text="", speed=0.9, cosyvoice_dir=None):
        super().__init__()
        cosyvoice_dir = cosyvoice_dir or _get_cosyvoice_dir_cached()
        default_model_dir = os.path.join(cosyvoice_dir, "pretrained_models", "Fun-CosyVoice3-0.5B") if cosyvoice_dir else ""
        self.model_dir = model_dir or default_model_dir
        self._cosyvoice_dir = cosyvoice_dir
        self.reference_wav = reference_wav or _get_reference_wav()
        self.reference_text = reference_text
        self.speed = speed
        self.volume = _load_tts_volume()

        self.sample_rate = 24000  # 워커에서 갱신됨
        self.is_playing = False
        self._proc = None
        self._ready = threading.Event()
        self._warmup_ready = threading.Event()
        self._warmup_done = threading.Event()
        self._worker_error = None
        self._warmup_error = None
        self._ctrl_q = deque()
        self._ctrl_lock = threading.Lock()
        self._speak_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._active_stop_event = None
        self._request_id = 0
        self._active_request_id = None
        self._restart_required = False
        self._drain_event = threading.Event()
        self._drain_event.set()
        self._drain_proc = None
        self._drain_request_id = None
        self._drain_cancelled_at = None
        self._stopping = False  # 종료 플래그 추가
        self._stream = None
        self._stream_rate = None
        self._stream_lock = threading.Lock()
        self._pcm_buffer = _PCMChunkBuffer()
        self._pcm_lock = threading.Lock()
        self._pcm_done = threading.Event()

        self._start_worker()

    # ── 서브프로세스 ────────────────────────────────────────────────────────────

    def _start_worker(self):
        with self._state_lock:
            self._proc = None
        self._ready.clear()
        self._warmup_ready.clear()
        self._warmup_done.clear()
        self._worker_error = None
        self._warmup_error = None
        with self._ctrl_lock:
            self._ctrl_q.clear()
        cmd = [
            _get_python_exe(), _get_worker_script(),
            "--model-dir", self.model_dir,
            "--reference-wav", self.reference_wav,
            "--reference-text", self.reference_text,
            "--cosyvoice-dir", self._cosyvoice_dir,
            "--speed", str(self.speed),
        ]
        # 부모는 stdin/stderr를 UTF-8로 주고받는데 한글 Windows의 자식
        # Python은 기본이 cp949라, 지정하지 않으면 한글이 깨져 워커가
        # 엉뚱한 텍스트를 합성한다. Inductor/Triton 캐시도 한글 경로를
        # 못 읽으므로 ASCII 경로로 보낸다.
        worker_env = dict(os.environ)
        worker_env["PYTHONUTF8"] = "1"
        worker_env["PYTHONIOENCODING"] = "utf-8"
        worker_env.setdefault("TORCHINDUCTOR_CACHE_DIR", r"C:\torch_cache\inductor")
        worker_env.setdefault("TRITON_CACHE_DIR", r"C:\torch_cache\triton")

        popen_kwargs = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "bufsize": 0,
            "env": worker_env,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            cmd,
            **popen_kwargs,
        )
        with self._state_lock:
            self._proc = proc
            self._restart_required = False
        self._stderr_thread = threading.Thread(
            target=self._stderr_reader, args=(proc,), daemon=True
        )
        self._stderr_thread.start()

        logging.info("CosyVoice3 워커 시작 중 (모델 로드 중, 약 30~60초)...")

    def _stderr_reader(self, proc):
        """워커 stderr(제어 채널)을 읽어 이벤트 설정"""
        try:
            while not self._stopping and self._proc is proc and proc.poll() is None:
                line_raw = proc.stderr.readline()
                if not line_raw:
                    break
                line = line_raw.decode("utf-8", errors="replace").strip()
                if self._proc is not proc:
                    break
                if not line:
                    continue
                if line.startswith("SAMPLERATE:"):
                    self.sample_rate = int(line.split(":")[1])
                elif line == "READY":
                    self._ready.set()
                elif line.startswith("INFO:"):
                    logging.info("[worker] %s", line[5:])
                    if "백그라운드 GPU warmup 완료" in line:
                        self._warmup_ready.set()
                        self._warmup_done.set()
                    elif "백그라운드 warmup 실패" in line:
                        self._warmup_error = line[5:]
                        self._warmup_done.set()
                elif line.startswith("DONE:") or line.startswith("ERROR:"):
                    with self._ctrl_lock:
                        if self._proc is proc:
                            self._ctrl_q.append((proc, line))
                else:
                    logging.debug("[worker] %s", line)
        except Exception as e:
            if not self._stopping and self._proc is proc:
                logging.error("stderr 읽기 오류: %s", e)
                self._worker_error = str(e)
        finally:
            if not self._stopping and self._proc is proc:
                exit_code = proc.poll()
                if not self._ready.is_set():
                    self._worker_error = self._worker_error or (
                        f"CosyVoice3 worker exited before READY (code={exit_code})"
                    )
                    self._ready.set()
                if not self._warmup_done.is_set():
                    self._warmup_error = self._warmup_error or (
                        f"CosyVoice3 worker exited before warmup completed (code={exit_code})"
                    )
                    self._warmup_done.set()

    def wait_until_ready(self, timeout=300, stop_event=None):
        """워커 READY 대기"""
        deadline = time.monotonic() + timeout
        while not self._ready.wait(
            timeout=min(0.05, max(0.0, deadline - time.monotonic()))
        ):
            if (
                (stop_event is not None and stop_event.is_set())
                or time.monotonic() >= deadline
            ):
                return False
        return (
            self._worker_error is None
            and self._proc is not None
            and self._proc.poll() is None
        )

    def wait_until_warmup_done(self, timeout=300):
        """웜업 완료 대기"""
        logging.info("CosyVoice3 웜업 완료 대기 중...")
        if not self._warmup_done.wait(timeout=timeout):
            return False
        return (
            self._warmup_ready.is_set()
            and self._warmup_error is None
            and self._proc is not None
            and self._proc.poll() is None
        )

    def _wait_ctrl(self, timeout=120, proc=None, stop_event=None) -> str:
        """DONE/ERROR 제어 메시지 대기 (타임아웃 연장)"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._stopping:
            if stop_event is not None and stop_event.is_set():
                return "ERROR:cancelled"
            with self._ctrl_lock:
                if self._ctrl_q:
                    while self._ctrl_q:
                        queued_proc, line = self._ctrl_q.popleft()
                        if queued_proc is proc:
                            return line
            if proc is not None and proc.poll() is not None:
                return "ERROR:worker-exited"
            time.sleep(0.05)
        return "ERROR:timeout"

    def _clear_pcm_state(self):
        with self._pcm_lock:
            self._pcm_buffer.clear()
        self._pcm_done.clear()

    def _audio_callback(self, in_data, frame_count, time_info, status):
        needed = frame_count * 4  # float32 mono
        stop_event = self._active_stop_event
        with self._pcm_lock:
            if stop_event is not None and stop_event.is_set():
                self._pcm_buffer.clear()
                chunk = b""
            else:
                chunk = self._pcm_buffer.pop_bytes(needed)
            empty_and_done = self._pcm_done.is_set() and self._pcm_buffer.size == 0

        if len(chunk) < needed:
            chunk += b"\x00" * (needed - len(chunk))

        flag = pyaudio.paComplete if empty_and_done else pyaudio.paContinue
        return (chunk, flag)

    def _request_is_active(self, request_id, proc, stop_event) -> bool:
        with self._state_lock:
            return (
                self._active_request_id == request_id
                and self._proc is proc
                and not stop_event.is_set()
                and not self._stopping
            )

    def _cancel_request(self, request_id, proc, stop_event) -> None:
        with self._state_lock:
            if self._active_request_id != request_id or self._proc is not proc:
                return
            stop_event.set()
            self._active_request_id = None
            if self._active_stop_event is stop_event:
                self._active_stop_event = None
        self._clear_pcm_state()
        self._pcm_done.set()

    def _abort_request(self, request_id, proc) -> None:
        with self._state_lock:
            if self._active_request_id != request_id or self._proc is not proc:
                return
            self._active_request_id = None
            self._active_stop_event = None
            self._restart_required = True
        self._clear_pcm_state()
        self._pcm_done.set()
        try:
            if proc.poll() is None:
                proc.kill()
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logging.debug("오류 난 CosyVoice 워커 종료 실패: %s", exc)

    def _start_drain(self, request_id, proc, reader_t, reader_state) -> None:
        """취소된 요청의 남은 출력을 백그라운드에서 버린다(워커는 유지)."""
        drain_event = threading.Event()
        cancelled_at = time.monotonic()
        with self._state_lock:
            self._drain_event = drain_event
            self._drain_proc = proc
            self._drain_request_id = request_id
            self._drain_cancelled_at = cancelled_at
        threading.Thread(
            target=self._drain_request,
            args=(proc, reader_t, reader_state, drain_event, cancelled_at),
            name=f"CosyVoice-Drain-{request_id}",
            daemon=True,
        ).start()

    def _drain_request(self, proc, reader_t, reader_state, drain_event, cancelled_at):
        """PCM 종료 표시(0)와 DONE/ERROR까지 기다린다. 어긋나면 재시작을 요구한다."""
        def remaining():
            return max(0.0, cancelled_at + self._DRAIN_TIMEOUT - time.monotonic())

        clean = False
        try:
            reader_t.join(timeout=remaining())
            if not reader_t.is_alive() and reader_state["clean"]:
                ctrl = self._wait_ctrl(timeout=remaining(), proc=proc)
                clean = ctrl not in ("ERROR:timeout", "ERROR:worker-exited")
        finally:
            if not clean and self._proc is proc:
                logging.warning("CosyVoice 요청 배출 실패, 워커를 재시작합니다")
                self._restart_required = True
            drain_event.set()

    def _watch_stop_event(self, request_id, proc, stop_event, finished):
        while not finished.wait(0.05):
            if stop_event.is_set():
                self._cancel_request(request_id, proc, stop_event)
                return

    def _ensure_worker(self, stop_event):
        if not self._wait_for_pending_drain(stop_event):
            return False
        if stop_event.is_set() or self._stopping:
            return False
        proc = self._proc
        if (
            self._restart_required
            or proc is None
            or proc.poll() is not None
        ):
            if proc is not None and proc.poll() is None:
                try:
                    proc.kill()
                    proc.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    logging.debug("이전 CosyVoice 워커 종료 대기 실패: %s", exc)
            self._start_worker()
        return self.wait_until_ready(stop_event=stop_event)

    def _wait_for_pending_drain(self, stop_event) -> bool:
        with self._state_lock:
            drain_event = self._drain_event
            proc = self._drain_proc
            cancelled_at = self._drain_cancelled_at
        if drain_event.is_set():
            return not stop_event.is_set()

        deadline = (cancelled_at or time.monotonic()) + self._DRAIN_TIMEOUT
        while not drain_event.wait(timeout=0.05):
            if stop_event.is_set() or self._stopping:
                return False
            if proc is None or proc.poll() is not None:
                self._restart_required = True
                return True
            if time.monotonic() >= deadline:
                logging.warning("CosyVoice 요청 배출 타임아웃, 워커를 재시작합니다")
                self._restart_required = True
                return True
        return not stop_event.is_set()

    def _apply_volume(self, data: bytes) -> bytes:
        """float32 PCM에 tts_volume 배율을 적용한다.

        CosyVoice는 API TTS와 달리 출력 레벨을 일정하게 맞춰주지 않아
        참조 음성 레벨을 그대로 따라간다. 제공자를 오갈 때 체감 볼륨이
        튀면 이 값으로 맞춘다. 1.0이면 변환 비용 없이 원본을 그대로 쓴다.
        """
        if self.volume == 1.0 or not data:
            return data
        samples = np.frombuffer(data, dtype=np.float32) * self.volume
        # 배율을 1.0 초과로 올린 경우 클리핑 잡음이 나지 않게 막는다.
        return np.clip(samples, -1.0, 1.0).astype(np.float32).tobytes()

    def _open_stream_on(self, device_index):
        return GlobalAudio.open_stream(
            format=pyaudio.paFloat32,
            channels=1,
            rate=self.sample_rate,
            output=True,
            output_device_index=device_index,
            frames_per_buffer=self._AUDIO_FRAMES_PER_BUFFER,
            stream_callback=self._audio_callback,
        )

    def _ensure_stream(self):
        """설정된 출력 장치로 열고, 실패하면 시스템 기본값까지 내려간다.

        장치를 지정하지 않으면 Fish TTS(설정 장치)와 서로 다른 장치로
        재생되어 체감 볼륨이 크게 달라진다. Voicemeeter처럼 가상 장치가
        기본으로 잡혀 있으면 게인 스테이징까지 달라진다.

        같은 스피커가 host API별로 중복 노출되는데 WASAPI는 24kHz를
        거부하고(-9997) WDM-KS는 독점 점유로 열리지 않으므로(-9999)
        audio_manager가 정렬해 준 후보를 순서대로 시도한다.
        """
        with self._stream_lock:
            self._close_stream_unlocked()
            from audio.audio_manager import (
                find_output_device_candidates,
                get_configured_output_device_name,
            )

            device_name = get_configured_output_device_name()
            candidates = find_output_device_candidates(device_name)
            candidates.append(None)  # 마지막 수단: 시스템 기본 장치

            errors = []
            for device_index in candidates:
                try:
                    self._stream = self._open_stream_on(device_index)
                except OSError as exc:
                    errors.append(f"idx={device_index}: {exc}")
                    continue
                if device_index is None and device_name:
                    logging.warning(
                        "[TTS] '%s' 출력 실패로 시스템 기본 장치 사용 (%s)",
                        device_name, "; ".join(errors),
                    )
                self._stream_rate = self.sample_rate
                return self._stream

            raise OSError(
                f"[TTS] {self.sample_rate}Hz 출력 스트림을 열 수 없습니다 "
                f"({'; '.join(errors)})"
            )

    def _close_stream(self):
        with self._stream_lock:
            self._close_stream_unlocked()

    def _close_stream_unlocked(self):
        if not self._stream:
            self._stream_rate = None
            return
        GlobalAudio.close_stream(self._stream)
        self._stream = None
        self._stream_rate = None

    # ── 합성 + 스트리밍 재생 ────────────────────────────────────────────────────

    def speak(
        self,
        text: str,
        emotion: str = DEFAULT_EMOTION,
        stop_event: threading.Event | None = None,
    ) -> bool:
        from audio.audio_manager import _audio_output_lock as _audio_lock

        stop_event = stop_event or threading.Event()
        text = _normalize_text_cached(text or "")
        text = apply_emotion_prosody(text, emotion)
        text = inject_breath_cues(text)
        if not text or stop_event.is_set():
            return False

        with self._speak_lock:
            if self._stopping or stop_event.is_set():
                return False
            with self._state_lock:
                self._request_id += 1
                request_id = self._request_id
                self._active_request_id = request_id
                self._active_stop_event = stop_event
            self.is_playing = True
            request_finished = threading.Event()
            watcher = None
            reader_t = None
            pa_stream = None
            proc = None
            worker_complete = False
            request_sent = False
            reader_state = {"clean": False}
            audio_lock_acquired = False
            try:
                self._clear_pcm_state()
                if not self._ensure_worker(stop_event):
                    proc = self._proc
                    if not stop_event.is_set():
                        logging.error(
                            "[TTS] CosyVoice3 워커 준비 실패: %s",
                            self._worker_error or "READY timeout",
                        )
                    return False
                proc = self._proc
                watcher = threading.Thread(
                    target=self._watch_stop_event,
                    args=(request_id, proc, stop_event, request_finished),
                    daemon=True,
                )
                watcher.start()
                if stop_event.is_set():
                    return False

                with self._ctrl_lock:
                    self._ctrl_q.clear()
                started_at = time.monotonic()
                proc.stdin.write(
                    (text.replace("\n", " ").strip() + "\n").encode("utf-8")
                )
                proc.stdin.flush()

                def pipe_reader():
                    first = True
                    try:
                        # 취소돼도 종료 표시(0)까지 읽어 파이프를 비운다(재생은 안 함).
                        while True:
                            hdr = self._read_exact(4, proc)
                            if not hdr:
                                break
                            size = struct.unpack("<I", hdr)[0]
                            if size == 0:
                                reader_state["clean"] = True
                                break
                            data = self._read_exact(size, proc)
                            if not data:
                                break
                            if not self._request_is_active(
                                request_id, proc, stop_event
                            ):
                                continue
                            if first:
                                logging.info(
                                    "[TTS] 첫 청크 수신 → 재생 시작: %.2fs",
                                    time.monotonic() - started_at,
                                )
                                first = False
                            data = self._apply_volume(data)
                            max_buffer_bytes = max(self._MAX_PCM_BUFFER_BYTES, len(data))
                            while self._request_is_active(
                                request_id, proc, stop_event
                            ):
                                with self._pcm_lock:
                                    if (
                                        self._active_request_id == request_id
                                        and self._pcm_buffer.size + len(data)
                                        <= max_buffer_bytes
                                    ):
                                        self._pcm_buffer.append(data)
                                        break
                                time.sleep(0.01)
                    except Exception as e:
                        if self._request_is_active(request_id, proc, stop_event):
                            logging.debug("pipe_reader 오류: %s", e)
                    finally:
                        if self._request_is_active(request_id, proc, stop_event):
                            self._pcm_done.set()

                reader_t = threading.Thread(
                    target=pipe_reader, name=f"CosyVoice-PCM-{request_id}", daemon=True
                )
                reader_t.start()
                request_sent = True

                _audio_lock.acquire()
                audio_lock_acquired = True
                pa_stream = self._ensure_stream()
                if not pa_stream.is_active():
                    pa_stream.start_stream()

                reader_deadline = time.monotonic() + 300
                while (
                    reader_t.is_alive()
                    and not stop_event.is_set()
                    and time.monotonic() < reader_deadline
                ):
                    reader_t.join(timeout=0.05)
                if reader_t.is_alive() and not stop_event.is_set():
                    logging.error("CosyVoice3 PCM 읽기 타임아웃")
                    self._abort_request(request_id, proc)
                    return False
                if stop_event.is_set():
                    return False
                self._pcm_done.set()
                deadline = time.monotonic() + 30
                if pa_stream:
                    while (
                        pa_stream.is_active()
                        and time.monotonic() < deadline
                        and not stop_event.is_set()
                    ):
                        time.sleep(0.1)

                if stop_event.is_set():
                    return False

                logging.info(
                    "[TTS] 전체 완료: %.2fs", time.monotonic() - started_at
                )
                ctrl = self._wait_ctrl(
                    timeout=60, proc=proc, stop_event=stop_event
                )
                worker_complete = ctrl != "ERROR:timeout" and ctrl != "ERROR:cancelled"
                if ctrl.startswith("ERROR:"):
                    logging.error("워커 오류: %s", ctrl[6:])
                return not ctrl.startswith("ERROR:") and not stop_event.is_set()

            except Exception as e:
                if not stop_event.is_set() and not self._stopping:
                    logging.error("CosyVoice TTS speak 오류: %s", e)
                return False
            finally:
                request_finished.set()
                if stop_event.is_set():
                    with self._state_lock:
                        cancel_proc = (
                            self._proc
                            if self._active_request_id == request_id
                            else None
                        )
                    if cancel_proc is not None:
                        self._cancel_request(request_id, cancel_proc, stop_event)
                    if request_sent and not worker_complete:
                        self._start_drain(request_id, proc, reader_t, reader_state)
                elif proc is not None and not worker_complete:
                    self._abort_request(request_id, proc)
                if watcher is not None:
                    watcher.join(timeout=0.1)
                if pa_stream is not None:
                    try:
                        self._close_stream()
                    except (OSError, RuntimeError, TypeError, ValueError) as exc:
                        logging.debug("CosyVoice 오디오 스트림 정리 실패: %s", exc)
                if audio_lock_acquired:
                    _audio_lock.release()
                    audio_lock_acquired = False
                with self._state_lock:
                    if self._active_request_id == request_id:
                        self._active_request_id = None
                    if self._active_stop_event is stop_event:
                        self._active_stop_event = None
                    self.is_playing = False
                self.playback_finished.emit()

    def _read_exact(self, n: int, proc=None, stop_event=None):
        """stdout에서 정확히 n바이트 읽기"""
        proc = proc or self._proc
        buf = b""
        try:
            while (
                len(buf) < n
                and not self._stopping
                and (stop_event is None or not stop_event.is_set())
            ):
                chunk = proc.stdout.read(n - len(buf))
                if not chunk:
                    return None
                buf += chunk
        except Exception as exc:
            if stop_event is None or not stop_event.is_set():
                logging.debug("_read_exact 실패: %s", exc)
            return None
        return buf if len(buf) == n else None

    # ── 정리 ───────────────────────────────────────────────────────────────────

    def stop(self):
        with self._state_lock:
            stop_event = self._active_stop_event
            if stop_event is None:
                return
            stop_event.set()
            self._active_stop_event = None
            self._active_request_id = None
        # 워커는 죽이지 않는다. 남은 출력은 speak()의 배출 스레드가 버린다.
        self._clear_pcm_state()
        self._pcm_done.set()

    def cleanup(self):
        """자원 정리 (프로세스 및 PyAudio)"""
        if self._stopping:
            return
        self.stop()
        self._stopping = True
        self._ready.set() # 대기 중인 스레드 해제
        self._warmup_done.set()

        logging.info("CosyVoice3 리소스 정리 중...")
        if self._proc and self._proc.poll() is None:
            try:
                # 1. EXIT 명령 시도
                self._proc.stdin.write(b"EXIT\n")
                self._proc.stdin.flush()
                # 2. 잠시 대기
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    self._proc.terminate()
                    self._proc.wait(timeout=2)
                except Exception as exc:
                    logging.debug("CosyVoice terminate 실패, kill 시도: %s", exc)
                    try:
                        self._proc.kill()
                    except Exception as kill_exc:
                        logging.debug("CosyVoice kill 실패: %s", kill_exc)
                        pass
            except Exception as exc:
                logging.debug("CosyVoice 종료 명령 실패, kill 시도: %s", exc)
                try:
                    self._proc.kill()
                except Exception as kill_exc:
                    logging.debug("CosyVoice kill 실패: %s", kill_exc)
                    pass
        self._close_stream()
        self._clear_pcm_state()

        # PyAudio 정리는 AriCore.cleanup()에서 GlobalAudio.terminate() 호출로 통합 관리
    def __del__(self):
        try:
            self.cleanup()
        except Exception as exc:
            logging.debug("CosyVoice 소멸자 cleanup 실패: %s", exc)
            pass

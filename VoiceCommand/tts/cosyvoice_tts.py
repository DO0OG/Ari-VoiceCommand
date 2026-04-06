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
from tts.cosyvoice_utils import (
    _PCMChunkBuffer,
    _normalize_text_cached,
    apply_emotion_prosody,
    inject_breath_cues,
    split_tts_segments,
)

_HERE = os.path.dirname(os.path.abspath(__file__))


def _get_python_exe() -> str:
    """실제 Python 인터프리터 경로 반환.
    frozen(EXE) 환경에서는 sys.executable이 Ari.exe 이므로
    PATH에서 python을 찾아야 한다."""
    if getattr(sys, 'frozen', False):
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
    except Exception:
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

def _get_reference_wav() -> str:
    """reference.wav 경로: appdata 우선, 없으면 번들"""
    from core.resource_manager import ResourceManager
    appdata_path = ResourceManager.get_writable_path("reference.wav")
    if os.path.exists(appdata_path):
        return appdata_path
    return ResourceManager.get_bundle_path("reference.wav")

def _get_worker_script() -> str:
    """cosyvoice_worker.py 경로: frozen이면 _MEIPASS, 아니면 _HERE"""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, "cosyvoice_worker.py")
    return os.path.join(_HERE, "cosyvoice_worker.py")


class CosyVoiceTTS(QObject):
    playback_finished = Signal()
    _MAX_PCM_BUFFER_BYTES = 24000 * 4 * 12
    _AUDIO_FRAMES_PER_BUFFER = 512

    def __init__(self, model_dir=None, reference_wav=None, reference_text="", speed=0.9):
        super().__init__()
        from audio.audio_manager import GlobalAudio
        cosyvoice_dir = _get_cosyvoice_dir_cached()
        default_model_dir = os.path.join(cosyvoice_dir, "pretrained_models", "Fun-CosyVoice3-0.5B") if cosyvoice_dir else ""
        self.model_dir = model_dir or default_model_dir
        self._cosyvoice_dir = cosyvoice_dir
        self.reference_wav = reference_wav or _get_reference_wav()
        self.reference_text = reference_text
        self.speed = speed

        self.pa = GlobalAudio.get_instance()
        self.sample_rate = 24000  # 워커에서 갱신됨
        self.is_playing = False
        self._proc = None
        self._ready = threading.Event()
        self._warmup_ready = threading.Event()  # 추가: 웜업 완료 이벤트
        self._ctrl_q = deque()
        self._ctrl_lock = threading.Lock()
        self._speak_lock = threading.Lock()
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
        cmd = [
            _get_python_exe(), _get_worker_script(),
            "--model-dir", self.model_dir,
            "--reference-wav", self.reference_wav,
            "--reference-text", self.reference_text,
            "--cosyvoice-dir", self._cosyvoice_dir,
            "--speed", str(self.speed),
        ]
        popen_kwargs = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "bufsize": 0,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(
            cmd,
            **popen_kwargs,
        )
        self._stderr_thread = threading.Thread(target=self._stderr_reader, daemon=True)
        self._stderr_thread.start()

        logging.info("CosyVoice3 워커 시작 중 (모델 로드 중, 약 30~60초)...")

    def _stderr_reader(self):
        """워커 stderr(제어 채널)을 읽어 이벤트 설정"""
        try:
            while not self._stopping and self._proc and self._proc.poll() is None:
                line_raw = self._proc.stderr.readline()
                if not line_raw:
                    break
                line = line_raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if line.startswith("SAMPLERATE:"):
                    self.sample_rate = int(line.split(":")[1])
                elif line == "READY":
                    self._ready.set()
                elif line.startswith("INFO:"):
                    logging.info(f"[worker] {line[5:]}")
                    if "백그라운드 GPU warmup 완료" in line:
                        self._warmup_ready.set()
                elif line.startswith("DONE:") or line.startswith("ERROR:"):
                    with self._ctrl_lock:
                        self._ctrl_q.append(line)
                else:
                    logging.debug(f"[worker] {line}")
        except Exception as e:
            if not self._stopping:
                logging.error(f"stderr 읽기 오류: {e}")

    def wait_until_ready(self, timeout=300):
        """워커 READY 대기"""
        return self._ready.wait(timeout=timeout)

    def wait_until_warmup_done(self, timeout=300):
        """웜업 완료 대기 후 PyAudio 하드웨어를 선점한다.

        첫 pa.open() 호출 시 드라이버 초기화 오버헤드가 발생해
        실제 TTS 재생 첫 문장 음질이 저하되는 문제를 방지한다.
        """
        logging.info("CosyVoice3 웜업 완료 대기 중...")
        result = self._warmup_ready.wait(timeout=timeout)
        self._prewarm_audio()
        return result

    def _prewarm_audio(self) -> None:
        """짧은 무음 스트림으로 PyAudio 하드웨어를 미리 초기화한다."""
        try:
            stream = self.pa.open(
                format=pyaudio.paFloat32,
                channels=1,
                rate=self.sample_rate,
                output=True,
                frames_per_buffer=self._AUDIO_FRAMES_PER_BUFFER,
            )
            # 100ms 무음 (하드웨어 버퍼 초기화 목적)
            silence = b"\x00" * (self._AUDIO_FRAMES_PER_BUFFER * 4 * 5)
            stream.write(silence)
            stream.stop_stream()
            stream.close()
            logging.debug("[TTS] PyAudio 하드웨어 선점 완료")
        except Exception as e:
            logging.debug(f"[TTS] PyAudio 선점 실패 (무시): {e}")

    def _wait_ctrl(self, timeout=120) -> str:
        """DONE/ERROR 제어 메시지 대기 (타임아웃 연장)"""
        import time
        deadline = time.time() + timeout
        while time.time() < deadline and not self._stopping:
            with self._ctrl_lock:
                if self._ctrl_q:
                    return self._ctrl_q.popleft()
            time.sleep(0.05)
        return "ERROR:timeout"

    def _clear_pcm_state(self):
        with self._pcm_lock:
            self._pcm_buffer.clear()
        self._pcm_done.clear()

    def _audio_callback(self, in_data, frame_count, time_info, status):
        needed = frame_count * 4  # float32 mono
        with self._pcm_lock:
            chunk = self._pcm_buffer.pop_bytes(needed)
            empty_and_done = self._pcm_done.is_set() and self._pcm_buffer.size == 0

        if len(chunk) < needed:
            chunk += b"\x00" * (needed - len(chunk))

        flag = pyaudio.paComplete if empty_and_done else pyaudio.paContinue
        return (chunk, flag)

    def _ensure_stream(self):
        with self._stream_lock:
            self._close_stream_unlocked()
            self._stream = self.pa.open(
                format=pyaudio.paFloat32,
                channels=1,
                rate=self.sample_rate,
                output=True,
                frames_per_buffer=self._AUDIO_FRAMES_PER_BUFFER,
                stream_callback=self._audio_callback,
            )
            self._stream_rate = self.sample_rate
            return self._stream

    def _close_stream(self):
        with self._stream_lock:
            self._close_stream_unlocked()

    def _close_stream_unlocked(self):
        if not self._stream:
            self._stream_rate = None
            return
        try:
            if self._stream.is_active():
                self._stream.stop_stream()
        except Exception:  # nosec B110
            pass
        try:
            self._stream.close()
        except Exception:  # nosec B110
            pass
        self._stream = None
        self._stream_rate = None

    # ── 합성 + 스트리밍 재생 ────────────────────────────────────────────────────

    def _speak_segment(self, text: str) -> bool:
        if not text:
            return False

        t0 = time.time()

        self._proc.stdin.write((text.replace("\n", " ").strip() + "\n").encode("utf-8"))
        self._proc.stdin.flush()

        self._clear_pcm_state()

        # 첫 청크가 버퍼에 채워진 뒤 스트림을 시작하기 위한 이벤트
        _first_chunk_ready = threading.Event()

        def pipe_reader():
            first = True
            try:
                while not self._stopping:
                    hdr = self._read_exact(4)
                    if not hdr:
                        break
                    size = struct.unpack("<I", hdr)[0]
                    if size == 0:
                        break
                    data = self._read_exact(size)
                    if not data:
                        break
                    if first:
                        # 첫 청크 앞 50ms에 페이드인: 모델 시작 아티팩트 마스킹
                        fade_samples = min(1200, len(data) // 4)
                        if fade_samples > 0:
                            arr = np.frombuffer(data, dtype=np.float32).copy()
                            arr[:fade_samples] *= np.linspace(
                                0.0, 1.0, fade_samples, dtype=np.float32
                            )
                            data = arr.tobytes()
                    max_buffer_bytes = max(self._MAX_PCM_BUFFER_BYTES, len(data))
                    while not self._stopping:
                        with self._pcm_lock:
                            if self._pcm_buffer.size + len(data) <= max_buffer_bytes:
                                self._pcm_buffer.append(data)
                                break
                        time.sleep(0.01)
                    if first:
                        logging.info(f"[TTS] 첫 청크 수신 → 재생 시작: {time.time()-t0:.2f}s")
                        _first_chunk_ready.set()
                        first = False
            except Exception as e:
                if not self._stopping:
                    logging.debug(f"pipe_reader 오류: {e}")
            finally:
                self._pcm_done.set()
                _first_chunk_ready.set()  # 데이터 없이 종료된 경우 블록 해제

        reader_t = threading.Thread(target=pipe_reader, daemon=True)
        reader_t.start()

        # 스트림 오픈 자체를 첫 청크 수신 후로 미룬다.
        # pa.open()이 WASAPI 등 일부 드라이버에서 콜백을 즉시 시작하므로
        # 그 이전에 버퍼를 채워야 무음→오디오 전환 아티팩트를 막을 수 있다.
        _first_chunk_ready.wait(timeout=60)
        pa_stream = self._ensure_stream()
        if not pa_stream.is_active():
            pa_stream.start_stream()

        reader_t.join(timeout=300)
        self._pcm_done.set()
        deadline = time.time() + 30
        if pa_stream:
            while pa_stream.is_active() and time.time() < deadline and not self._stopping:
                time.sleep(0.1)

        try:
            if pa_stream:
                self._close_stream()
        except Exception:  # nosec B110
            pass
        if self._stopping:
            return False

        logging.info(f"[TTS] 전체 완료: {time.time()-t0:.2f}s")

        ctrl = self._wait_ctrl(timeout=60)
        if ctrl.startswith("ERROR:"):
            logging.error(f"워커 오류: {ctrl[6:]}")
        return not ctrl.startswith("ERROR:")

    def speak(self, text: str, emotion: str = "평온") -> bool:
        from audio.audio_manager import _audio_output_lock as _audio_lock
        text = _normalize_text_cached(text or "")
        text = apply_emotion_prosody(text, emotion)
        text = inject_breath_cues(text)
        segments = split_tts_segments(text)
        if not segments or self._proc is None or self._proc.poll() is not None:
            return False

        if not self._ready.is_set():
            logging.info("[TTS] 워커 준비 대기 중...")
            if not self._ready.wait(timeout=300):
                logging.error("[TTS] 워커 준비 타임아웃 — speak() 건너뜀")
                return False

        with _audio_lock:
            with self._speak_lock:
                self.is_playing = True
                try:
                    for index, segment in enumerate(segments, start=1):
                        if len(segments) > 1:
                            logging.debug("[TTS] 세그먼트 %s/%s: %s", index, len(segments), segment[:30])
                        if not self._speak_segment(segment):
                            return False
                    return True
                except Exception as e:
                    if not self._stopping:
                        logging.error(f"CosyVoice TTS speak 오류: {e}")
                    return False
                finally:
                    self.is_playing = False
                    self.playback_finished.emit()

    def _read_exact(self, n: int):
        """stdout에서 정확히 n바이트 읽기"""
        buf = b""
        try:
            while len(buf) < n and not self._stopping:
                chunk = self._proc.stdout.read(n - len(buf))
                if not chunk:
                    return None
                buf += chunk
        except Exception:
            return None
        return buf

    # ── 정리 ───────────────────────────────────────────────────────────────────

    def cleanup(self):
        """자원 정리 (프로세스 및 PyAudio)"""
        if self._stopping:
            return
        self._stopping = True
        self._ready.set() # 대기 중인 스레드 해제

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
                except Exception:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._close_stream()
        self._clear_pcm_state()

        # PyAudio 정리는 AriCore.cleanup()에서 GlobalAudio.terminate() 호출로 통합 관리
    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass

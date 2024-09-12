"""
CosyVoice3 Local TTS — 서브프로세스 격리 + 이진 스트리밍
- cosyvoice_worker.py를 별도 프로세스로 실행 (DLL 충돌 방지)
- stdout 이진 스트림으로 첫 청크 즉시 재생 (저레이턴시)
- Fish Audio와 동일한 인터페이스: speak() / playback_finished / cleanup()
"""
import sys
import os
import re
import shutil
import struct
import logging
import threading
import time
import subprocess

import numpy as np
import pyaudio
from PySide6.QtCore import QObject, Signal

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

# ── 한국어 숫자 정규화 ────────────────────────────────────────────────────────
_NATIVE_HOURS = ['', '한', '두', '세', '네', '다섯', '여섯', '일곱', '여덟', '아홉',
                 '열', '열한', '열두']
_SINO_ONES = ['', '일', '이', '삼', '사', '오', '육', '칠', '팔', '구']


def _sino(n: int) -> str:
    """정수를 한자어 수사 문자열로 (0~9999)"""
    if n == 0:
        return '영'
    result = ''
    if n >= 1000:
        t = n // 1000
        result += ('' if t == 1 else _SINO_ONES[t]) + '천'
        n %= 1000
    if n >= 100:
        h = n // 100
        result += ('' if h == 1 else _SINO_ONES[h]) + '백'
        n %= 100
    if n >= 10:
        t = n // 10
        result += ('' if t == 1 else _SINO_ONES[t]) + '십'
        n %= 10
    if n > 0:
        result += _SINO_ONES[n]
    return result


def _normalize_text(text: str) -> str:
    """TTS 전 숫자를 한국어 발음으로 변환"""
    # 시(時): 1~12는 고유어, 그 외는 한자어
    def repl_hour(m):
        h = int(m.group(1))
        return (_NATIVE_HOURS[h] if 1 <= h <= 12 else _sino(h)) + '시'

    text = re.sub(r'(\d{1,2})시', repl_hour, text)
    text = re.sub(r'(\d{1,2})분', lambda m: _sino(int(m.group(1))) + '분', text)
    text = re.sub(r'(\d{1,2})초', lambda m: _sino(int(m.group(1))) + '초', text)
    # 나머지 숫자 → 한자어
    text = re.sub(r'\d+', lambda m: _sino(int(m.group(0))), text)
    return text
COSYVOICE_DIR = r"D:\Git\CosyVoice"
DEFAULT_MODEL_DIR = os.path.join(COSYVOICE_DIR, "pretrained_models", "Fun-CosyVoice3-0.5B")

def _get_reference_wav() -> str:
    """reference.wav 경로: appdata 우선, 없으면 번들"""
    from resource_manager import ResourceManager
    appdata_path = ResourceManager.get_writable_path("reference.wav")
    if os.path.exists(appdata_path):
        return appdata_path
    return os.path.join(_HERE, "reference.wav")

def _get_worker_script() -> str:
    """cosyvoice_worker.py 경로: frozen이면 _MEIPASS, 아니면 _HERE"""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, "cosyvoice_worker.py")
    return os.path.join(_HERE, "cosyvoice_worker.py")


class CosyVoiceTTS(QObject):
    playback_finished = Signal()

    def __init__(self, model_dir=None, reference_wav=None, reference_text="", speed=0.9):
        super().__init__()
        self.model_dir = model_dir or DEFAULT_MODEL_DIR
        self.reference_wav = reference_wav or _get_reference_wav()
        self.reference_text = reference_text
        self.speed = speed

        self.pa = pyaudio.PyAudio()
        self.sample_rate = 24000  # 워커에서 갱신됨
        self.is_playing = False
        self._proc = None
        self._ready = threading.Event()
        self._ctrl_q = []
        self._ctrl_lock = threading.Lock()
        self._speak_lock = threading.Lock()

        self._start_worker()

    # ── 서브프로세스 ────────────────────────────────────────────────────────────

    def _start_worker(self):
        cmd = [
            _get_python_exe(), _get_worker_script(),
            "--model-dir", self.model_dir,
            "--reference-wav", self.reference_wav,
            "--reference-text", self.reference_text,
            "--cosyvoice-dir", COSYVOICE_DIR,
            "--speed", str(self.speed),
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,   # 이진 PCM 스트림
            stderr=subprocess.PIPE,   # 텍스트 제어 메시지
        )
        threading.Thread(target=self._stderr_reader, daemon=True).start()

        logging.info("CosyVoice3 워커 시작 중 (모델 로드 중, 약 30~60초)...")
        if not self._ready.wait(timeout=120):
            logging.error("CosyVoice3 워커 타임아웃 (120초 초과) — 워커 프로세스를 확인하세요.")
        else:
            logging.info(f"CosyVoice3 워커 준비 완료 (sample_rate={self.sample_rate})")

    def _stderr_reader(self):
        """워커 stderr(제어 채널)을 읽어 이벤트 설정"""
        try:
            for raw in self._proc.stderr:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if line.startswith("SAMPLERATE:"):
                    self.sample_rate = int(line.split(":")[1])
                elif line == "READY":
                    self._ready.set()
                elif line.startswith("INFO:"):
                    logging.info(f"[worker] {line[5:]}")
                elif line.startswith("DONE:") or line.startswith("ERROR:"):
                    with self._ctrl_lock:
                        self._ctrl_q.append(line)
                else:
                    logging.debug(f"[worker] {line}")
        except Exception as e:
            logging.error(f"stderr 읽기 오류: {e}")

    def _wait_ctrl(self, timeout=60) -> str:
        """DONE/ERROR 제어 메시지 대기"""
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._ctrl_lock:
                if self._ctrl_q:
                    return self._ctrl_q.pop(0)
            time.sleep(0.05)
        return "ERROR:timeout"

    # ── 합성 + 스트리밍 재생 ────────────────────────────────────────────────────

    def speak(self, text: str) -> bool:
        text = _normalize_text(text)
        if not text or self._proc is None or self._proc.poll() is not None:
            return False

        # 워커가 아직 준비되지 않았으면 대기 (최대 120초)
        if not self._ready.is_set():
            logging.info("[TTS] 워커 준비 대기 중...")
            if not self._ready.wait(timeout=120):
                logging.error("[TTS] 워커 준비 타임아웃 — speak() 건너뜀")
                return False

        with self._speak_lock:
            try:
                self.is_playing = True
                t0 = time.time()

                # 워커에 텍스트 전송
                self._proc.stdin.write((text.replace("\n", " ").strip() + "\n").encode("utf-8"))
                self._proc.stdin.flush()

                # 링 버퍼 + 완료 이벤트
                ring = bytearray()
                ring_lock = threading.Lock()
                gen_done = threading.Event()

                def pipe_reader():
                    first = True
                    try:
                        while True:
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
                                logging.info(f"[TTS] 첫 청크 수신 → 재생 시작: {time.time()-t0:.2f}s")
                                first = False
                            with ring_lock:
                                ring.extend(data)
                    finally:
                        gen_done.set()

                reader_t = threading.Thread(target=pipe_reader, daemon=True)
                reader_t.start()

                # PyAudio 콜백 모드 — 오디오 클록이 독립적으로 동작,
                # 데이터 부족 시 무음 패딩 → 언더플로 끊김 완전 방지
                def audio_callback(in_data, frame_count, time_info, status):
                    needed = frame_count * 4  # float32 = 4바이트
                    with ring_lock:
                        avail = len(ring)
                        take = min(avail, needed)
                        chunk = bytes(ring[:take])
                        del ring[:take]
                        empty_and_done = gen_done.is_set() and len(ring) == 0

                    if take < needed:
                        chunk += b"\x00" * (needed - take)  # 무음으로 패딩

                    flag = pyaudio.paComplete if empty_and_done else pyaudio.paContinue
                    return (chunk, flag)

                pa_stream = self.pa.open(
                    format=pyaudio.paFloat32,
                    channels=1,
                    rate=self.sample_rate,
                    output=True,
                    frames_per_buffer=1024,  # 콜백 모드: 작을수록 레이턴시 ↓
                    stream_callback=audio_callback,
                )
                pa_stream.start_stream()

                # 생성 완료 대기 (최대 120초)
                reader_t.join(timeout=120)
                # reader가 끝났거나 타임아웃됐어도 gen_done을 강제 설정
                # → 콜백이 paComplete를 반환할 수 있게 함
                gen_done.set()
                # 남은 오디오 재생 완료 대기 (최대 30초)
                deadline = time.time() + 30
                while pa_stream.is_active() and time.time() < deadline:
                    time.sleep(0.02)

                pa_stream.stop_stream()
                pa_stream.close()

                logging.info(f"[TTS] 전체 완료: {time.time()-t0:.2f}s")

                ctrl = self._wait_ctrl(timeout=30)
                if ctrl.startswith("ERROR:"):
                    logging.error(f"워커 오류: {ctrl[6:]}")

                self.is_playing = False
                self.playback_finished.emit()
                return not ctrl.startswith("ERROR:")

            except Exception as e:
                logging.error(f"CosyVoice TTS speak 오류: {e}")
                self.is_playing = False
                self.playback_finished.emit()
                return False

    def _read_exact(self, n: int):
        """stdout에서 정확히 n바이트 읽기"""
        buf = b""
        while len(buf) < n:
            chunk = self._proc.stdout.read(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    # ── 정리 ───────────────────────────────────────────────────────────────────

    def cleanup(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.write(b"EXIT\n")
                self._proc.stdin.flush()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
        if hasattr(self, "pa"):
            try:
                self.pa.terminate()
            except Exception:
                pass

    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass

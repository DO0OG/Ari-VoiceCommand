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
        from audio_manager import GlobalAudio
        self.model_dir = model_dir or DEFAULT_MODEL_DIR
        self.reference_wav = reference_wav or _get_reference_wav()
        self.reference_text = reference_text
        self.speed = speed

        self.pa = GlobalAudio.get_instance()
        self.sample_rate = 24000  # 워커에서 갱신됨
        self.is_playing = False
        self._proc = None
        self._ready = threading.Event()
        self._warmup_ready = threading.Event()  # 추가: 웜업 완료 이벤트
        self._ctrl_q = []
        self._ctrl_lock = threading.Lock()
        self._speak_lock = threading.Lock()
        self._stopping = False  # 종료 플래그 추가

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
        self._proc = subprocess.Popen(  # nosec B603 - controlled local worker process
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,   # 이진 PCM 스트림
            stderr=subprocess.PIPE,   # 텍스트 제어 메시지
        )
        self._stderr_thread = threading.Thread(target=self._stderr_reader, daemon=True)
        self._stderr_thread.start()

        logging.info("CosyVoice3 워커 시작 중 (모델 로드 중, 약 30~60초)...")
        # 워커가 READY 신호를 보낼 때까지 대기
        if not self._ready.wait(timeout=300):
            logging.error("CosyVoice3 워커 타임아웃 (300초 초과) — 워커 프로세스를 확인하세요.")
        else:
            logging.info(f"CosyVoice3 워커 준비 완료 (sample_rate={self.sample_rate})")

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
        """웜업 완료 대기"""
        logging.info("CosyVoice3 웜업 완료 대기 중...")
        return self._warmup_ready.wait(timeout=timeout)

    def _wait_ctrl(self, timeout=120) -> str:
        """DONE/ERROR 제어 메시지 대기 (타임아웃 연장)"""
        import time
        deadline = time.time() + timeout
        while time.time() < deadline and not self._stopping:
            with self._ctrl_lock:
                if self._ctrl_q:
                    return self._ctrl_q.pop(0)
            time.sleep(0.05)
        return "ERROR:timeout"

    # ── 합성 + 스트리밍 재생 ────────────────────────────────────────────────────

    def speak(self, text: str) -> bool:
        from audio_manager import _audio_output_lock as _audio_lock
        text = _normalize_text(text)
        if not text or self._proc is None or self._proc.poll() is not None:
            return False

        # 워커가 아직 준비되지 않았으면 대기 (최대 300초)
        if not self._ready.is_set():
            logging.info("[TTS] 워커 준비 대기 중...")
            if not self._ready.wait(timeout=300):
                logging.error("[TTS] 워커 준비 타임아웃 — speak() 건너뜀")
                return False

        # 오디오 장치 사용을 위해 락 획득
        with _audio_lock:
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
                                    logging.info(f"[TTS] 첫 청크 수신 → 재생 시작: {time.time()-t0:.2f}s")
                                    first = False
                                with ring_lock:
                                    ring.extend(data)
                        except Exception as e:
                            if not self._stopping:
                                logging.debug(f"pipe_reader 오류: {e}")
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

                    # 생성 완료 대기 (최대 300초)
                    reader_t.join(timeout=300)
                    # reader가 끝났거나 타임아웃됐어도 gen_done을 강제 설정
                    # → 콜백이 paComplete를 반환할 수 있게 함
                    gen_done.set()
                    # 남은 오디오 재생 완료 대기 (드레인 강화)
                    deadline = time.time() + 30
                    if pa_stream:
                        while pa_stream.is_active() and time.time() < deadline and not self._stopping:
                            time.sleep(0.1)

                    try:
                        if pa_stream:
                            pa_stream.stop_stream()
                            pa_stream.close()
                    except Exception:  # nosec B110
                        pass
                    if self._stopping:
                        return False

                    logging.info(f"[TTS] 전체 완료: {time.time()-t0:.2f}s")

                    ctrl = self._wait_ctrl(timeout=60)
                    if ctrl.startswith("ERROR:"):
                        logging.error(f"워커 오류: {ctrl[6:]}")

                    self.is_playing = False
                    self.playback_finished.emit()
                    return not ctrl.startswith("ERROR:")

                except Exception as e:
                    if not self._stopping:
                        logging.error(f"CosyVoice TTS speak 오류: {e}")
                    self.is_playing = False
                    self.playback_finished.emit()
                    return False

    def _read_exact(self, n: int):
        """stdout에서 정확히 n바이트 읽기"""
        buf = b""
        try:
            while len(buf) < n and not self._stopping:
                chunk = self._proc.stdout.read(n - len(buf))
                if not chunk:
                    return None
                buf += chunk
        except Exception:  # nosec B110
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
                if self._proc.wait(timeout=2) is None:
                    self._proc.terminate()
            except Exception:
                try:
                    self._proc.kill()
                except Exception:  # nosec B110
                    pass

        # PyAudio 정리는 AriCore.cleanup()에서 GlobalAudio.terminate() 호출로 통합 관리
    def __del__(self):
        try:
            self.cleanup()
        except Exception:  # nosec B110
            pass

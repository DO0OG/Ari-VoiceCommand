"""
Fish Audio WebSocket TTS (Streaming Optimized)
첫 청크 수신 즉시 재생을 시작하여 레이턴시를 최소화합니다.
"""
import os
import logging
import time
import threading
import queue
import subprocess
from contextlib import contextmanager
import pyaudio
from fish_audio_sdk import Session, TTSRequest
from PySide6.QtCore import QObject, Signal


@contextmanager
def _suppress_decoder_console():
    if os.name != "nt":
        yield
        return

    original_popen = subprocess.Popen

    def _wrapped_popen(*args, **kwargs):
        kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return original_popen(*args, **kwargs)

    subprocess.Popen = _wrapped_popen
    try:
        yield
    finally:
        subprocess.Popen = original_popen


def _decode_mp3_segment(audio_bytes: bytes):
    from pydub import AudioSegment
    import io

    with _suppress_decoder_console():
        return AudioSegment.from_mp3(io.BytesIO(audio_bytes))


class FishTTSWebSocket(QObject):
    playback_finished = Signal()  # TTS 재생 완료 시그널
    _QUEUE_MAX_CHUNKS = 24

    def __init__(self, api_key="", reference_id=""):
        super().__init__()
        from audio.audio_manager import GlobalAudio
        self.session = Session(api_key)
        self.reference_id = reference_id
        self.pa = GlobalAudio.get_instance()
        self.is_playing = False
        self.play_thread = None  # 추가
        self.stop_event = threading.Event()  # 추가
        logging.info("🌊 Fish Audio Streaming TTS Initialized")

    def speak(self, text):
        """텍스트를 음성으로 변환 (저레이턴시 스트리밍)"""
        if not text:
            return False

        try:
            logging.info(f"TTS 요청: {text[:30]}...")

            req = TTSRequest(
                text=text,
                reference_id=self.reference_id or None,
                latency="balanced",
                format="mp3",
            )

            def _iter_websocket_chunks():
                with self.session.websocket() as ws:
                    yield from ws.tts(req)

            audio_stream = _iter_websocket_chunks()

            # 재생용 큐와 이벤트
            # self.stop_event를 공유해야 cleanup()이 play_worker도 중단시킬 수 있음
            audio_queue = queue.Queue(maxsize=self._QUEUE_MAX_CHUNKS)
            self.stop_event.clear()
            stop_event = self.stop_event
            download_done = threading.Event()

            def play_worker():
                """스트리밍 재생 워커 (반응성 및 안정성 최적화)"""
                stream = None
                chunk_buffer = []
                INITIAL_BUFFER_SIZE = 3  # 2 -> 3: 긴 문장 초기 안정성 확보

                try:
                    # 1단계: 초기 버퍼 확보
                    for _ in range(INITIAL_BUFFER_SIZE):
                        try:
                            chunk = audio_queue.get(timeout=3.0)
                            if chunk is None: break
                            chunk_buffer.append(chunk)
                        except queue.Empty: break

                    if not chunk_buffer: return

                    # 첫 재생 장치 열기 및 즉시 재생
                    combined = b"".join(chunk_buffer)
                    segment = _decode_mp3_segment(combined)

                    from audio.audio_manager import _audio_output_lock
                    # pa.open()만 락으로 보호 (stream.write는 블로킹 콜이므로 락 밖으로)
                    with _audio_output_lock:
                        stream = self.pa.open(
                            format=self.pa.get_format_from_width(segment.sample_width),
                            channels=segment.channels,
                            rate=segment.frame_rate,
                            output=True,
                            frames_per_buffer=4096
                        )
                    stream.write(segment.raw_data)
                    chunk_buffer.clear()

                    # 2단계: 연속 스트리밍 재생 (적응형 디코딩)
                    mp3_buffer = b""
                    MIN_DECODE_SIZE = 8192

                    while not stop_event.is_set():
                        try:
                            chunk = audio_queue.get(timeout=0.1)
                            if chunk is None: break
                            mp3_buffer += chunk

                            if len(mp3_buffer) >= MIN_DECODE_SIZE:
                                try:
                                    segment = _decode_mp3_segment(mp3_buffer)
                                    stream.write(segment.raw_data)
                                    mp3_buffer = b""
                                except Exception:
                                    if len(mp3_buffer) > 32768: mp3_buffer = b""
                                    continue
                        except queue.Empty:
                            if download_done.is_set() and not mp3_buffer: break
                            continue

                    # 3단계: 남은 데이터 처리 및 스트림 드레인
                    if mp3_buffer:
                        try:
                            segment = _decode_mp3_segment(mp3_buffer)
                            stream.write(segment.raw_data)
                        except Exception:  # nosec B110
                            pass

                    # 하드웨어 버퍼 소진 대기 — 레이턴시 최적화 (10초 -> 1.5초)
                    if stream:
                        # 데이터 전송 후 소리가 실제로 나가는 시간을 고려하여 짧게 대기
                        drain_deadline = time.time() + 1.5
                        while stream.is_active() and time.time() < drain_deadline:
                            time.sleep(0.01)

                except Exception as e:
                    logging.error(f"재생 워커 오류: {e}")

                finally:
                    if stream:
                        try:
                            # stop_stream() 대신 즉시 close()하여 반응성 확보
                            stream.close()
                        except Exception:  # nosec B110
                            pass
                    logging.debug("재생 장치 닫기 완료")

            # 재생 스레드 시작
            self.is_playing = True
            self.stop_event.clear()
            self.play_thread = threading.Thread(target=play_worker, daemon=True)
            self.play_thread.start()

            # 스트림에서 청크 받아서 큐에 추가
            chunk_count = 0
            for chunk in audio_stream:
                if self.stop_event.is_set():
                    break
                while not self.stop_event.is_set():
                    try:
                        audio_queue.put(chunk, timeout=0.2)
                        break
                    except queue.Full:
                        continue
                chunk_count += 1
                if chunk_count == 1:
                    logging.info("[TTS] 첫 청크 수신")

            # 다운로드 완료 알림
            download_done.set()
            audio_queue.put(None)
            logging.debug(f"다운로드 완료 ({chunk_count}개 청크)")

            # 재생 완료 대기 — 최대 15초, 초과 시 강제 중단
            self.play_thread.join(timeout=15.0)
            if self.play_thread.is_alive():
                logging.warning("재생 스레드 타임아웃 — 강제 중단")
                self.stop_event.set()
                self.play_thread.join(timeout=2.0)

            # 완전히 끝날 때까지 0.2초 추가 여유 (OS 사운드 버퍼 고려)
            time.sleep(0.2)
            
            self.is_playing = False
            self.playback_finished.emit()
            logging.debug("TTS 재생 프로세스 완전 종료")

            return True

        except Exception as e:
            logging.error(f"TTS 오류: {e}")
            import traceback
            traceback.print_exc()
            self.is_playing = False
            self.playback_finished.emit()
            return False

    def cleanup(self):
        """리소스 정리"""
        self.stop_event.set()
        if self.play_thread and self.play_thread.is_alive():
            self.play_thread.join(timeout=1.0)
        self.is_playing = False

    def __del__(self):
        pass

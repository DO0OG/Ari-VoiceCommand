"""
Fish Audio WebSocket TTS
WAV 전체 수신 후 wave 모듈로 파싱하여 재생합니다.
"""
import io
import logging
import queue
import threading
import time
import wave

from fish_audio_sdk import Session, TTSRequest
from PySide6.QtCore import QObject, Signal


class FishTTSWebSocket(QObject):
    playback_finished = Signal()
    _QUEUE_MAX_CHUNKS = 64

    def __init__(self, api_key="", reference_id=""):
        super().__init__()
        from audio.audio_manager import GlobalAudio
        try:
            self.session = Session(api_key)
        except Exception as exc:
            raise RuntimeError(f"Fish Audio 세션 초기화 실패: {exc}") from exc
        self.reference_id = reference_id
        self.pa = GlobalAudio.get_instance()
        self.is_playing = False
        self.play_thread = None
        self.stop_event = threading.Event()
        logging.info("🌊 Fish Audio Streaming TTS Initialized")

    def speak(self, text, emotion: str = "평온"):
        """텍스트를 음성으로 변환하여 재생"""
        if not text:
            return False

        try:
            logging.info(f"TTS 요청: {text[:30]}...")

            req = TTSRequest(
                text=text,
                reference_id=self.reference_id or None,
                latency="balanced",
                format="wav",
            )

            audio_stream = self.session.tts(req)

            audio_queue = queue.Queue(maxsize=self._QUEUE_MAX_CHUNKS)
            self.stop_event.clear()
            stop_event = self.stop_event
            download_done = threading.Event()

            def play_worker():
                # 1단계: 전체 WAV 수집
                buf = io.BytesIO()
                while not stop_event.is_set():
                    try:
                        chunk = audio_queue.get(timeout=0.5)
                        if chunk is None:
                            break
                        buf.write(chunk)
                    except queue.Empty:
                        if download_done.is_set():
                            break

                if stop_event.is_set():
                    return

                wav_bytes = buf.getvalue()
                if not wav_bytes:
                    return

                # 2단계: wave 모듈로 파싱
                try:
                    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                        channels = wf.getnchannels()
                        sample_width = wf.getsampwidth()
                        sample_rate = wf.getframerate()
                        frames = wf.readframes(wf.getnframes())
                    logging.info(
                        f"[TTS] WAV 파라미터: {sample_rate}Hz {channels}ch "
                        f"{sample_width * 8}bit / {len(frames)} bytes"
                    )
                except Exception as exc:
                    logging.error(f"WAV 파싱 실패: {exc}")
                    return

                # 3단계: PyAudio 재생
                from audio.audio_manager import _audio_output_lock
                stream = None
                try:
                    with _audio_output_lock:
                        stream = self.pa.open(
                            format=self.pa.get_format_from_width(sample_width),
                            channels=channels,
                            rate=sample_rate,
                            output=True,
                            frames_per_buffer=4096,
                        )

                    # 중단 가능하도록 청크 단위 재생
                    chunk_bytes = 4096 * channels * sample_width
                    offset = 0
                    while offset < len(frames) and not stop_event.is_set():
                        end = min(offset + chunk_bytes, len(frames))
                        stream.write(frames[offset:end])
                        offset = end

                    # 하드웨어 버퍼 소진 대기
                    drain_deadline = time.time() + 1.5
                    while stream.is_active() and time.time() < drain_deadline:
                        time.sleep(0.01)

                except Exception as exc:
                    logging.error(f"재생 오류: {exc}")
                finally:
                    if stream:
                        try:
                            stream.close()
                        except Exception:  # nosec B110
                            pass
                    logging.debug("재생 장치 닫기 완료")

            self.is_playing = True
            self.play_thread = threading.Thread(target=play_worker, daemon=True)
            self.play_thread.start()

            # 다운로드 (메인 스레드)
            chunk_count = 0
            for chunk in audio_stream:
                if stop_event.is_set():
                    break
                while not stop_event.is_set():
                    try:
                        audio_queue.put(chunk, timeout=0.2)
                        break
                    except queue.Full:
                        continue
                chunk_count += 1
                if chunk_count == 1:
                    logging.info("[TTS] 첫 청크 수신")

            download_done.set()
            audio_queue.put(None)
            logging.debug(f"다운로드 완료 ({chunk_count}개 청크)")

            self.play_thread.join(timeout=30.0)
            if self.play_thread.is_alive():
                logging.warning("재생 스레드 타임아웃 — 강제 중단")
                self.stop_event.set()
                self.play_thread.join(timeout=2.0)

            time.sleep(0.1)
            self.is_playing = False
            self.playback_finished.emit()
            logging.debug("TTS 재생 프로세스 완전 종료")
            return True

        except Exception as exc:
            logging.error(f"TTS 오류: {exc}")
            import traceback
            traceback.print_exc()
            self.is_playing = False
            self.playback_finished.emit()
            return False

    def cleanup(self):
        self.stop_event.set()
        if self.play_thread and self.play_thread.is_alive():
            self.play_thread.join(timeout=1.0)
        self.is_playing = False

    def __del__(self):
        pass

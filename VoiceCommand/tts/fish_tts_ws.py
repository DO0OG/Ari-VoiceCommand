"""
Fish Audio HTTP TTS
WAV 전체 수신 후 wave 모듈로 파싱하여 재생한다.
"""
import io
import logging
import queue
import threading
import time
import wave

import ormsgpack
import requests
from PySide6.QtCore import QObject, Signal


class FishTTSWebSocket(QObject):
    playback_finished = Signal()
    _QUEUE_MAX_CHUNKS = 64
    _MIN_PLAYBACK_JOIN_TIMEOUT_SEC = 30.0
    _PLAYBACK_TIMEOUT_GRACE_RATIO = 0.15
    _PLAYBACK_TIMEOUT_GRACE_MIN_SEC = 5.0
    _PLAYBACK_TIMEOUT_MAX_SEC = 900.0

    # SDK 기본 백엔드(speech-1.5)는 유료 등급이라 명시하지 않으면 과금된다.
    _DEFAULT_MODEL = "s2.1-pro-free"
    # __init__을 거치지 않고 생성되는 경우(테스트 등)에도 항상 값이 있도록 한다.
    model = _DEFAULT_MODEL

    def __init__(self, api_key="", reference_id="", model=""):
        super().__init__()
        from audio.audio_manager import GlobalAudio
        self.api_key = api_key
        self.reference_id = reference_id
        self.model = model or self._DEFAULT_MODEL
        self.pa = GlobalAudio.get_instance()
        self.is_playing = False
        self.play_thread = None
        self.stop_event = threading.Event()
        logging.info("🌊 Fish Audio Streaming TTS Initialized")

    def _stream_tts(self, text):
        payload = {
            "text": text,
            "chunk_length": 200,
            "format": "wav",
            "sample_rate": None,
            "mp3_bitrate": 128,
            "opus_bitrate": 32,
            "references": [],
            "reference_id": self.reference_id or None,
            "normalize": True,
            "latency": "balanced",
            "prosody": None,
            "top_p": 0.7,
            "temperature": 0.7,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/msgpack",
            "model": self.model,
        }

        with requests.post(
            "https://api.fish.audio/v1/tts",
            headers=headers,
            data=ormsgpack.packb(payload),
            stream=True,
            timeout=(10, 60),
        ) as response:
            if not 200 <= response.status_code < 300:
                try:
                    error_body = response.json()
                except ValueError:
                    error_body = None
                if isinstance(error_body, dict):
                    message = error_body.get("detail") or error_body.get("message")
                else:
                    message = None
                if not message:
                    message = response.text.strip() or "No error detail returned"
                raise RuntimeError(
                    f"Fish Audio API request failed ({response.status_code}): {message}"
                )

            for chunk in response.iter_content(chunk_size=None):
                if chunk:
                    yield chunk

    def speak(self, text, emotion: str = "평온"):
        """텍스트를 음성으로 변환하여 재생"""
        if not text:
            return False

        try:
            logging.info(f"TTS 요청: {text[:30]}...")

            audio_stream = self._stream_tts(text)

            audio_queue = queue.Queue(maxsize=self._QUEUE_MAX_CHUNKS)
            self.stop_event.clear()
            stop_event = self.stop_event
            download_done = threading.Event()
            metadata_ready = threading.Event()
            playback_meta = {"duration_sec": 0.0}

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
                    metadata_ready.set()
                    return

                # 2단계: wave 모듈로 파싱
                try:
                    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                        channels = wf.getnchannels()
                        sample_width = wf.getsampwidth()
                        sample_rate = wf.getframerate()
                        frames = wf.readframes(wf.getnframes())
                    duration_sec = _estimate_pcm_duration_seconds(
                        len(frames),
                        sample_rate,
                        channels,
                        sample_width,
                    )
                    playback_meta["duration_sec"] = duration_sec
                    metadata_ready.set()
                    logging.info(
                        f"[TTS] WAV 파라미터: {sample_rate}Hz {channels}ch "
                        f"{sample_width * 8}bit / {len(frames)} bytes "
                        f"({duration_sec:.1f}s)"
                    )
                except Exception as exc:
                    metadata_ready.set()
                    logging.error(f"WAV 파싱 실패: {exc}")
                    return

                # 3단계: PyAudio 재생
                from audio.audio_manager import _audio_output_lock, get_output_device_index
                stream = None
                try:
                    out_idx = get_output_device_index()
                    with _audio_output_lock:
                        stream = self.pa.open(
                            format=self.pa.get_format_from_width(sample_width),
                            channels=channels,
                            rate=sample_rate,
                            output=True,
                            output_device_index=out_idx,
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
            try:
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
            finally:
                close_stream = getattr(audio_stream, "close", None)
                if close_stream:
                    close_stream()

            download_done.set()
            audio_queue.put(None)
            logging.debug(f"다운로드 완료 ({chunk_count}개 청크)")

            metadata_ready.wait(timeout=5.0)
            playback_timeout = _playback_join_timeout(
                playback_meta.get("duration_sec", 0.0)
            )
            self.play_thread.join(timeout=playback_timeout)
            if self.play_thread.is_alive():
                logging.warning(
                    "재생 스레드 타임아웃 — 강제 중단 (예상 재생 %.1fs, 대기 %.1fs)",
                    playback_meta.get("duration_sec", 0.0),
                    playback_timeout,
                )
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


def _estimate_pcm_duration_seconds(
    frame_bytes: int,
    sample_rate: int,
    channels: int,
    sample_width: int,
) -> float:
    bytes_per_second = sample_rate * channels * sample_width
    if bytes_per_second <= 0:
        return 0.0
    return max(0.0, frame_bytes / bytes_per_second)


def _playback_join_timeout(duration_sec: float) -> float:
    if duration_sec <= 0:
        return FishTTSWebSocket._MIN_PLAYBACK_JOIN_TIMEOUT_SEC

    grace_sec = max(
        FishTTSWebSocket._PLAYBACK_TIMEOUT_GRACE_MIN_SEC,
        duration_sec * FishTTSWebSocket._PLAYBACK_TIMEOUT_GRACE_RATIO,
    )
    timeout = duration_sec + grace_sec
    timeout = max(timeout, FishTTSWebSocket._MIN_PLAYBACK_JOIN_TIMEOUT_SEC)
    return min(timeout, FishTTSWebSocket._PLAYBACK_TIMEOUT_MAX_SEC)

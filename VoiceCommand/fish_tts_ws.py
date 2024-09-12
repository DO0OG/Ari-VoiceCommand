"""
Fish Audio WebSocket TTS (Streaming Optimized)
첫 청크 수신 즉시 재생을 시작하여 레이턴시를 최소화합니다.
"""
import logging
import io
import threading
import queue
import pyaudio
from fishaudio import FishAudio
from PySide6.QtCore import QObject, Signal


class FishTTSWebSocket(QObject):
    playback_finished = Signal()  # TTS 재생 완료 시그널

    def __init__(self, api_key="", reference_id=""):
        super().__init__()
        self.client = FishAudio(api_key=api_key) if api_key else FishAudio()
        self.reference_id = reference_id
        self.pa = pyaudio.PyAudio()
        self.is_playing = False
        self.play_thread = None  # 추가
        self.stop_event = threading.Event()  # 추가
        logging.info("🌊 Fish Audio Streaming TTS Initialized")

    def speak(self, text):
        """텍스트를 음성으로 변환 (저레이턴시 스트리밍)"""
        if not text:
            return False

        try:
            from pydub import AudioSegment
            import io

            def text_gen():
                yield text

            logging.info(f"TTS 요청: {text[:30]}...")

            audio_stream = self.client.tts.stream_websocket(
                text_gen(),
                reference_id=self.reference_id,
                latency="balanced",
                format="mp3"
            )

            # 재생용 큐와 이벤트
            audio_queue = queue.Queue()
            stop_event = threading.Event()
            download_done = threading.Event()

            def play_worker():
                """스트리밍 재생 워커 (적응형 버퍼링)"""
                stream = None
                chunk_buffer = []
                INITIAL_BUFFER_SIZE = 3  # 초기 버퍼: 3개 청크 (레이턴시 vs 안정성 절충)

                try:
                    # 1단계: 초기 버퍼 확보
                    logging.info(f"초기 버퍼 확보 중 ({INITIAL_BUFFER_SIZE}개 청크)...")
                    for _ in range(INITIAL_BUFFER_SIZE):
                        try:
                            chunk = audio_queue.get(timeout=3.0)
                            if chunk is None:
                                break
                            chunk_buffer.append(chunk)
                        except queue.Empty:
                            break

                    if not chunk_buffer:
                        logging.error("초기 버퍼 비어있음")
                        return

                    # 초기 버퍼 디코딩 및 재생 시작
                    combined = b"".join(chunk_buffer)
                    segment = AudioSegment.from_mp3(io.BytesIO(combined))

                    stream = self.pa.open(
                        format=self.pa.get_format_from_width(segment.sample_width),
                        channels=segment.channels,
                        rate=segment.frame_rate,
                        output=True,
                        frames_per_buffer=8192  # 8KB로 증가 (끊김 최소화)
                    )

                    logging.info(f"재생 시작 (초기 {len(chunk_buffer)}개 청크)")
                    stream.write(segment.raw_data)
                    chunk_buffer.clear()

                    # 2단계: 적응형 스트리밍 재생
                    mp3_buffer = b""
                    MIN_DECODE_SIZE = 8192  # 8KB로 증가 (안정성 우선)
                    consecutive_failures = 0

                    while not stop_event.is_set():
                        try:
                            chunk = audio_queue.get(timeout=0.15)  # 0.1 → 0.15로 약간 증가
                            if chunk is None:
                                break

                            mp3_buffer += chunk

                            # 적응형 버퍼 크기: 디코딩 실패가 많으면 더 모으기
                            adaptive_size = MIN_DECODE_SIZE + (consecutive_failures * 2048)

                            # 버퍼가 충분히 모이면 디코딩 후 재생
                            if len(mp3_buffer) >= adaptive_size:
                                try:
                                    segment = AudioSegment.from_mp3(io.BytesIO(mp3_buffer))
                                    stream.write(segment.raw_data)
                                    mp3_buffer = b""
                                    consecutive_failures = 0  # 성공 시 리셋
                                except Exception as e:
                                    # 디코딩 실패 = 불완전한 MP3 프레임
                                    consecutive_failures += 1
                                    if consecutive_failures > 3:
                                        # 3번 이상 실패 시 큐에서 추가 청크 대기
                                        try:
                                            extra_chunk = audio_queue.get(timeout=0.1)
                                            if extra_chunk:
                                                mp3_buffer += extra_chunk
                                        except:
                                            pass

                                    # 버퍼가 너무 크면 일부 버림
                                    if len(mp3_buffer) > 40960:  # 40KB
                                        logging.warning(f"버퍼 오버플로우, 일부 버림")
                                        mp3_buffer = mp3_buffer[-20480:]
                                        consecutive_failures = 0

                        except queue.Empty:
                            # 큐가 비었지만 버퍼에 데이터가 있으면 재생 시도
                            if len(mp3_buffer) >= 2048:
                                try:
                                    segment = AudioSegment.from_mp3(io.BytesIO(mp3_buffer))
                                    stream.write(segment.raw_data)
                                    mp3_buffer = b""
                                    consecutive_failures = 0
                                except:
                                    pass

                            # 다운로드 완료 확인
                            if download_done.is_set():
                                break
                            continue

                    # 3단계: 남은 버퍼 재생
                    if mp3_buffer:
                        try:
                            segment = AudioSegment.from_mp3(io.BytesIO(mp3_buffer))
                            stream.write(segment.raw_data)
                        except:
                            pass

                except Exception as e:
                    logging.error(f"재생 워커 오류: {e}")

                finally:
                    if stream:
                        stream.stop_stream()
                        stream.close()
                    logging.info("재생 완료")

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
                audio_queue.put(chunk)
                chunk_count += 1
                if chunk_count == 1:
                    logging.info("첫 청크 수신")

            # 다운로드 완료 알림
            download_done.set()
            audio_queue.put(None)
            logging.info(f"다운로드 완료 ({chunk_count}개 청크)")

            # 재생 완료 대기
            self.play_thread.join(timeout=30.0)
            if self.play_thread.is_alive():
                logging.warning("재생 스레드 타임아웃")

            self.is_playing = False
            self.playback_finished.emit()

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
        if hasattr(self, 'pa'):
            self.pa.terminate()

    def __del__(self):
        if hasattr(self, 'pa'):
            self.pa.terminate()

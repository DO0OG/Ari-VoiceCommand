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
                    segment = AudioSegment.from_mp3(io.BytesIO(combined))

                    from audio_manager import _audio_lock
                    with _audio_lock:
                        stream = self.pa.open(
                            format=self.pa.get_format_from_width(segment.sample_width),
                            channels=segment.channels,
                            rate=segment.frame_rate,
                            output=True,
                            frames_per_buffer=4096 # 버퍼 크기 증가로 안정성 향상
                        )
                        stream.write(segment.raw_data)
                    
                    chunk_buffer.clear()

                    # 2단계: 연속 스트리밍 재생 (적응형 디코딩)
                    mp3_buffer = b""
                    MIN_DECODE_SIZE = 8192 # 4KB -> 8KB: 긴 문장 끊김 방지

                    while not stop_event.is_set():
                        try:
                            chunk = audio_queue.get(timeout=0.1)
                            if chunk is None: break
                            mp3_buffer += chunk

                            # 충분한 데이터가 모였을 때만 디코딩하여 재생 (끊김 최소화)
                            if len(mp3_buffer) >= MIN_DECODE_SIZE:
                                try:
                                    segment = AudioSegment.from_mp3(io.BytesIO(mp3_buffer))
                                    with _audio_lock:
                                        stream.write(segment.raw_data)
                                    mp3_buffer = b""
                                except:
                                    # 프레임이 잘렸을 경우 다음 청크 대기
                                    if len(mp3_buffer) > 32768: mp3_buffer = b"" # 오버플로 방지
                                    continue
                        except queue.Empty:
                            if download_done.is_set() and not mp3_buffer: break
                            continue

                    # 3단계: 남은 데이터 처리 및 스트림 드레인
                    if mp3_buffer:
                        try:
                            segment = AudioSegment.from_mp3(io.BytesIO(mp3_buffer))
                            with _audio_lock:
                                stream.write(segment.raw_data)
                        except: pass

                    # 하드웨어 버퍼가 모두 비워질 때까지 대기 (말풍선 유지 핵심)
                    if stream:
                        while stream.is_active():
                            time.sleep(0.1)

                except Exception as e:
                    logging.error(f"재생 워커 오류: {e}")

                finally:
                    if stream:
                        try:
                            stream.stop_stream()
                            stream.close()
                        except: pass
                    logging.info("재생 장치 닫기 완료")

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

            # 재생 완료 대기 (최대 60초로 연장)
            self.play_thread.join(timeout=60.0)
            if self.play_thread.is_alive():
                logging.warning("재생 스레드 종료 지연")

            # 완전히 끝날 때까지 0.2초 추가 여유 (OS 사운드 버퍼 고려)
            time.sleep(0.2)
            
            self.is_playing = False
            self.playback_finished.emit()
            logging.info("TTS 재생 프로세스 완전 종료")

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

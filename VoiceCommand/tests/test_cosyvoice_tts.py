import os
import queue
import struct
import threading
import time
from collections import deque
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


from tts.cosyvoice_utils import (
    _PCMChunkBuffer,
    _normalize_text_cached,
    apply_emotion_prosody,
    inject_breath_cues,
)
from tts import cosyvoice_tts
from tts.cosyvoice_tts import CosyVoiceTTS, _get_reference_wav


VOICECOMMAND_ROOT = str(Path(__file__).resolve().parent.parent)


class PCMChunkBufferTests(unittest.TestCase):
    def test_pop_bytes_preserves_remainder(self):
        buffer = _PCMChunkBuffer()
        buffer.append(b"abcd")
        buffer.append(b"efgh")

        self.assertEqual(buffer.pop_bytes(3), b"abc")
        self.assertEqual(buffer.size, 5)
        self.assertEqual(buffer.pop_bytes(3), b"def")
        self.assertEqual(buffer.size, 2)
        self.assertEqual(buffer.pop_bytes(8), b"gh")
        self.assertEqual(buffer.size, 0)


class CosyVoiceReferencePathTests(unittest.TestCase):
    def test_reference_wav_falls_back_to_bundle_path_when_runtime_copy_missing(self):
        expected = os.path.join(VOICECOMMAND_ROOT, "reference.wav")
        with patch("tts.cosyvoice_tts.os.path.exists", return_value=False):
            self.assertEqual(_get_reference_wav(), expected)

    def test_normalize_cache_returns_same_value(self):
        first = _normalize_text_cached("12시 30분")
        second = _normalize_text_cached("12시 30분")
        self.assertEqual(first, second)
        self.assertIn("열두시", first)

    def test_tts_venv_prefers_user_data_and_recognizes_legacy_path(self):
        from tts.cosyvoice_tts import _find_tts_venv_python

        writable_dir = os.path.abspath(r".ari_runtime\.venv-tts")
        legacy_dir = os.path.join(VOICECOMMAND_ROOT, ".venv-tts")
        writable_python = os.path.join(writable_dir, "Scripts", "python.exe")
        legacy_python = os.path.join(legacy_dir, "Scripts", "python.exe")

        with (
            patch("core.resource_manager.ResourceManager.get_writable_path", return_value=writable_dir),
            patch("tts.cosyvoice_tts.os.path.isfile", side_effect=lambda path: os.fspath(path) == writable_python),
        ):
            self.assertEqual(_find_tts_venv_python(), writable_python)

        with (
            patch("core.resource_manager.ResourceManager.get_writable_path", return_value=writable_dir),
            patch("tts.cosyvoice_tts.os.path.isfile", side_effect=lambda path: os.fspath(path) == legacy_python),
        ):
            self.assertEqual(_find_tts_venv_python(), legacy_python)


class _DummySignal:
    def __init__(self):
        self.emitted = 0

    def emit(self):
        self.emitted += 1


class _FakeStream:
    def __init__(self):
        self.started = False

    def is_active(self):
        return False

    def start_stream(self):
        self.started = True


class _FakeStdin:
    def __init__(self):
        self.writes = []
        self.flush_calls = 0

    def write(self, data):
        self.writes.append(data)

    def flush(self):
        self.flush_calls += 1


class _FakeProc:
    def __init__(self):
        self.stdin = _FakeStdin()

    def poll(self):
        return None


class _PipeStdout:
    def __init__(self):
        self._chunks = queue.Queue()
        self._rest = b""
        self.reads = 0

    def feed(self, *chunks):
        for chunk in chunks:
            self._chunks.put(chunk)

    def read(self, size):
        if not self._rest:
            self.reads += 1
            try:
                self._rest = self._chunks.get(timeout=3)
            except queue.Empty:
                return b""
        out, self._rest = self._rest[:size], self._rest[size:]
        return out


class _PipeProc:
    """워커 흉내: 요청마다 stdout에 길이 접두 PCM을 흘린다."""

    def __init__(self):
        self.stdout = _PipeStdout()
        self.stdin = self
        self.on_write = None
        self.kill_calls = 0
        self.killed = False

    def write(self, _data):
        if self.on_write:
            self.on_write()

    def flush(self):
        pass

    def feed(self, *chunks):
        self.stdout.feed(*chunks)

    def wait_for_reads(self, count, timeout=2):
        deadline = time.monotonic() + timeout
        while self.stdout.reads < count and time.monotonic() < deadline:
            time.sleep(0.01)
        return self.stdout.reads >= count

    def poll(self):
        return -9 if self.killed else None

    def kill(self):
        self.kill_calls += 1
        self.killed = True
        self.stdout.feed(b"")

    def wait(self, timeout=None):
        return 0


def _pcm(data):
    return struct.pack("<I", len(data)) + data


class CosyVoiceTTSSpeakTests(unittest.TestCase):
    def _make_cleanup_tts(self, proc):
        with patch.object(CosyVoiceTTS, "__init__", lambda self, *args, **kwargs: None):
            tts = CosyVoiceTTS()
        tts._proc = proc
        tts._stopping = False
        tts._ready = threading.Event()
        tts._warmup_done = threading.Event()
        tts._stream_lock = threading.Lock()
        tts._stream = None
        tts._stream_rate = None
        tts._state_lock = threading.Lock()
        tts._active_stop_event = None
        tts._clear_pcm_state = Mock()
        tts._close_stream_unlocked = Mock()
        return tts

    def test_cleanup_waits_after_kill(self):
        class Proc:
            def __init__(self):
                self.stdin = _FakeStdin()
                self.alive = True
                self.wait_calls = []
                self.kill_calls = 0

            def poll(self):
                return None if self.alive else 0

            def wait(self, timeout):
                self.wait_calls.append(timeout)
                if len(self.wait_calls) == 1:
                    raise cosyvoice_tts.subprocess.TimeoutExpired("worker", timeout)
                if len(self.wait_calls) == 2:
                    raise cosyvoice_tts.subprocess.TimeoutExpired("worker", timeout)
                self.alive = False
                return 0

            def terminate(self):
                pass

            def kill(self):
                self.kill_calls += 1

        proc = Proc()
        self._make_cleanup_tts(proc).cleanup()

        self.assertEqual(proc.wait_calls, [2, 2, 2])
        self.assertEqual(proc.kill_calls, 1)
        self.assertIsNotNone(proc.poll())

    def test_cleanup_still_terminates_process_after_audio_cleanup_error(self):
        class Proc(_PipeProc):
            def write(self, _data):
                raise OSError("pipe closed")

        proc = Proc()
        tts = self._make_cleanup_tts(proc)
        tts.stop = Mock(side_effect=RuntimeError("audio cleanup failed"))

        tts.cleanup()

        self.assertEqual(proc.kill_calls, 1)
        self.assertIsNotNone(proc.poll())

    def test_speak_streams_worker_output_and_emits_completion(self):
        with patch.object(CosyVoiceTTS, "__init__", lambda self, *args, **kwargs: None):
            tts = CosyVoiceTTS()
        tts._ready = threading.Event()
        tts._ready.set()
        tts._proc = _FakeProc()
        tts._speak_lock = threading.Lock()
        from audio.audio_manager import _audio_output_lock
        tts._state_lock = threading.Lock()
        tts._active_stop_event = None
        tts._request_id = 0
        tts._active_request_id = None
        tts._restart_required = False
        tts._stopping = False
        tts._ctrl_lock = threading.Lock()
        tts._ctrl_q = []
        tts._pcm_lock = threading.Lock()
        tts._pcm_buffer = _PCMChunkBuffer()
        tts._pcm_done = threading.Event()
        tts.playback_finished = _DummySignal()
        tts.is_playing = False
        tts._clear_pcm_state = lambda: None
        tts._close_stream = lambda: None
        worker_lock_state = []
        tts._ensure_worker = lambda _stop_event: worker_lock_state.append(_audio_output_lock.locked()) or True
        fake_stream = _FakeStream()
        tts._ensure_stream = lambda: fake_stream
        tts._wait_ctrl = lambda timeout=60, proc=None, stop_event=None: "DONE:ok"
        payloads = iter([struct.pack("<I", 4), b"data", struct.pack("<I", 0)])
        tts._read_exact = lambda _n, proc=None, stop_event=None: next(payloads, None)

        result = tts.speak("테스트 문장")

        self.assertTrue(result)
        self.assertTrue(fake_stream.started)
        self.assertEqual(tts.playback_finished.emitted, 1)
        self.assertEqual(tts._proc.stdin.flush_calls, 1)
        self.assertEqual(tts._proc.stdin.writes, ["테스트 문장\n".encode("utf-8")])
        self.assertEqual(worker_lock_state, [False])

    def test_worker_failure_does_not_acquire_global_output_lock(self):
        with patch.object(CosyVoiceTTS, "__init__", lambda self, *args, **kwargs: None):
            tts = CosyVoiceTTS()
        from audio.audio_manager import _audio_output_lock
        tts._proc = None
        tts._worker_error = None
        tts._speak_lock = threading.Lock()
        tts._state_lock = threading.Lock()
        tts._request_id = 0
        tts._active_request_id = None
        tts._active_stop_event = None
        tts._stopping = False
        tts.is_playing = False
        tts.playback_finished = _DummySignal()
        tts._clear_pcm_state = lambda: None
        lock_state = []
        tts._ensure_worker = lambda _stop_event: lock_state.append(_audio_output_lock.locked()) or False

        self.assertFalse(tts.speak("테스트 문장"))

        self.assertEqual(lock_state, [False])
        self.assertFalse(_audio_output_lock.locked())

    def test_cleanup_exception_releases_global_output_lock(self):
        tts = self._make_pipe_tts()
        from audio.audio_manager import _audio_output_lock

        class NoThread:
            def __init__(self, *args, **kwargs):
                del args, kwargs

            def start(self):
                pass

            def is_alive(self):
                return False

            def join(self, timeout=None):
                del timeout

        def cancelled(*, timeout, proc, stop_event):
            del timeout, proc
            stop_event.set()
            return "ERROR:cancelled"

        tts._ensure_worker = lambda _stop_event: True
        tts._wait_ctrl = cancelled
        tts._start_drain = Mock(side_effect=RuntimeError("drain failed"))
        stop_event = threading.Event()

        with patch("tts.cosyvoice_tts.threading.Thread", NoThread):
            self.assertFalse(tts.speak("테스트 문장", stop_event=stop_event))

        acquired = _audio_output_lock.acquire(blocking=False)
        self.assertTrue(acquired)
        if acquired:
            _audio_output_lock.release()
        self.assertFalse(tts.is_playing)

    def _make_pipe_tts(self):
        with patch.object(CosyVoiceTTS, "__init__", lambda self, *args, **kwargs: None):
            tts = CosyVoiceTTS()
        tts._proc = _PipeProc()
        tts._ready = threading.Event()
        tts._ready.set()
        tts._worker_error = None
        tts._state_lock = threading.Lock()
        tts._speak_lock = threading.Lock()
        tts._active_stop_event = None
        tts._request_id = 0
        tts._active_request_id = None
        tts._restart_required = False
        tts._drain_event = threading.Event()
        tts._drain_event.set()
        tts._drain_proc = None
        tts._drain_request_id = None
        tts._drain_cancelled_at = None
        tts._stopping = False
        tts._ctrl_lock = threading.Lock()
        tts._ctrl_q = deque()
        tts._pcm_lock = threading.Lock()
        tts._pcm_buffer = _PCMChunkBuffer()
        tts._pcm_done = threading.Event()
        tts.volume = 1.0
        tts.is_playing = False
        tts.playback_finished = _DummySignal()
        tts._ensure_stream = lambda: _FakeStream()
        tts._close_stream = lambda: None
        tts._start_worker = Mock()
        return tts

    def _start_speak(self, tts, text, stop_event):
        result = []
        thread = threading.Thread(
            target=lambda: result.append(tts.speak(text, stop_event=stop_event))
        )
        thread.start()
        return thread, result

    def test_cancel_keeps_worker_and_drains_remaining_output(self):
        tts = self._make_pipe_tts()
        proc = tts._proc
        stop_event = threading.Event()
        thread, result = self._start_speak(tts, "취소할 문장", stop_event)
        proc.feed(_pcm(b"aaaa"))
        self.assertTrue(proc.wait_for_reads(1))

        tts.stop()
        thread.join(2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [False])
        self.assertFalse(tts._drain_event.wait(0.2))  # 종료 표시 전에는 배출 중
        proc.feed(_pcm(b"bbbb"), _pcm(b""))
        tts._ctrl_q.append((proc, "DONE:2"))

        self.assertTrue(tts._drain_event.wait(2))
        self.assertEqual(proc.kill_calls, 0)
        self.assertFalse(tts._restart_required)
        self.assertEqual(tts._pcm_buffer.size, 0)

    def test_next_speak_after_cancel_plays_only_new_request(self):
        tts = self._make_pipe_tts()
        proc = tts._proc
        first_stop = threading.Event()
        thread, _result = self._start_speak(tts, "첫 문장", first_stop)
        proc.feed(_pcm(b"old!"))
        self.assertTrue(proc.wait_for_reads(1))
        tts.stop()
        thread.join(2)
        proc.feed(_pcm(b"old2"), _pcm(b""))
        tts._ctrl_q.append((proc, "DONE:2"))

        proc.on_write = lambda: (
            proc.feed(_pcm(b"new"), _pcm(b"")),
            tts._ctrl_q.append((proc, "DONE:1")),
        )
        result = tts.speak("둘째 문장", stop_event=threading.Event())

        self.assertTrue(result)
        self.assertEqual(proc.kill_calls, 0)
        tts._start_worker.assert_not_called()
        self.assertEqual(tts._pcm_buffer.pop_bytes(100), b"new")

    def test_drain_timeout_restarts_worker(self):
        tts = self._make_pipe_tts()
        tts._DRAIN_TIMEOUT = 0.2
        proc = tts._proc
        stop_event = threading.Event()
        thread, _result = self._start_speak(tts, "취소할 문장", stop_event)
        proc.feed(_pcm(b"aaaa"))
        self.assertTrue(proc.wait_for_reads(1))
        tts.stop()
        thread.join(2)
        tts.wait_until_ready = lambda stop_event=None: True

        self.assertTrue(tts._ensure_worker(threading.Event()))

        self.assertEqual(proc.kill_calls, 1)
        tts._start_worker.assert_called_once()

    def test_explicit_cosyvoice_dir_avoids_cached_discovery(self):
        cosyvoice_dir = os.path.abspath("selected-cosyvoice")
        with (
            patch("tts.cosyvoice_tts._get_reference_wav", return_value="reference.wav"),
            patch("tts.cosyvoice_tts._load_tts_volume", return_value=1.0),
            patch("tts.cosyvoice_tts._get_cosyvoice_dir_cached") as get_cached_dir,
            patch.object(CosyVoiceTTS, "_start_worker"),
        ):
            tts = CosyVoiceTTS(cosyvoice_dir=cosyvoice_dir)

        self.assertEqual(tts._cosyvoice_dir, cosyvoice_dir)
        self.assertEqual(
            tts.model_dir,
            os.path.join(cosyvoice_dir, "pretrained_models", "Fun-CosyVoice3-0.5B"),
        )
        get_cached_dir.assert_not_called()

    def test_stream_open_and_close_use_global_wrappers(self):
        with patch.object(CosyVoiceTTS, "__init__", lambda self, *args, **kwargs: None):
            tts = CosyVoiceTTS()
        tts._stream_lock = threading.Lock()
        tts._stream = None
        tts.sample_rate = 24000
        stream = Mock()

        with patch("tts.cosyvoice_tts.GlobalAudio.open_stream", return_value=stream) as open_stream:
            self.assertIs(tts._open_stream_on(3), stream)

        open_stream.assert_called_once()
        tts._stream = stream
        tts._stream_rate = 24000
        with patch("tts.cosyvoice_tts.GlobalAudio.close_stream") as close_stream:
            tts._close_stream()

        close_stream.assert_called_once_with(stream)
        self.assertIsNone(tts._stream)


class ApplyEmotionProsodyTests(unittest.TestCase):
    def test_neutral_emotion_unchanged(self):
        text = "안녕하세요. 반갑습니다."
        self.assertEqual(apply_emotion_prosody(text, "평온"), text)

    def test_serious_emotion_unchanged(self):
        text = "오류가 발생했습니다."
        self.assertEqual(apply_emotion_prosody(text, "진지"), text)

    def test_joy_replaces_period_with_exclamation(self):
        result = apply_emotion_prosody("좋아요. 정말 기쁩니다.", "기쁨")
        self.assertEqual(result, "좋아요! 정말 기쁩니다!")

    def test_anticipation_replaces_period_with_exclamation(self):
        result = apply_emotion_prosody("기대돼요.", "기대")
        self.assertEqual(result, "기대돼요!")

    def test_anger_replaces_period_with_exclamation(self):
        result = apply_emotion_prosody("화가 납니다.", "화남")
        self.assertEqual(result, "화가 납니다!")

    def test_sadness_replaces_period_with_ellipsis(self):
        result = apply_emotion_prosody("슬퍼요.", "슬픔")
        self.assertEqual(result, "슬퍼요...")

    def test_worry_replaces_period_with_ellipsis(self):
        result = apply_emotion_prosody("걱정돼요.", "걱정")
        self.assertEqual(result, "걱정돼요...")

    def test_shy_replaces_period_with_tilde(self):
        result = apply_emotion_prosody("별말씀을요.", "수줍")
        self.assertEqual(result, "별말씀을요~")

    def test_surprise_replaces_period_with_interrobang(self):
        result = apply_emotion_prosody("정말요.", "놀람")
        self.assertEqual(result, "정말요?!")

    def test_existing_punctuation_preserved(self):
        # 이미 구두점이 있는 문장은 영향받지 않아야 함
        result = apply_emotion_prosody("맞아요! 진짜요?", "기쁨")
        self.assertEqual(result, "맞아요! 진짜요?")

    def test_ellipsis_not_double_transformed(self):
        # 마침표가 연속으로 있는 경우(줄임표 ...) 는 변환하지 않음
        result = apply_emotion_prosody("글쎄요...", "기쁨")
        self.assertEqual(result, "글쎄요...")

    def test_empty_text_unchanged(self):
        self.assertEqual(apply_emotion_prosody("", "기쁨"), "")


class InjectBreathCuesTests(unittest.TestCase):
    def test_long_sentence_adds_single_breath_comma(self):
        text = "오늘 일정 정리했고 메일 답장도 끝냈으니 이제 점심 드시면 됩니다."
        result = inject_breath_cues(text)

        self.assertIn(",", result)
        self.assertTrue(result.endswith("."))

    def test_connector_prefers_breath_before_transition(self):
        text = "오늘 일정 정리했고 그리고 메일 답장도 끝냈으니 이제 점심 드시면 됩니다."
        result = inject_breath_cues(text)

        self.assertIn("정리했고, 그리고", result)

    def test_existing_comma_is_preserved(self):
        text = "안녕하세요, 반갑습니다."
        self.assertEqual(inject_breath_cues(text), text)


if __name__ == "__main__":
    unittest.main()

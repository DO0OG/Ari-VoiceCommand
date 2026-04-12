import os
import struct
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


from tts.cosyvoice_utils import (
    _PCMChunkBuffer,
    _normalize_text_cached,
    apply_emotion_prosody,
    inject_breath_cues,
)
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


class CosyVoiceTTSSpeakTests(unittest.TestCase):
    def test_speak_streams_worker_output_and_emits_completion(self):
        with patch.object(CosyVoiceTTS, "__init__", lambda self, *args, **kwargs: None):
            tts = CosyVoiceTTS()
        tts._ready = threading.Event()
        tts._ready.set()
        tts._proc = _FakeProc()
        tts._speak_lock = threading.Lock()
        tts._stopping = False
        tts._pcm_lock = threading.Lock()
        tts._pcm_buffer = _PCMChunkBuffer()
        tts._pcm_done = threading.Event()
        tts.playback_finished = _DummySignal()
        tts.is_playing = False
        tts._clear_pcm_state = lambda: None
        tts._close_stream = lambda: None
        fake_stream = _FakeStream()
        tts._ensure_stream = lambda: fake_stream
        tts._wait_ctrl = lambda timeout=60: "DONE:ok"
        payloads = iter([struct.pack("<I", 4), b"data", struct.pack("<I", 0)])
        tts._read_exact = lambda _n: next(payloads, None)

        result = tts.speak("테스트 문장")

        self.assertTrue(result)
        self.assertTrue(fake_stream.started)
        self.assertEqual(tts.playback_finished.emitted, 1)
        self.assertEqual(tts._proc.stdin.flush_calls, 1)
        self.assertEqual(tts._proc.stdin.writes, ["테스트 문장\n".encode("utf-8")])


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

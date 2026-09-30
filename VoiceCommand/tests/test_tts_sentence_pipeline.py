import asyncio
import tempfile
import threading
import unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import Mock, patch

from audio.audio_manager import GlobalAudio
from audio import mp3_decoder
from core.constants import get_wake_responses
from i18n.translator import get_language
from tts.tts_cache import DiskTTSAudioCache, build_tts_cache_key
from tts.tts_edge import EdgeTTS, split_sentences


class EdgeTTSSentencePipelineTests(unittest.TestCase):
    @contextmanager
    def _playback_patches(self, stream):
        with ExitStack() as stack:
            yield (
                stack.enter_context(patch.object(GlobalAudio, "open_stream", return_value=stream)),
                stack.enter_context(patch.object(GlobalAudio, "close_stream")),
                stack.enter_context(
                    patch("audio.audio_manager.get_output_device_index", return_value=None)
                ),
                stack.enter_context(
                    patch.object(
                        mp3_decoder,
                        "decode_mp3_to_pcm",
                        side_effect=lambda data, _rate: data,
                    )
                ),
            )

    def test_split_sentences_preserves_punctuation_and_keeps_unterminated_text(self):
        self.assertEqual(
            split_sentences("첫째 문장입니다. 둘째 문장입니다! 마지막 문장"),
            ["첫째 문장입니다.", "둘째 문장입니다!", "마지막 문장"],
        )

    def test_next_sentence_synthesis_overlaps_playback_and_reuses_one_stream(self):
        provider = EdgeTTS(audio_cache=Mock())
        second_synthesis_started = threading.Event()
        third_synthesis_started = threading.Event()
        playback_count = 0
        stream = Mock()

        async def synthesize(text, emotion=None):
            del emotion
            if text.startswith("둘째"):
                second_synthesis_started.set()
            elif text.startswith("셋째"):
                third_synthesis_started.set()
            return text.encode("utf-8")

        def write(_pcm):
            nonlocal playback_count
            playback_count += 1
            next_synthesis = (
                second_synthesis_started
                if playback_count == 1
                else third_synthesis_started
            )
            if playback_count <= 2 and not next_synthesis.wait(2):
                raise AssertionError("다음 문장 합성이 현재 문장 재생과 겹치지 않았습니다")

        stream.write.side_effect = write
        with (
            self._playback_patches(stream) as playback_patches,
            patch.object(provider, "_synthesize", new=synthesize),
        ):
            open_stream, close_stream, _device_index, _decoder = playback_patches
            self.assertTrue(
                provider.speak("첫째 문장입니다. 둘째 문장입니다. 셋째 문장입니다.")
            )

        open_stream.assert_called_once()
        close_stream.assert_called_once_with(stream)
        self.assertEqual(stream.write.call_count, 3)

    def test_timed_out_sentence_is_skipped_and_later_sentence_plays(self):
        provider = EdgeTTS(synthesis_timeout_seconds=0.02, audio_cache=Mock())
        stream = Mock()

        async def synthesize(text, emotion=None):
            del emotion
            if text.startswith("느린"):
                await asyncio.sleep(0.2)
            return b"second"

        with (
            self._playback_patches(stream),
            patch.object(provider, "_synthesize", new=synthesize),
        ):
            self.assertTrue(provider.speak("느린 문장입니다. 다음 문장입니다."))

        stream.write.assert_called_once_with(b"second")

    def test_cached_wake_response_plays_without_synthesizing(self):
        text = get_wake_responses()[0]
        with tempfile.TemporaryDirectory() as cache_dir:
            cache = DiskTTSAudioCache(cache_dir)
            cache.put(
                build_tts_cache_key(
                    "edge", "ko-KR-SunHiNeural", "+0%", "+0%", "평온",
                    get_language(), text, pitch="+0Hz",
                ),
                b"cached-pcm",
            )
            provider = EdgeTTS(audio_cache=cache)
            stream = Mock()
            with (
                self._playback_patches(stream),
                patch.object(
                    provider,
                    "_synthesize",
                    side_effect=AssertionError("cache miss"),
                ) as synthesize,
            ):
                self.assertTrue(provider.speak(text))
                synthesize.assert_not_called()

        stream.write.assert_called_once_with(b"cached-pcm")

    def test_cached_ack_miss_never_synthesizes(self):
        cache = Mock()
        cache.get.return_value = None
        provider = EdgeTTS(audio_cache=cache)

        with patch.object(provider, "_synthesize") as synthesize:
            self.assertFalse(provider.speak_cached("확인하겠습니다."))

        synthesize.assert_not_called()

    def test_cached_ack_playback_stops_with_provider(self):
        provider = EdgeTTS(audio_cache=Mock())
        stream = Mock()
        stream.write.side_effect = lambda _pcm: provider.stop()

        with (
            patch.object(GlobalAudio, "open_stream", return_value=stream),
            patch.object(GlobalAudio, "close_stream") as close_stream,
            patch("audio.audio_manager.get_output_device_index", return_value=None),
        ):
            provider._audio_cache.get.return_value = b"x" * 10000
            self.assertFalse(
                provider.speak_cached(
                    "확인하겠습니다.",
                    request_cancel_event=threading.Event(),
                )
            )

        close_stream.assert_called_once_with(stream)
        stream.write.assert_called_once()

    def test_dynamic_response_is_never_written_to_cache(self):
        cache = Mock()
        cache.get.return_value = None
        provider = EdgeTTS(audio_cache=cache)
        stream = Mock()

        async def synthesize(_text, _emotion=None):
            return b"mp3"

        with (
            self._playback_patches(stream),
            patch.object(provider, "_synthesize", new=synthesize),
        ):
            self.assertTrue(provider.speak("사용자 요청에 대한 비공개 답변입니다."))

        cache.get.assert_not_called()
        cache.put.assert_not_called()

    def test_successful_speak_does_not_set_caller_stop_event(self):
        provider = EdgeTTS(audio_cache=Mock())
        stream = Mock()
        stop_event = threading.Event()

        async def synthesize(_text, _emotion=None):
            return b"mp3"

        with (
            self._playback_patches(stream),
            patch.object(provider, "_synthesize", new=synthesize),
        ):
            self.assertTrue(provider.speak("hello", stop_event=stop_event))

        self.assertFalse(stop_event.is_set())

    def test_stop_closes_reused_stream_without_writing_remaining_chunks(self):
        provider = EdgeTTS(audio_cache=Mock())
        stream = Mock()
        stream.write.side_effect = lambda _pcm: provider.stop()

        with (
            patch.object(GlobalAudio, "open_stream", return_value=stream) as open_stream,
            patch.object(GlobalAudio, "close_stream") as close_stream,
            patch("audio.audio_manager.get_output_device_index", return_value=None),
            patch.object(mp3_decoder, "decode_mp3_to_pcm", return_value=b"x" * 10000),
            patch.object(
                provider,
                "_synthesize",
                new=lambda _text, _emotion=None: _completed_audio(),
            ),
        ):
            self.assertFalse(provider.speak("중단할 문장입니다."))

        open_stream.assert_called_once()
        close_stream.assert_called_once_with(stream)
        stream.write.assert_called_once()

    def test_stop_cancels_pending_sentence_synthesis(self):
        provider = EdgeTTS(audio_cache=Mock())
        synthesis_started = threading.Event()
        synthesis_cancelled = threading.Event()
        result = []

        async def synthesize(_text, _emotion=None):
            synthesis_started.set()
            try:
                await asyncio.sleep(10)
            finally:
                synthesis_cancelled.set()

        speak_thread = threading.Thread(
            target=lambda: result.append(provider.speak("중단할 비공개 문장입니다."))
        )
        with (
            patch.object(provider, "_synthesize", new=synthesize),
            patch.object(GlobalAudio, "open_stream") as open_stream,
        ):
            speak_thread.start()
            self.assertTrue(synthesis_started.wait(1))
            provider.stop()
            speak_thread.join(2)

        self.assertFalse(speak_thread.is_alive())
        self.assertTrue(synthesis_cancelled.is_set())
        self.assertEqual(result, [False])
        open_stream.assert_not_called()


async def _completed_audio():
    return b"mp3"


if __name__ == "__main__":
    unittest.main()

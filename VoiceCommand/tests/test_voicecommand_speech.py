import unittest
import threading
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock, call, patch


from core import VoiceCommand


class VoiceCommandSpeechTests(unittest.TestCase):
    def test_recognize_speech_uses_fifteen_second_phrase_limit(self):
        recognizer = Mock()
        recognizer.listen.return_value = object()
        provider = Mock()
        provider.transcribe.return_value = "다운로드한 문서를 옮겨줘"
        signal = Mock()
        source = object()

        with patch("core.VoiceCommand.time.monotonic", return_value=1.0):
            VoiceCommand.recognize_speech_helper(
                recognizer,
                source,
                signal,
                stt_provider=provider,
                previous_texts=deque(maxlen=3),
            )

        recognizer.listen.assert_called_once_with(
            source,
            timeout=5,
            phrase_time_limit=15,
        )
        signal.emit.assert_called_once_with("다운로드한 문서를 옮겨줘")
        provider.transcribe.assert_called_once_with(
            recognizer.listen.return_value,
            mode="command",
        )

    def test_same_phrase_is_suppressed_only_before_two_seconds(self):
        recognizer = Mock()
        recognizer.listen.return_value = object()
        provider = Mock()
        provider.transcribe.return_value = "볼륨 올려줘"
        signal = Mock()
        history = deque(maxlen=3)
        times = iter([10.0, 11.99, 12.0])

        with patch("core.VoiceCommand.time.monotonic", side_effect=times):
            first_notice = VoiceCommand.recognize_speech_helper(
                recognizer, object(), signal, stt_provider=provider,
                previous_texts=history,
            )
            duplicate_notice = VoiceCommand.recognize_speech_helper(
                recognizer, object(), signal, stt_provider=provider,
                previous_texts=history,
            )
            accepted_notice = VoiceCommand.recognize_speech_helper(
                recognizer, object(), signal, stt_provider=provider,
                previous_texts=history,
            )

        self.assertIsNone(first_notice)
        self.assertTrue(duplicate_notice)
        self.assertIsNone(accepted_notice)
        self.assertEqual(
            signal.emit.call_args_list,
            [call("볼륨 올려줘"), call("볼륨 올려줘")],
        )

    def test_push_to_talk_release_ends_capture_and_restores_microphone_stream(self):
        released = threading.Event()
        stream = Mock()
        stream.read.side_effect = lambda _size: released.set() or b"audio"
        source = SimpleNamespace(
            stream=stream,
            SAMPLE_RATE=16000,
            SAMPLE_WIDTH=2,
        )
        recognizer = Mock()
        recognizer.listen.side_effect = lambda observed_source, **_kwargs: (
            observed_source.stream.read(4)
        )
        provider = Mock()
        provider.transcribe.return_value = "볼륨 올려줘"
        signal = Mock()

        with patch("core.VoiceCommand.time.monotonic", return_value=1.0):
            VoiceCommand.recognize_speech_helper(
                recognizer,
                source,
                signal,
                stt_provider=provider,
                push_to_talk_released=released,
            )

        self.assertIs(source.stream, stream)
        provider.transcribe.assert_called_once_with(bytes(8), mode="command")
        signal.emit.assert_called_once_with("볼륨 올려줘")

    def test_estimated_tts_duration_uses_current_language_rate(self):
        with (
            patch.object(VoiceCommand.translator, "get_language", return_value="en"),
            patch.object(VoiceCommand, "_tts_wake_guard_seconds", return_value=1.2),
        ):
            duration = VoiceCommand._estimate_tts_duration("x" * 240)

        self.assertEqual(duration, 12.0)


if __name__ == "__main__":
    unittest.main()

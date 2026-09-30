import base64
from io import BytesIO
import os
import struct
import tempfile
import threading
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec, patch

from openai.resources.audio.speech import Speech

from audio.audio_manager import GlobalAudio
from tts.tts_openai_compat import OpenAICompatTTS, _MAX_REFERENCE_BYTES, _parse_wav


def _wav_bytes(channels, sample_rate, sample_width, frames):
    output = BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(frames)
    return output.getvalue()


class OpenAICompatTTSTests(unittest.TestCase):
    def _make_provider(self, **kwargs):
        # 실제 SDK 시그니처를 따르게 해서 필수 인자 누락을 잡는다.
        speech = create_autospec(Speech, instance=True)
        speech.create.return_value = SimpleNamespace(
            content=_wav_bytes(1, 24000, 2, struct.pack("<hh", 10, -20))
        )
        client = SimpleNamespace(audio=SimpleNamespace(speech=speech))
        openai_module = SimpleNamespace(OpenAI=Mock(return_value=client))
        with patch("tts.tts_openai_compat.importlib.import_module", return_value=openai_module):
            provider = OpenAICompatTTS(base_url="http://127.0.0.1:8880/v1", **kwargs)
        return provider, openai_module.OpenAI, speech.create

    def _speak_with_mock_audio(self, provider):
        stream = Mock()
        with (
            patch.object(GlobalAudio, "open_stream", return_value=stream),
            patch.object(GlobalAudio, "close_stream"),
            patch("audio.audio_manager.get_output_device_index", return_value=None),
            patch("tts.tts_openai_compat.write_pcm_chunks", return_value=True),
        ):
            return provider.speak("hello", "happy")

    def test_missing_base_url_raises_value_error(self):
        with self.assertRaises(ValueError):
            OpenAICompatTTS()

    def test_sdk_uses_local_compatible_url_and_no_retries(self):
        _provider, openai_factory, _create = self._make_provider(api_key="")

        openai_factory.assert_called_once_with(
            base_url="http://127.0.0.1:8880/v1",
            api_key="not-needed",
            max_retries=0,
            timeout=30,
        )

    def test_clone_mode_sends_reference_audio_fields(self):
        wav = _wav_bytes(1, 16000, 2, struct.pack("<h", 1))
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as reference:
            reference.write(wav)
            reference_path = reference.name
        try:
            provider, _factory, create = self._make_provider(
                clone_mode="ref_audio",
                reference_wav=reference_path,
                reference_text="reference words",
                emotion_mode="none",
            )
            self.assertTrue(self._speak_with_mock_audio(provider))
        finally:
            os.unlink(reference_path)

        options = create.call_args.kwargs
        self.assertIn("voice", options)
        self.assertEqual(
            options["extra_body"],
            {
                "ref_audio": "data:audio/wav;base64," + base64.b64encode(wav).decode("ascii"),
                "ref_text": "reference words",
                "task_type": "Base",
            },
        )

    def test_clone_none_uses_voice_without_extra_body(self):
        provider, _factory, create = self._make_provider(
            voice="alloy", clone_mode="none", emotion_mode="none"
        )

        self.assertTrue(self._speak_with_mock_audio(provider))

        options = create.call_args.kwargs
        self.assertEqual(options["voice"], "alloy")
        self.assertNotIn("extra_body", options)

    def test_instructions_mode_sends_emotion_instruction(self):
        provider, _factory, create = self._make_provider(language="ko")
        with (
            patch(
                "tts.tts_openai_compat.get_emotion_instruction",
                return_value="Speak cheerfully.",
            ) as instruction,
        ):
            self.assertTrue(self._speak_with_mock_audio(provider))

        instruction.assert_called_once_with("happy", "ko")
        self.assertEqual(create.call_args.kwargs["instructions"], "Speak cheerfully.")

    def test_emotion_none_omits_instructions(self):
        provider, _factory, create = self._make_provider(emotion_mode="none")

        self.assertTrue(self._speak_with_mock_audio(provider))

        self.assertNotIn("instructions", create.call_args.kwargs)

    def test_request_failure_logs_detail_without_api_key_and_ignores_cancel(self):
        provider, _factory, create = self._make_provider(api_key="secret-key")
        create.side_effect = RuntimeError("401 unauthorized secret-key")

        with patch("tts.tts_openai_compat.logging.error") as log_error:
            self.assertFalse(provider.speak("hello"))

        detail = log_error.call_args.args[1]
        self.assertIn("401 unauthorized", detail)
        self.assertNotIn("secret-key", detail)

        cancelled, _factory, create = self._make_provider(api_key="secret-key")
        stop_event = threading.Event()

        def cancel_then_fail(**_kwargs):
            stop_event.set()
            raise RuntimeError("request closed")

        create.side_effect = cancel_then_fail
        with patch("tts.tts_openai_compat.logging.error") as log_error:
            self.assertFalse(cancelled.speak("hello", stop_event=stop_event))

        log_error.assert_not_called()

    def test_reference_over_five_mib_fails_before_request(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as reference:
            reference.seek(_MAX_REFERENCE_BYTES)
            reference.write(b"x")
            reference_path = reference.name
        try:
            provider, _factory, create = self._make_provider(
                clone_mode="ref_audio", reference_wav=reference_path
            )
            self.assertFalse(provider.speak("hello"))
        finally:
            os.unlink(reference_path)

        create.assert_not_called()

    def test_wav_parser_preserves_mono_and_sample_rate(self):
        wav = _wav_bytes(1, 32000, 2, struct.pack("<hh", 100, -200))

        sample_rate, pcm = _parse_wav(wav)

        self.assertEqual(sample_rate, 32000)
        self.assertEqual(pcm, struct.pack("<hh", 100, -200))

    def test_wav_parser_averages_stereo_channels(self):
        wav = _wav_bytes(2, 44100, 2, struct.pack("<hhhh", 1000, -2000, 32767, -32768))

        sample_rate, pcm = _parse_wav(wav)

        self.assertEqual(sample_rate, 44100)
        self.assertEqual(pcm, struct.pack("<hh", -500, 0))

    def test_wav_parser_rejects_non_int16_samples(self):
        wav = _wav_bytes(1, 24000, 1, b"\x80")

        with self.assertRaises(ValueError):
            _parse_wav(wav)

        provider, _factory, create = self._make_provider(emotion_mode="none")
        provider._client.audio.speech.create.return_value.content = wav
        self.assertFalse(provider.speak("hello"))
        create.assert_called_once()


if __name__ == "__main__":
    unittest.main()

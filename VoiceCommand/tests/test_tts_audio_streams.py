import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from audio import mp3_decoder
from audio.audio_manager import GlobalAudio
from tts.tts_edge import EdgeTTS
from tts.tts_elevenlabs import ElevenLabsTTS
from tts.tts_openai import OpenAITTS


class TTSStreamWrapperTests(unittest.TestCase):
    def test_edge_tts_forwards_shared_volume_to_pcm_writer(self):
        provider = EdgeTTS(tts_volume=0.5, audio_cache=Mock())
        stream = Mock()
        stop_event = threading.Event()

        with patch("tts.tts_edge.write_pcm_chunks", return_value=True) as write:
            self.assertTrue(
                provider._write_pcm_chunks(
                    stream, b"\x01\x00", stop_event, volume=provider.tts_volume
                )
            )

        write.assert_called_once_with(
            stream, b"\x01\x00", stop_event, 22050, volume=0.5
        )

    def _assert_wrappers_close_after_write_failure(self, speak):
        stream = Mock()
        stream.write.side_effect = OSError("output stream failed")

        with (
            patch.object(GlobalAudio, "open_stream", return_value=stream) as open_stream,
            patch.object(GlobalAudio, "close_stream") as close_stream,
        ):
            self.assertFalse(speak())

        open_stream.assert_called_once()
        close_stream.assert_called_once_with(stream)

    def test_edge_tts_uses_shared_stream_wrappers(self):
        provider = EdgeTTS()

        async def synthesize(_text, _emotion=None):
            return b"mp3"

        with (
            patch.dict(sys.modules, {"edge_tts": SimpleNamespace()}),
            patch.object(provider, "_synthesize", new=synthesize),
            patch.object(mp3_decoder, "decode_mp3_to_pcm", return_value=b"pcm"),
            patch("audio.audio_manager.get_output_device_index", return_value=None),
        ):
            self._assert_wrappers_close_after_write_failure(
                lambda: provider.speak("hello")
            )

    def test_openai_tts_uses_shared_stream_wrappers(self):
        client = SimpleNamespace(
            audio=SimpleNamespace(
                speech=SimpleNamespace(
                    create=Mock(return_value=SimpleNamespace(content=b"pcm"))
                )
            )
        )
        openai_module = SimpleNamespace(OpenAI=lambda **_kwargs: client)
        with patch("tts.tts_openai.importlib.import_module", return_value=openai_module):
            provider = OpenAITTS(api_key="test-key")

        with patch("audio.audio_manager.get_output_device_index", return_value=None):
            self._assert_wrappers_close_after_write_failure(
                lambda: provider.speak("hello")
            )

    def test_openai_tts_redacts_api_key_from_error_log(self):
        secret = "openai-test-secret"  # nosec B105
        client = SimpleNamespace(
            audio=SimpleNamespace(
                speech=SimpleNamespace(
                    create=Mock(side_effect=RuntimeError(f"failed with {secret}"))
                )
            )
        )
        openai_module = SimpleNamespace(OpenAI=lambda **_kwargs: client)
        with patch("tts.tts_openai.importlib.import_module", return_value=openai_module):
            provider = OpenAITTS(api_key=secret)

        with self.assertLogs(level="ERROR") as captured:
            self.assertFalse(provider.speak("hello"))

        self.assertNotIn(secret, "\n".join(captured.output))
        self.assertIn("[redacted]", "\n".join(captured.output))

    def test_elevenlabs_tts_uses_shared_stream_wrappers(self):
        provider = ElevenLabsTTS(api_key="test-key")
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers = {"Content-Type": "audio/pcm"}
        response.iter_content.return_value = [b"\x00\x00"]
        session = Mock()
        session.post.return_value = response
        provider._get_session = lambda: session

        with patch("audio.audio_manager.get_output_device_index", return_value=None):
            self._assert_wrappers_close_after_write_failure(
                lambda: provider.speak("hello")
            )


if __name__ == "__main__":
    unittest.main()

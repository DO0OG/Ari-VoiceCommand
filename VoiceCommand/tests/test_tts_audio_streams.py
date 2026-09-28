import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from audio import mp3_decoder
from audio.audio_manager import GlobalAudio
from tts.tts_edge import EdgeTTS
from tts.tts_elevenlabs import ElevenLabsTTS
from tts.tts_openai import OpenAITTS


class TTSStreamWrapperTests(unittest.TestCase):
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

    def test_elevenlabs_tts_uses_shared_stream_wrappers(self):
        provider = ElevenLabsTTS(api_key="test-key")
        response = MagicMock()
        response.__enter__.return_value = response
        response.iter_content.return_value = [b"mp3"]
        session = Mock()
        session.post.return_value = response
        provider._get_session = lambda: session

        with (
            patch.object(mp3_decoder, "decode_mp3_to_pcm", return_value=b"pcm"),
            patch("audio.audio_manager.get_output_device_index", return_value=None),
        ):
            self._assert_wrappers_close_after_write_failure(
                lambda: provider.speak("hello")
            )


if __name__ == "__main__":
    unittest.main()

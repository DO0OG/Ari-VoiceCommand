import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from audio.audio_manager import GlobalAudio
from tts.tts_openai import OpenAITTS


class OpenAICustomVoiceTests(unittest.TestCase):
    def test_custom_voice_id_uses_openai_voice_object(self):
        speech = SimpleNamespace(
            create=Mock(return_value=SimpleNamespace(content=b"pcm"))
        )
        client = SimpleNamespace(audio=SimpleNamespace(speech=speech))
        openai_module = SimpleNamespace(OpenAI=Mock(return_value=client))
        stream = Mock()

        # import_module 대역은 다른 patch 대상 해석에도 쓰이므로 마지막에 건다.
        with (
            patch("audio.audio_manager.get_output_device_index", return_value=None),
            patch.object(GlobalAudio, "open_stream", return_value=stream),
            patch.object(GlobalAudio, "close_stream"),
            patch("tts.tts_openai.write_pcm_chunks", return_value=True),
            patch("tts.tts_openai.importlib.import_module", return_value=openai_module),
        ):
            provider = OpenAITTS(api_key="test-key", custom_voice_id="voice_custom")
            self.assertTrue(provider.speak("hello"))

        self.assertEqual(speech.create.call_args.kwargs["voice"], {"id": "voice_custom"})


if __name__ == "__main__":
    unittest.main()

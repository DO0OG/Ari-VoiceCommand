import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from audio.audio_manager import GlobalAudio
from core.emotions import EMOTION_CATALOG, EMOTION_NAMES, get_emotion_instruction
from core.rp_generator import RPGenerator
from tts.tts_edge import EdgeTTS
from tts.tts_elevenlabs import ElevenLabsTTS
from tts.tts_openai import OpenAITTS


class EmotionCatalogTests(unittest.TestCase):
    def test_prompt_uses_canonical_korean_tags_for_every_language(self):
        expected = " ".join(f"({name})" for name in EMOTION_NAMES)

        for language in ("ko", "en", "ja"):
            with self.subTest(language=language):
                self.assertIn(expected, get_emotion_instruction(language))
        self.assertEqual(len(EMOTION_NAMES), 9)

    def test_saved_template_instruction_is_replaced_by_catalog_prompt(self):
        old_prompt = "안내\n모든 답변 첫머리에 감정 태그를 붙이세요: (태그)\n계속"
        with patch("i18n.translator.get_language", return_value="ko"):
            prompt = RPGenerator().build_system_prompt(old_prompt)

        self.assertNotIn("모든 답변 첫머리에 감정 태그를 붙이세요:", prompt)
        self.assertIn(get_emotion_instruction("ko"), prompt)


class EdgeEmotionProsodyTests(unittest.TestCase):
    def test_rate_offsets_clamp_to_edge_supported_range(self):
        fast = EdgeTTS(rate="+98%")
        slow = EdgeTTS(rate="-49%")

        self.assertEqual(fast._prosody("기쁨"), ("+100%", "+3Hz"))
        self.assertEqual(slow._prosody("슬픔"), ("-50%", "-2Hz"))

    def test_disabled_offsets_keep_user_rate_and_zero_pitch(self):
        provider = EdgeTTS(rate="-45%", emotion_enabled=False)

        self.assertEqual(provider._prosody("기쁨"), ("-45%", "+0Hz"))

    def test_synthesis_passes_emotion_rate_and_pitch_to_edge(self):
        calls = []

        class FakeCommunicate:
            def __init__(self, text, voice, **options):
                calls.append((text, voice, options))

            async def stream(self):
                yield {"type": "audio", "data": b"audio"}

        provider = EdgeTTS(rate="+98%")
        with patch.dict("sys.modules", {"edge_tts": SimpleNamespace(Communicate=FakeCommunicate)}):
            audio = asyncio.run(provider._synthesize("hello", "기쁨"))

        self.assertEqual(audio, b"audio")
        self.assertEqual(calls[0][2]["rate"], "+100%")
        self.assertEqual(calls[0][2]["pitch"], "+3Hz")


class OpenAIEmotionProsodyTests(unittest.TestCase):
    def _speak(self, model, emotion, emotion_enabled=True):
        client = SimpleNamespace(
            audio=SimpleNamespace(speech=SimpleNamespace(create=Mock(
                return_value=SimpleNamespace(content=b"pcm")
            )))
        )
        openai_module = SimpleNamespace(OpenAI=Mock(return_value=client))
        stream = Mock()
        # patch()도 대상 모듈을 import_module로 찾으므로 import_module 교체보다 먼저 건다.
        with (
            patch("audio.audio_manager.get_output_device_index", return_value=None),
            patch.object(GlobalAudio, "open_stream", return_value=stream),
            patch.object(GlobalAudio, "close_stream"),
            patch("tts.tts_openai.importlib.import_module", return_value=openai_module),
        ):
            provider = OpenAITTS(
                api_key="test-key", model=model, emotion_enabled=emotion_enabled
            )
            self.assertTrue(provider.speak("hello", emotion))
        return client.audio.speech.create.call_args.kwargs

    def test_supported_model_gets_instructions_and_legacy_model_ignores_them(self):
        supported = self._speak("gpt-4o-mini-tts", "기쁨")
        legacy = self._speak("tts-1", "기쁨")
        disabled = self._speak("gpt-4o-mini-tts", "기쁨", emotion_enabled=False)

        self.assertEqual(
            supported["instructions"],
            EMOTION_CATALOG["기쁨"]["openai"],
        )
        self.assertNotIn("instructions", legacy)
        self.assertNotIn("instructions", disabled)


class ElevenLabsEmotionProsodyTests(unittest.TestCase):
    def test_settings_offsets_are_small_clamped_and_disableable(self):
        enabled = ElevenLabsTTS(stability=0.98)
        disabled = ElevenLabsTTS(stability=0.98, emotion_enabled=False)

        self.assertAlmostEqual(enabled._voice_settings("기쁨")["stability"], 0.93)
        self.assertAlmostEqual(enabled._voice_settings("기쁨")["style"], 0.08)
        self.assertAlmostEqual(disabled._voice_settings("기쁨")["stability"], 0.98)
        self.assertAlmostEqual(disabled._voice_settings("기쁨")["style"], 0.0)
        self.assertAlmostEqual(enabled._voice_settings("걱정")["stability"], 1.0)


    def test_negative_style_offset_is_represented_by_a_small_valid_adjustment(self):
        provider = ElevenLabsTTS()

        self.assertEqual(provider._voice_settings("worried")["style"], 0.02)


if __name__ == "__main__":
    unittest.main()

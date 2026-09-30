import unittest
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch


from tts import tts_openai
from tts.tts_factory import build_tts_signature, create_tts_provider


class TTSFactoryTests(unittest.TestCase):
    def test_new_provider_settings_are_in_tts_signature(self):
        base = {"tts_mode": "openai_compat_tts"}
        for key, value in (
            ("cosyvoice_dir", "C:/CosyVoice"),
            ("tts_volume", 0.5),
            ("tts_reference_wav", "C:/voice.wav"),
            ("openai_compat_tts_base_url", "http://127.0.0.1:8880/v1"),
            ("openai_compat_tts_api_key", "secret"),
            ("openai_compat_tts_model", "model"),
            ("openai_compat_tts_voice", "voice"),
            ("openai_compat_tts_clone_mode", "ref_audio"),
            ("openai_compat_tts_emotion_mode", "none"),
            ("openai_tts_custom_voice_id", "voice_custom"),
            ("elevenlabs_model_id", "eleven_v3"),
        ):
            with self.subTest(key=key):
                self.assertNotEqual(
                    build_tts_signature(base), build_tts_signature({**base, key: value})
                )

    def test_tts_signature_changes_only_with_tts_related_fields(self):
        base = {
            "tts_mode": "fish",
            "fish_api_key": "a",
            "fish_reference_id": "b",
            "personality": "x",
        }
        same = dict(base, personality="y")
        changed = dict(base, fish_reference_id="c")

        self.assertEqual(build_tts_signature(base), build_tts_signature(same))
        self.assertNotEqual(build_tts_signature(base), build_tts_signature(changed))

    def test_emotion_setting_is_part_of_the_tts_signature(self):
        enabled = {"tts_mode": "edge", "tts_emotion_enabled": True}
        disabled = {"tts_mode": "edge", "tts_emotion_enabled": False}

        self.assertNotEqual(build_tts_signature(enabled), build_tts_signature(disabled))

    def test_edge_provider_receives_emotion_setting(self):
        with patch("tts.tts_edge.EdgeTTS") as edge_tts:
            provider, mode = create_tts_provider(
                {
                    "tts_mode": "edge",
                    "tts_emotion_enabled": False,
                    "tts_volume": 0.5,
                }
            )

        self.assertIs(provider, edge_tts.return_value)
        self.assertEqual(mode, "edge")
        edge_tts.assert_called_once_with(
            voice="ko-KR-SunHiNeural",
            rate="+0%",
            emotion_enabled=False,
            synthesis_timeout_seconds=10,
            cache_max_bytes=50 * 1024 * 1024,
            tts_volume=0.5,
        )

    def test_openai_client_initialization_failure_falls_back_to_edge(self):
        edge_provider = object()

        class FakeEdgeTTS:
            def __new__(cls, **_kwargs):
                return edge_provider

        with (
            patch.object(
                tts_openai,
                "importlib",
                SimpleNamespace(import_module=Mock(side_effect=ImportError("missing sdk"))),
            ),
            patch("tts.tts_openai.GlobalAudio.get_instance") as audio,
            patch.dict(sys.modules, {"tts.tts_edge": SimpleNamespace(EdgeTTS=FakeEdgeTTS)}),
        ):
            provider, mode = create_tts_provider(
                {
                    "tts_mode": "openai_tts",
                    "openai_tts_api_key": "test-key",
                    "edge_tts_voice": "ko-KR-SunHiNeural",
                }
            )

        self.assertIs(provider, edge_provider)
        self.assertEqual(mode, "edge")
        audio.assert_not_called()

    def test_openai_compat_provider_receives_shared_reference_and_language(self):
        provider = object()
        settings = {
            "tts_mode": "openai_compat_tts",
            "openai_compat_tts_base_url": "http://127.0.0.1:8880/v1",
            "openai_compat_tts_clone_mode": "ref_audio",
        }
        with (
            patch("tts.voice_reference.get_reference_wav", return_value="reference.wav"),
            patch("tts.voice_reference.get_reference_text", return_value="reference text"),
            patch("tts.tts_openai_compat.OpenAICompatTTS", return_value=provider) as constructor,
            patch("i18n.translator.get_language", return_value="ja"),
        ):
            result, mode = create_tts_provider(settings)

        self.assertIs(result, provider)
        self.assertEqual(mode, "openai_compat_tts")
        self.assertEqual(constructor.call_args.kwargs["reference_wav"], "reference.wav")
        self.assertEqual(constructor.call_args.kwargs["reference_text"], "reference text")
        self.assertEqual(constructor.call_args.kwargs["language"], "ja")

    def test_pcm_provider_factories_forward_shared_volume(self):
        volume = 0.5
        with (
            patch("tts.tts_openai_compat.OpenAICompatTTS") as compat,
            patch("tts.voice_reference.get_reference_wav", return_value=""),
            patch("tts.voice_reference.get_reference_text", return_value=""),
            patch("i18n.translator.get_language", return_value="ko"),
        ):
            create_tts_provider(
                {"tts_mode": "openai_compat_tts", "tts_volume": volume}
            )
        self.assertEqual(compat.call_args.kwargs["tts_volume"], volume)

        with patch("tts.tts_openai.OpenAITTS") as openai:
            create_tts_provider({"tts_mode": "openai_tts", "tts_volume": volume})
        self.assertEqual(openai.call_args.kwargs["tts_volume"], volume)

        with patch("tts.tts_elevenlabs.ElevenLabsTTS") as elevenlabs:
            create_tts_provider({"tts_mode": "elevenlabs", "tts_volume": volume})
        self.assertEqual(elevenlabs.call_args.kwargs["tts_volume"], volume)

        with patch("tts.fish_tts_ws.FishTTSWebSocket") as fish:
            create_tts_provider(
                {"tts_mode": "fish", "fish_api_key": "key", "tts_volume": volume}
            )
        self.assertEqual(fish.call_args.kwargs["tts_volume"], volume)


if __name__ == "__main__":
    unittest.main()

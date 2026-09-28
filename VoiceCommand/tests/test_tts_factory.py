import unittest
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch


from tts import tts_openai
from tts.tts_factory import build_tts_signature, create_tts_provider


class TTSFactoryTests(unittest.TestCase):
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
                {"tts_mode": "edge", "tts_emotion_enabled": False}
            )

        self.assertIs(provider, edge_tts.return_value)
        self.assertEqual(mode, "edge")
        edge_tts.assert_called_once_with(
            voice="ko-KR-SunHiNeural",
            rate="+0%",
            emotion_enabled=False,
            synthesis_timeout_seconds=10,
            cache_max_bytes=50 * 1024 * 1024,
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


if __name__ == "__main__":
    unittest.main()

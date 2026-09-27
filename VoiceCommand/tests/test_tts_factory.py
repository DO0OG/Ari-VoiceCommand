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
            patch("tts.tts_openai.pyaudio.PyAudio") as audio,
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

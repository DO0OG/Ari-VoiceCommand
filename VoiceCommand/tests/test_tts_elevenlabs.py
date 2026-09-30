import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from tts.tts_elevenlabs import (
    ElevenLabsTTS,
    create_voice_clone,
    fetch_models,
    fetch_voices,
)


class ElevenLabsProviderTests(unittest.TestCase):
    def test_missing_api_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "API key is missing"):
            ElevenLabsTTS()

    def test_v3_and_v4_use_tags_instead_of_legacy_voice_settings(self):
        for model_id in ("eleven_v3", "eleven_v4-preview"):
            with self.subTest(model_id=model_id):
                provider = ElevenLabsTTS(api_key="test-key", model_id=model_id)
                with patch(
                    "tts.tts_elevenlabs.get_emotion_details",
                    return_value={"elevenlabs_tag": "[happy]"},
                ):
                    payload = provider._speech_payload("Hello", "기쁨")

                self.assertEqual(payload["text"], "[happy] Hello")
                self.assertNotIn("voice_settings", payload)

    def test_empty_v3_tag_leaves_text_without_a_prefix(self):
        provider = ElevenLabsTTS(api_key="test-key", model_id="eleven_v3")
        with patch(
            "tts.tts_elevenlabs.get_emotion_details",
            return_value={"elevenlabs_tag": ""},
        ):
            payload = provider._speech_payload("Hello", "평온")

        self.assertEqual(payload["text"], "Hello")

    def test_non_v3_model_keeps_legacy_emotion_offsets(self):
        provider = ElevenLabsTTS(api_key="test-key", model_id="eleven_multilingual_v2")

        payload = provider._speech_payload("Hello", "기쁨")

        self.assertEqual(payload["text"], "Hello")
        self.assertEqual(payload["voice_settings"]["style"], 0.08)
        self.assertAlmostEqual(payload["voice_settings"]["stability"], 0.45)


class ElevenLabsSettingsApiTests(unittest.TestCase):
    def _response(self, body):
        response = Mock()
        response.json.return_value = body
        response.status_code = 200
        return response

    def test_model_loader_filters_non_tts_models(self):
        response = self._response([
            {"model_id": "eleven_v3", "name": "V3", "can_do_text_to_speech": True},
            {"model_id": "music", "name": "Music", "can_do_text_to_speech": False},
        ])
        with patch("requests.get", return_value=response) as get:
            models = fetch_models("test-key")

        self.assertEqual(models, [{"model_id": "eleven_v3", "name": "V3"}])
        self.assertEqual(get.call_args.kwargs["timeout"], (10, 30))

    def test_voice_loader_follows_next_page_token(self):
        first = self._response({
            "voices": [{"voice_id": "one", "name": "First"}],
            "has_more": True,
            "next_page_token": "next-token",
        })
        second = self._response({
            "voices": [{"voice_id": "two", "name": "Second"}],
            "has_more": False,
            "next_page_token": None,
        })
        with patch("requests.get", side_effect=[first, second]) as get:
            voices = fetch_voices("test-key")

        self.assertEqual(
            voices,
            [
                {"voice_id": "one", "name": "First"},
                {"voice_id": "two", "name": "Second"},
            ],
        )
        self.assertEqual(get.call_count, 2)
        self.assertEqual(
            get.call_args_list[1].kwargs["params"]["next_page_token"],
            "next-token",
        )

    def test_clone_upload_uses_multipart_file_and_name_fields(self):
        response = self._response({"voice_id": "cloned-voice"})
        with tempfile.TemporaryDirectory() as directory:
            wav_path = Path(directory) / "reference.wav"
            wav_path.write_bytes(b"wav-data")
            with patch("requests.post", return_value=response) as post:
                voice_id = create_voice_clone("test-key", str(wav_path), "My Voice")

        self.assertEqual(voice_id, "cloned-voice")
        self.assertEqual(post.call_args.kwargs["data"], {"name": "My Voice"})
        uploaded = post.call_args.kwargs["files"]["files"]
        self.assertEqual(uploaded[0], "reference.wav")
        self.assertEqual(uploaded[2], "audio/wav")
        self.assertEqual(post.call_args.kwargs["timeout"], (10, 60))

    def test_clone_error_includes_server_detail_without_api_key(self):
        response = Mock()
        response.status_code = 403
        response.text = "denied: private-key"
        response.raise_for_status.side_effect = requests.HTTPError("request failed")
        with tempfile.TemporaryDirectory() as directory:
            wav_path = Path(directory) / "reference.wav"
            wav_path.write_bytes(b"wav-data")
            with patch("requests.post", return_value=response):
                with self.assertRaises(RuntimeError) as raised:
                    create_voice_clone("private-key", str(wav_path), "My Voice")

        self.assertIn("denied", str(raised.exception))
        self.assertNotIn("private-key", str(raised.exception))


if __name__ == "__main__":
    unittest.main()

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from PySide6.QtCore import Qt

from audio.audio_manager import GlobalAudio
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

    def test_speak_streams_pcm_before_download_finishes(self):
        provider = ElevenLabsTTS(api_key="test-key")
        writes = []

        class _FakeAudioStream:
            def write(self, data):
                writes.append(data)

        class _FakeResponse:
            complete = False
            first_write_before_complete = False
            headers = {"Content-Type": "audio/pcm"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.closed = True

            def close(self):
                self.closed = True

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                self.chunk_size = chunk_size
                yield b"\x01"
                yield b"\x02\x03"
                self.first_write_before_complete = bool(writes) and not self.complete
                yield b"\x04"
                self.complete = True

        response = _FakeResponse()
        session = Mock()
        session.post.return_value = response
        provider._get_session = lambda: session
        finished = []
        provider.playback_finished.connect(lambda: finished.append(True))

        with (
            patch.object(
                GlobalAudio, "open_stream", return_value=_FakeAudioStream()
            ) as open_stream,
            patch.object(GlobalAudio, "close_stream") as close_stream,
            patch("audio.audio_manager.get_output_device_index", return_value=0),
        ):
            self.assertTrue(provider.speak("hello"))

        self.assertEqual(b"".join(writes), b"\x01\x02\x03\x04")
        self.assertTrue(response.first_write_before_complete)
        self.assertEqual(response.chunk_size, 1024)
        self.assertTrue(response.closed)
        self.assertFalse(provider.is_playing)
        self.assertEqual(finished, [True])
        self.assertTrue(session.post.call_args.args[0].endswith("/stream"))
        self.assertEqual(
            session.post.call_args.kwargs["params"],
            {"output_format": "pcm_24000"},
        )
        self.assertNotIn("Accept", session.post.call_args.kwargs["headers"])
        self.assertEqual(open_stream.call_args.kwargs["rate"], 24000)
        close_stream.assert_called_once()

    def test_speak_rejects_non_audio_success_response(self):
        provider = ElevenLabsTTS(api_key="test-key")

        class _FakeResponse:
            headers = {"Content-Type": "text/html; charset=utf-8"}

            def __init__(self):
                self.closed = False

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                return iter([b"<html>not audio</html>"])

            def close(self):
                self.closed = True

        response = _FakeResponse()
        session = Mock()
        session.post.return_value = response
        provider._get_session = lambda: session

        with patch.object(GlobalAudio, "open_stream") as open_stream:
            self.assertFalse(provider.speak("hello"))

        self.assertTrue(response.closed)
        open_stream.assert_not_called()
        self.assertFalse(provider.is_playing)

    def test_cleanup_cancels_active_response_and_playback(self):
        provider = ElevenLabsTTS(api_key="test-key")
        response_closed = threading.Event()
        response_reading = threading.Event()

        class _FakeAudioStream:
            def write(self, _data):
                return None

        class _FakeResponse:
            headers = {"Content-Type": "audio/pcm"}

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                response_reading.set()
                response_closed.wait(timeout=2)
                return iter(())

            def close(self):
                response_closed.set()

        response = _FakeResponse()
        session = Mock()
        session.post.return_value = response
        provider._get_session = lambda: session
        finished = []
        provider.playback_finished.connect(
            lambda: finished.append(True), Qt.ConnectionType.DirectConnection
        )
        with (
            patch.object(GlobalAudio, "open_stream", return_value=_FakeAudioStream()),
            patch.object(GlobalAudio, "close_stream"),
            patch("audio.audio_manager.get_output_device_index", return_value=0),
        ):
            worker = threading.Thread(target=lambda: provider.speak("hello"))
            worker.start()
            self.assertTrue(response_reading.wait(timeout=2))
            active_stop_event = provider._active_stop_event
            provider.cleanup()
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertTrue(active_stop_event.is_set())
        self.assertTrue(response_closed.is_set())
        self.assertFalse(provider.is_playing)
        self.assertEqual(finished, [True])


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
            "next_page_token": "next-token",  # nosec B105
        })
        second = self._response({
            "voices": [{"voice_id": "two", "name": "Second"}],
            "has_more": False,
            "next_page_token": None,  # nosec B105
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

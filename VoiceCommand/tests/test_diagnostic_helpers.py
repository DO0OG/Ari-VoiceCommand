import struct
import unittest
from unittest.mock import patch

from audio.audio_manager import get_configured_output_device_name, output_device_override
from ui.diagnostic_helpers import (
    pcm_level_percent,
    resolve_input_device_index,
    run_tts_diagnostic,
    transcribe_diagnostic_sample,
)


class _Provider:
    def __init__(self, result=True):
        self.result = result
        self.spoken = []
        self.cleaned = False
        self.device_during_speak = None

    def speak(self, sentence):
        self.spoken.append(sentence)
        self.device_during_speak = get_configured_output_device_name()
        return self.result

    def cleanup(self):
        self.cleaned = True


class DiagnosticHelperTests(unittest.TestCase):
    def test_pcm_level_percent_scales_rms(self):
        self.assertEqual(pcm_level_percent(b""), 0)
        self.assertEqual(pcm_level_percent(struct.pack("<4h", 0, 0, 0, 0)), 0)
        self.assertEqual(pcm_level_percent(struct.pack("<2h", 32767, -32768)), 100)

    def test_resolve_input_device_index_matches_input_devices_only(self):
        devices = [
            {"name": "Mic A", "maxInputChannels": 0},
            {"name": "Mic  A", "maxInputChannels": 1},
        ]
        self.assertIsNone(resolve_input_device_index("", devices))
        self.assertEqual(resolve_input_device_index("mic a", devices), 1)
        with self.assertRaises(ValueError):
            resolve_input_device_index("Missing", devices)

    def test_tts_diagnostic_uses_selected_output_device_and_cleans_up(self):
        provider = _Provider()
        with patch("core.config_manager.ConfigManager.get", return_value="Saved Speaker"):
            ok, _message = run_tts_diagnostic(
                {}, "edge", "Selected Speaker", "hello", provider_factory=lambda _s: (provider, "edge")
            )
            self.assertEqual(get_configured_output_device_name(), "Saved Speaker")

        self.assertTrue(ok)
        self.assertEqual(provider.spoken, ["hello"])
        self.assertEqual(provider.device_during_speak, "Selected Speaker")
        self.assertTrue(provider.cleaned)

    def test_tts_diagnostic_fails_when_provider_falls_back_or_speak_fails(self):
        fallback = _Provider()
        ok, _message = run_tts_diagnostic(
            {}, "openai_tts", "", "hello", provider_factory=lambda _s: (fallback, "edge")
        )
        self.assertFalse(ok)
        self.assertEqual(fallback.spoken, [])
        self.assertTrue(fallback.cleaned)

        failing = _Provider(result=False)
        ok, _message = run_tts_diagnostic(
            {}, "edge", "", "hello", provider_factory=lambda _s: (failing, "edge")
        )
        self.assertFalse(ok)

    def test_transcribe_diagnostic_sample_reports_text_or_empty_result(self):
        class _STT:
            def __init__(self, text):
                self.text = text

            def transcribe(self, _audio):
                return self.text

        ok, message = transcribe_diagnostic_sample(b"audio", {}, provider_factory=lambda _s: _STT(" 안녕 "))
        self.assertTrue(ok)
        self.assertIn("안녕", message)
        ok, _message = transcribe_diagnostic_sample(b"audio", {}, provider_factory=lambda _s: _STT(""))
        self.assertFalse(ok)

    def test_output_device_override_is_restored(self):
        with output_device_override("Outer"):
            with output_device_override("Inner"):
                self.assertEqual(get_configured_output_device_name(), "Inner")
            self.assertEqual(get_configured_output_device_name(), "Outer")


if __name__ == "__main__":
    unittest.main()

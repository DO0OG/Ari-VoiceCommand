import math
import struct
import unittest
from unittest.mock import patch

import speech_recognition as sr


from audio.simple_wake import SimpleWakeWord, should_transcribe_wake_audio


def _audio_from_envelope(envelope):
    sample_rate = 16000
    frame_samples = sample_rate // 50
    raw_data = bytearray()
    for frame_index, level in enumerate(envelope):
        for sample_index in range(frame_samples):
            position = frame_index * frame_samples + sample_index
            phase = 2 * math.pi * 220 * position / sample_rate
            sample = int(12000 * level * math.sin(phase))
            raw_data.extend(struct.pack("<h", sample))
    return sr.AudioData(bytes(raw_data), sample_rate, 2)


class _FakeSttProvider:
    def is_healthy(self):
        return True

    def transcribe(self, _audio):
        return "아리야"


class SimpleWakeWordTests(unittest.TestCase):
    def _make_detector(self):
        settings = {
            "wake_words": ["아리야", "시작"],
            "stt_energy_threshold": 300,
            "stt_dynamic_energy": True,
            "stt_provider": "google",
            "whisper_model": "small",
            "whisper_device": "auto",
            "whisper_compute_type": "int8",
        }
        with patch("audio.simple_wake.ConfigManager.load_settings", return_value=settings):
            with patch("audio.simple_wake.create_stt_provider", return_value=_FakeSttProvider()):
                return SimpleWakeWord()

    def test_matches_exact_wake_word_even_with_punctuation(self):
        detector = self._make_detector()

        self.assertTrue(detector._matches_wake_word("아리야!", "아리야"))
        self.assertTrue(detector._matches_wake_word(" 시작... ", "시작"))

    def test_does_not_match_generic_word_inside_longer_sentence(self):
        detector = self._make_detector()

        self.assertFalse(
            detector._matches_wake_word("오늘도 평화롭게 시작하셨길 바랍니다", "시작")
        )

    def test_wake_audio_gate_rejects_silence(self):
        audio = _audio_from_envelope([0.0] * 40)

        self.assertFalse(should_transcribe_wake_audio(audio, 300))

    def test_wake_audio_gate_rejects_continuous_music(self):
        audio = _audio_from_envelope([0.7] * 40)

        self.assertFalse(should_transcribe_wake_audio(audio, 300))

    def test_wake_audio_gate_rejects_long_conversation(self):
        audio = _audio_from_envelope([0.7] * 150)

        self.assertFalse(should_transcribe_wake_audio(audio, 300))

    def test_wake_audio_gate_accepts_short_wake_word(self):
        envelope = [0.9] * 10 + [0.0] * 3 + [0.4] * 9 + [0.0] * 5 + [0.85] * 8
        audio = _audio_from_envelope(envelope)

        self.assertTrue(should_transcribe_wake_audio(audio, 300))

    def test_wake_audio_gate_ignores_trailing_silence_in_length(self):
        # listen()은 말 끝 무음(약 0.8초)까지 녹음하므로 전체 길이가 1.5초를 넘을 수 있다.
        envelope = (
            [0.0] * 10 + [0.9] * 10 + [0.0] * 3 + [0.4] * 9 + [0.0] * 5
            + [0.85] * 8 + [0.0] * 40
        )
        audio = _audio_from_envelope(envelope)

        self.assertTrue(should_transcribe_wake_audio(audio, 300))

    def test_only_gated_audio_reaches_stt_and_is_counted(self):
        settings = {
            "wake_words": ["아리야"],
            "stt_energy_threshold": 300,
            "stt_dynamic_energy": True,
            "stt_provider": "google",
        }
        with patch("audio.simple_wake.ConfigManager.load_settings", return_value=settings):
            with patch("audio.simple_wake.create_stt_provider", return_value=_FakeSttProvider()):
                detector = SimpleWakeWord()
        detector._calibrated = True
        envelope = [0.0] * 40 + [0.9] * 10 + [0.0] * 3 + [0.4] * 9
        audio = _audio_from_envelope(envelope + [0.0] * 5 + [0.85] * 8)

        with (
            patch("audio.simple_wake.ConfigManager.load_settings", return_value=settings),
            patch.object(
                detector.recognizer,
                "listen",
                side_effect=[_audio_from_envelope([0.0] * 40), audio],
            ),
        ):
            self.assertFalse(detector.listen_for_wake_word(object()))
            self.assertTrue(detector.listen_for_wake_word(object()))

        self.assertEqual(detector.stt_calls_per_hour, 1)

    def test_stt_call_count_expires_outside_the_rolling_hour(self):
        detector = self._make_detector()
        detector._stt_call_times.extend([100, 3599])

        with patch("audio.simple_wake.time.monotonic", return_value=3700):
            self.assertEqual(detector.stt_calls_per_hour, 1)

    def test_stt_call_rate_logs_zero_for_quiet_hours(self):
        detector = self._make_detector()
        detector._last_stt_metric_log = 0

        with (
            patch("audio.simple_wake.time.monotonic", side_effect=[60, 60]),
            patch("audio.simple_wake.logging.info") as log_info,
        ):
            detector._log_stt_call_rate()

        log_info.assert_called_once_with("[WakeWord] stt_calls_per_hour=%d", 0)

    def test_energy_threshold_updates_are_debounced_and_skip_unchanged_values(self):
        detector = self._make_detector()
        with (
            patch("audio.simple_wake.time.monotonic", side_effect=[10, 10.5, 11.4, 11.5]),
            patch("audio.simple_wake.ConfigManager.set_value", return_value=True) as set_value,
        ):
            detector._save_energy_threshold()
            detector.recognizer.energy_threshold = 450
            detector._save_energy_threshold()
            detector.recognizer.energy_threshold = 475
            detector._save_energy_threshold()

            detector._flush_pending_energy_threshold()
            set_value.assert_not_called()
            detector._flush_pending_energy_threshold()

        set_value.assert_called_once_with("stt_energy_threshold", 475)
        self.assertEqual(detector._saved_energy_threshold, 475)

    def test_flush_pending_settings_persists_threshold_on_shutdown(self):
        detector = self._make_detector()
        detector.recognizer.energy_threshold = 450

        with patch("audio.simple_wake.ConfigManager.set_value", return_value=True) as set_value:
            detector._save_energy_threshold()
            detector.flush_pending_settings()

        set_value.assert_called_once_with("stt_energy_threshold", 450)
        self.assertIsNone(detector._pending_energy_threshold)

    def test_refresh_settings_preserves_calibrated_threshold_until_config_changes(self):
        detector = self._make_detector()
        settings = {
            "wake_words": ["아리야"],
            "stt_energy_threshold": 300,
            "stt_dynamic_energy": True,
            "stt_provider": "google",
        }
        detector.recognizer.energy_threshold = 450

        with patch("audio.simple_wake.ConfigManager.load_settings", return_value=settings):
            detector.refresh_settings()

        self.assertEqual(detector.recognizer.energy_threshold, 450)

        settings["stt_energy_threshold"] = 500
        with patch("audio.simple_wake.ConfigManager.load_settings", return_value=settings):
            detector.refresh_settings()

        self.assertEqual(detector.recognizer.energy_threshold, 500)


if __name__ == "__main__":
    unittest.main()

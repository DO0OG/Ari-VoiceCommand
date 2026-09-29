import math
import struct
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import speech_recognition as sr


from audio.simple_wake import SimpleWakeWord, should_transcribe_wake_audio
from core.threads import VoiceRecognitionThread


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
    def __init__(self, text="아리야"):
        self.modes = []
        self.text = text

    def is_healthy(self):
        return True

    def transcribe(self, _audio, mode=None):
        self.modes.append(mode)
        return self.text


class SimpleWakeWordTests(unittest.TestCase):
    def test_thread_initialization_creates_one_shared_stt_provider(self):
        settings = {
            "wake_words": ["아리야"],
            "stt_energy_threshold": 300,
            "stt_dynamic_energy": True,
            "stt_provider": "google",
            "whisper_model": "small",
            "whisper_device": "auto",
            "whisper_compute_type": "int8",
        }
        created = []
        provider = SimpleNamespace(is_healthy=lambda: True)

        def create_provider(_settings):
            created.append(True)
            return provider

        with (
            patch("VoiceCommand.SharedMicrophone", return_value=Mock()),
            patch("core.threads.ConfigManager.load_settings", return_value=settings),
            patch(
                "core.threads.ConfigManager.get",
                side_effect=lambda key, default=None: settings.get(key, default),
            ),
            patch("core.threads.create_stt_provider", side_effect=create_provider),
            patch("audio.simple_wake.create_stt_provider", side_effect=create_provider),
        ):
            thread = VoiceRecognitionThread()
            self.assertTrue(thread._initialize_voice_recognition())

        self.assertEqual(len(created), 1)
        self.assertIs(thread.wake_detector._stt, provider)
        self.assertEqual(
            thread.wake_detector._provider_signature,
            thread._stt_signature,
        )

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
            return SimpleWakeWord(stt_provider=_FakeSttProvider())

    def test_matches_exact_wake_word_even_with_punctuation(self):
        detector = self._make_detector()

        self.assertTrue(detector._matches_wake_word("아리야!", "아리야"))
        self.assertTrue(detector._matches_wake_word(" 시작... ", "시작"))

    def test_matches_fuzzy_korean_wake_word(self):
        detector = self._make_detector()

        for transcript in ("아리야", "아리아", "아리 야"):
            with self.subTest(transcript=transcript):
                self.assertTrue(detector._matches_wake_word(transcript, "아리야"))

    def test_matches_normalized_english_and_japanese_wake_words(self):
        detector = self._make_detector()

        self.assertTrue(detector._matches_wake_word("COMPUTR!", "computer"))
        self.assertTrue(
            detector._matches_wake_word("コンピュータ", "こんぴゅーたー")
        )

    def test_rejects_unrelated_wake_word_transcript(self):
        detector = self._make_detector()

        self.assertFalse(detector._matches_wake_word("おはようございます", "アリヤ"))

    def test_extracts_japanese_command_without_spacing(self):
        detector = self._make_detector()

        cases = (
            ("コンピュータ照明をつけて", "こんぴゅーたー", "照明をつけて"),
            ("アリヤあかりをつけて", "ありや", "あかりをつけて"),
            ("ありよあかりをつけて", "ありや", "あかりをつけて"),
        )
        for transcript, wake_word, command in cases:
            with self.subTest(transcript=transcript):
                self.assertEqual(
                    detector._command_after_wake_word(transcript, wake_word),
                    command,
                )

    def test_wake_recognizer_uses_short_pause_threshold(self):
        settings = {
            "wake_words": ["아리야"],
            "stt_energy_threshold": 300,
            "stt_dynamic_energy": True,
            "wake_pause_threshold": 0.4,
        }
        with patch("audio.simple_wake.ConfigManager.load_settings", return_value=settings):
            detector = SimpleWakeWord(stt_provider=_FakeSttProvider())

        self.assertEqual(detector.recognizer.pause_threshold, 0.4)
        self.assertLessEqual(
            detector.recognizer.non_speaking_duration,
            detector.recognizer.pause_threshold,
        )

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

    def test_wake_audio_gate_accepts_longer_one_shot_utterance(self):
        audio = _audio_from_envelope([0.25] * 20 + [0.75] * 40 + [0.4] * 60)

        self.assertTrue(should_transcribe_wake_audio(audio, 300))

    def test_wake_audio_gate_rejects_utterance_over_limit(self):
        audio = _audio_from_envelope([0.25] * 100 + [0.75] * 100 + [0.4] * 50)

        self.assertFalse(should_transcribe_wake_audio(audio, 300))

    def test_wake_audio_gate_ignores_trailing_silence_in_length(self):
        # 말끝 무음은 발화 길이 계산에서 제외한다.
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
        provider = _FakeSttProvider()
        with patch("audio.simple_wake.ConfigManager.load_settings", return_value=settings):
            detector = SimpleWakeWord(stt_provider=provider)
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
        self.assertEqual(provider.modes, ["wake"])
        self.assertIsNone(detector.detected_command)

    def test_one_shot_transcript_stores_command_and_uses_wake_stt_mode(self):
        settings = {
            "wake_words": ["아리야"],
            "stt_energy_threshold": 300,
            "stt_dynamic_energy": True,
            "stt_provider": "google",
        }
        provider = _FakeSttProvider("아리아, 불 꺼줘")
        with patch("audio.simple_wake.ConfigManager.load_settings", return_value=settings):
            detector = SimpleWakeWord(stt_provider=provider)
        detector._calibrated = True
        audio = _audio_from_envelope([0.25] * 20 + [0.75] * 40 + [0.4] * 60)
        source = object()

        with (
            patch("audio.simple_wake.ConfigManager.load_settings", return_value=settings),
            patch.object(detector.recognizer, "listen", return_value=audio) as listen,
        ):
            self.assertTrue(detector.listen_for_wake_word(source))

        listen.assert_called_once_with(
            source,
            timeout=2,
            phrase_time_limit=4.0,
        )
        self.assertEqual(detector.detected_command, "불 꺼줘")
        self.assertEqual(provider.modes, ["wake"])

    def test_interrupt_discards_current_wake_audio_before_stt(self):
        detector = self._make_detector()
        detector._calibrated = True
        interrupt_event = threading.Event()
        interrupt_event.set()
        original_stream = Mock()
        source = SimpleNamespace(stream=original_stream)

        with (
            patch(
                "audio.simple_wake.ConfigManager.load_settings",
                return_value={"wake_words": ["아리야"], "stt_provider": "google"},
            ),
            patch.object(
                detector.recognizer,
                "listen",
                side_effect=lambda observed_source, **_kwargs: (
                    observed_source.stream.read(1024)
                ),
            ),
            patch.object(detector, "_transcribe") as transcribe,
        ):
            self.assertFalse(
                detector.listen_for_wake_word(
                    source,
                    interrupt_event=interrupt_event,
                )
            )

        self.assertIs(source.stream, original_stream)
        transcribe.assert_not_called()

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

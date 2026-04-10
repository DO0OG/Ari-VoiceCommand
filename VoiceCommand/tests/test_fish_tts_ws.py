import unittest

from tts.fish_tts_ws import (
    _estimate_pcm_duration_seconds,
    _playback_join_timeout,
)


class FishTTSWebSocketTests(unittest.TestCase):
    def test_estimate_pcm_duration_seconds_from_wav_params(self):
        duration = _estimate_pcm_duration_seconds(
            frame_bytes=3_308_630,
            sample_rate=44_100,
            channels=1,
            sample_width=2,
        )

        self.assertAlmostEqual(duration, 37.5, places=1)

    def test_playback_join_timeout_scales_with_long_audio_duration(self):
        timeout = _playback_join_timeout(37.5)

        self.assertGreater(timeout, 37.5)
        self.assertGreater(timeout, 30.0)

    def test_playback_join_timeout_keeps_short_audio_floor(self):
        self.assertEqual(_playback_join_timeout(3.0), 30.0)


if __name__ == "__main__":
    unittest.main()

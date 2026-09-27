import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from audio.mp3_decoder import decode_mp3_to_pcm
from core import bundle_import_self_test


class _ArrayBytes:
    def __init__(self, payload):
        self.payload = payload

    def tobytes(self):
        return self.payload


class _Frame:
    def __init__(self, payload):
        self.payload = payload

    def to_ndarray(self):
        return _ArrayBytes(self.payload)


class _Container:
    def __init__(self):
        self.closed = False

    def decode(self, audio):
        if audio != 0:
            raise AssertionError("expected first audio stream")
        return [_Frame(b"frame-1"), _Frame(b"frame-2")]

    def close(self):
        self.closed = True


class _Resampler:
    def __init__(self, **kwargs):
        self.options = kwargs

    def resample(self, frame):
        return [_Frame(b"flush")] if frame is None else [frame]


class ReleaseBundleDependencyTests(unittest.TestCase):
    def test_mp3_decoder_uses_pyav_resampler_and_closes_container(self):
        container = _Container()
        opened = []
        resampler_options = []

        def create_resampler(**kwargs):
            resampler_options.append(kwargs)
            return _Resampler(**kwargs)

        fake_av = SimpleNamespace(
            open=lambda source, **kwargs: opened.append((source, kwargs)) or container,
            AudioResampler=create_resampler,
        )
        with patch.dict(sys.modules, {"av": fake_av}):
            pcm = decode_mp3_to_pcm(b"mp3-data", 22050)

        self.assertEqual(pcm, b"frame-1frame-2flush")
        self.assertEqual(opened[0][1], {"format": "mp3"})
        self.assertEqual(resampler_options, [{"format": "s16", "layout": "mono", "rate": 22050}])
        self.assertTrue(container.closed)

    def test_mp3_decoder_rejects_empty_data_without_opening_av(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            decode_mp3_to_pcm(b"", 22050)

    def test_mp3_decoder_closes_container_when_decoding_fails(self):
        class FailingContainer(_Container):
            def decode(self, audio):
                raise RuntimeError("decode failed")

        container = FailingContainer()
        fake_av = SimpleNamespace(
            open=lambda source, **kwargs: container,
            AudioResampler=_Resampler,
        )
        with patch.dict(sys.modules, {"av": fake_av}):
            with self.assertRaisesRegex(RuntimeError, "decode failed"):
                decode_mp3_to_pcm(b"mp3-data", 22050)
        self.assertTrue(container.closed)

    def test_pyav_mp3_encode_and_decode_round_trip_in_memory(self):
        import av
        import numpy as np
        from fractions import Fraction

        try:
            av.Codec("libmp3lame", "w")
        except Exception as exc:
            self.skipTest(f"PyAV MP3 encoder unavailable: {exc}")

        sample_rate = 22050
        samples = (np.sin(np.linspace(0, 20 * np.pi, 2205, dtype=np.float32)) * 0.2).reshape(1, -1)
        output = io.BytesIO()
        container = av.open(output, mode="w", format="mp3")
        stream = container.add_stream("libmp3lame", rate=sample_rate)
        stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(samples, format="fltp", layout="mono")
        frame.sample_rate = sample_rate
        frame.pts = 0
        frame.time_base = Fraction(1, sample_rate)
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
        container.close()

        pcm = decode_mp3_to_pcm(output.getvalue(), sample_rate)
        self.assertGreater(len(pcm), 0)
        self.assertEqual(len(pcm) % 2, 0)

    def test_bundle_self_test_writes_failure_details_and_returns_nonzero(self):
        def passing_check():
            return {"loaded": True}

        def failing_check():
            raise ImportError("excluded module")

        with tempfile.TemporaryDirectory() as directory, patch.object(
            bundle_import_self_test,
            "_BUNDLE_CHECKS",
            (("pass", passing_check), ("fail", failing_check)),
        ):
            report_path = Path(directory) / "report.json"
            result = bundle_import_self_test.run_bundle_import_self_test(str(report_path))
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(result, 1)
        self.assertFalse(report["ok"])
        self.assertTrue(report["checks"]["pass"]["ok"])
        self.assertFalse(report["checks"]["fail"]["ok"])
        self.assertIn("excluded module", report["checks"]["fail"]["error"])

    def test_bundle_self_test_succeeds_when_all_checks_pass(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            bundle_import_self_test,
            "_BUNDLE_CHECKS",
            (("ready", lambda: {"loaded": True}),),
        ):
            report_path = Path(directory) / "report.json"
            result = bundle_import_self_test.run_bundle_import_self_test(str(report_path))
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(result, 0)
        self.assertTrue(report["ok"])
        self.assertTrue(report["checks"]["ready"]["ok"])


if __name__ == "__main__":
    unittest.main()
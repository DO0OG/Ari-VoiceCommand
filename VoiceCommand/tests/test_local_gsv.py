import hashlib
import os
import tempfile
import threading
import unittest
import wave
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from core.emotions import DEFAULT_EMOTION
from tts.gsv import audio, model_store
from tts.gsv.engine import GSVEngine, _session_with_weights
from tts.gsv.g2p.symbols import symbols_v2
from tts.gsv.text_splitter import split_text
from tts.tts_local_gsv import LocalGSVTTS, detect_language, reference_cache_key


class LanguageDetectionTests(unittest.TestCase):
    def test_detects_korean_before_japanese_and_english(self):
        self.assertEqual(detect_language("안녕하세요"), "ko")
        self.assertEqual(detect_language("こんにちは"), "ja")
        self.assertEqual(detect_language("東京"), "ja")
        self.assertEqual(detect_language("Hello world"), "en")


class KoreanG2PTests(unittest.TestCase):
    def test_output_only_contains_model_symbols(self):
        from tts.gsv.ko_g2p.korean import korean_to_phones

        phones = korean_to_phones("안녕하세요. 오늘은 3개입니다!")

        self.assertTrue(phones)
        self.assertLessEqual(set(phones), set(symbols_v2))


class AudioPreprocessingTests(unittest.TestCase):
    def test_resample_poly_returns_expected_length(self):
        samples = np.zeros(24000, dtype=np.float32)

        result = audio.resample_audio(samples, 24000, 32000)

        self.assertEqual(len(result), 32000)

    def test_reads_wav_and_mixes_stereo_channels(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "reference.wav")
            frames = np.array([[32767, -32768], [16384, 16384]], dtype="<i2")
            with wave.open(path, "wb") as target:
                target.setnchannels(2)
                target.setsampwidth(2)
                target.setframerate(24000)
                target.writeframes(frames.tobytes())

            samples, sample_rate = audio.read_wav(path)

        self.assertEqual(sample_rate, 24000)
        self.assertEqual(len(samples), 2)
        self.assertAlmostEqual(float(samples[1]), 0.5, places=4)

    def test_rejects_non_wav_reference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "reference.wav")
            Path(path).write_bytes(b"not wav")

            with self.assertRaisesRegex(ValueError, "PCM WAV"):
                audio.read_wav(path)


class TextSplittingTests(unittest.TestCase):
    def test_splits_at_sentence_endings_and_keeps_short_lead_in(self):
        self.assertEqual(
            split_text("안녕하세요. 반갑습니다."),
            ["안녕하세요.", "반갑습니다."],
        )
        self.assertEqual(split_text("짧. 안녕하세요."), ["짧. 안녕하세요."])


class ModelStoreTests(unittest.TestCase):
    def test_status_check_can_skip_hashing_large_assets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = os.path.join(temp_dir, "model.bin")
            Path(model_path).write_bytes(b"model")
            dictionary_dir = os.path.join(temp_dir, "open_jtalk_dic")
            os.makedirs(dictionary_dir)
            Path(dictionary_dir, "sys.dic").touch()

            with (
                patch.object(model_store, "get_model_dir", return_value=temp_dir),
                patch.object(
                    model_store,
                    "_assets",
                    return_value=[("release", "model.bin", 5, "unused")],
                ),
                patch.object(model_store, "_sha256", side_effect=AssertionError),
            ):
                self.assertTrue(model_store.is_model_installed(verify_hash=False))

    def _configure_small_install(self, temp_dir, size, digest, response):
        patcher = patch.object(model_store, "get_model_dir", return_value=temp_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        assets = [("release", "model.bin", size, digest)]
        assets_patcher = patch.object(model_store, "_assets", return_value=assets)
        assets_patcher.start()
        self.addCleanup(assets_patcher.stop)
        zip_patcher = patch.object(
            model_store,
            "_OPEN_JTALK_ZIP",
            ("dictionary.zip", 0, "unused"),
        )
        zip_patcher.start()
        self.addCleanup(zip_patcher.stop)
        request_patcher = patch.object(
            model_store.requests, "get", return_value=response
        )
        request_patcher.start()
        self.addCleanup(request_patcher.stop)
        return os.path.join(temp_dir, "model.bin.part")

    def test_hash_mismatch_fails_and_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            body = b"nope"
            response = _DownloadResponse([body])
            part_path = self._configure_small_install(
                temp_dir, len(body), hashlib.sha256(b"good").hexdigest(), response
            )

            with self.assertRaises(ValueError):
                model_store.install_model()

            self.assertFalse(os.path.exists(part_path))

    def test_cancel_during_download_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cancel_event = threading.Event()
            response = _DownloadResponse([b"part"], cancel_event=cancel_event)
            part_path = self._configure_small_install(
                temp_dir, 4,
                hashlib.sha256(b"part").hexdigest(),
                response,
            )

            with self.assertRaises(InterruptedError):
                model_store.install_model(cancel_event=cancel_event)

            self.assertFalse(os.path.exists(part_path))

    def test_dictionary_extraction_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = os.path.join(temp_dir, "unsafe.zip")
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escaped", "unsafe")

            with self.assertRaises(ValueError):
                model_store._extract_japanese_dictionary(
                    archive_path, os.path.join(temp_dir, "dictionary")
                )


class ProviderTests(unittest.TestCase):
    def test_missing_model_raises_runtime_error(self):
        with patch("tts.tts_local_gsv.is_model_installed", return_value=False):
            with self.assertRaises(RuntimeError):
                LocalGSVTTS(settings={})

    def test_reference_selection_uses_emotion_then_common_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            common_wav = os.path.join(temp_dir, "common.wav")
            happy_wav = os.path.join(temp_dir, "happy.wav")
            Path(common_wav).touch()
            Path(happy_wav).touch()
            engine = Mock()
            engine.prepare_reference.return_value = object()
            with (
                patch("tts.tts_local_gsv.is_model_installed", return_value=True),
                patch("tts.tts_local_gsv.GSVEngine", return_value=engine),
            ):
                provider = LocalGSVTTS(
                    settings={
                        "tts_reference_wav": common_wav,
                        "cosyvoice_reference_text": "공통 대본",
                        "local_gsv_emotion_refs": {
                            "기쁨": {"wav": happy_wav, "text": "기쁜 대본"}
                        },
                    }
                )
                self.addCleanup(provider.cleanup)
                self.assertTrue(provider.wait_until_warmup_done(2))

                selected = provider._select_reference("기쁨")
                fallback = provider._select_reference(DEFAULT_EMOTION)
                first = provider._get_reference("기쁨")
                second = provider._get_reference("기쁨")

            self.assertEqual(selected, (happy_wav, "기쁜 대본", "ko"))
            self.assertEqual(fallback, (common_wav, "공통 대본", "ko"))
            self.assertIs(first, second)
            engine.prepare_reference.assert_called_once_with(
                happy_wav, "기쁜 대본", "ko"
            )

    def test_reference_cache_key_changes_when_file_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "reference.wav")
            Path(path).write_bytes(b"wav")
            first = reference_cache_key(path, "대본", "ko")
            stat = os.stat(path)
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))
            second = reference_cache_key(path, "대본", "ko")

        self.assertNotEqual(first, second)


class ONNXSessionTests(unittest.TestCase):
    def test_fp16_weights_are_converted_in_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            weights_path = os.path.join(temp_dir, "weights.bin")
            np.array([0.5, -1.5], dtype=np.float16).tofile(weights_path)
            tensor = SimpleNamespace(
                data_location=1,
                external_data=[
                    SimpleNamespace(key="offset", value="0"),
                    SimpleNamespace(key="length", value="8"),
                ],
                raw_data=b"",
                name="weight",
            )
            model = SimpleNamespace(
                graph=SimpleNamespace(initializer=[tensor]),
                SerializeToString=lambda: b"model",
            )
            with (
                patch("tts.gsv.engine.onnx.load_model", return_value=model),
                patch("tts.gsv.engine.ort.InferenceSession", return_value=object()) as session,
            ):
                _session_with_weights(
                    "model.onnx",
                    ["CPUExecutionProvider"],
                    Mock(),
                    weights_path,
                    fp16_weights=True,
                )

            self.assertEqual(tensor.raw_data, np.array([0.5, -1.5], dtype=np.float32).tobytes())
            self.assertEqual(tensor.data_location, 0)
            self.assertEqual(tensor.external_data, [])
            self.assertEqual(session.call_args.args[0], b"model")

    def test_session_loader_requests_all_pinned_sessions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = GSVEngine.__new__(GSVEngine)
            engine.model_dir = temp_dir
            engine._sessions = {}
            with (
                patch(
                    "tts.gsv.engine._session_with_weights", return_value=object()
                ) as weight_session,
                patch(
                    "tts.gsv.engine.ort.InferenceSession", return_value=object()
                ) as plain_session,
            ):
                engine._load_sessions_with(["CPUExecutionProvider"])

        self.assertEqual(
            set(engine._sessions),
            {
                "t2s_encoder_fp32.onnx",
                "t2s_first_stage_decoder_fp32.onnx",
                "t2s_stage_decoder_fp32.onnx",
                "vits_fp32.onnx",
                "prompt_encoder_fp32.onnx",
                "hubert",
                "speaker",
            },
        )
        self.assertEqual(weight_session.call_count, 6)
        plain_session.assert_called_once()

    def test_directml_session_failure_retries_with_cpu(self):
        engine = GSVEngine.__new__(GSVEngine)
        engine._requested_device = "auto"
        engine._sessions = {}
        with (
            patch(
                "tts.gsv.engine.ort.get_available_providers",
                return_value=["DmlExecutionProvider", "CPUExecutionProvider"],
            ),
            patch.object(
                engine,
                "_load_sessions_with",
                side_effect=[RuntimeError("DML failed"), None],
            ) as load_sessions,
            patch("tts.gsv.engine.logging.warning"),
        ):
            engine._load_sessions()

        self.assertEqual(load_sessions.call_args_list[0].args[0][0], "DmlExecutionProvider")
        self.assertEqual(load_sessions.call_args_list[1].args[0], ["CPUExecutionProvider"])


class VerifiedPickleTests(unittest.TestCase):
    def test_wrong_pickle_hash_is_rejected_before_loading(self):
        from tts.gsv.g2p.english import _load_verified_pickle

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "cache.pickle")
            Path(path).write_bytes(b"not a pickle")

            with self.assertRaises(ValueError):
                _load_verified_pickle(path, "0" * 64)


class _DownloadResponse:
    def __init__(self, chunks, cancel_event=None):
        self.chunks = chunks
        self.cancel_event = cancel_event

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1):
        del chunk_size
        for chunk in self.chunks:
            if self.cancel_event is not None:
                self.cancel_event.set()
            yield chunk


if __name__ == "__main__":
    unittest.main()

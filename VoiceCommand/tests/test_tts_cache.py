import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tts.tts_cache import (
    DEFAULT_MAX_BYTES,
    DiskTTSAudioCache,
    build_tts_cache_key,
)


class DiskTTSAudioCacheTests(unittest.TestCase):
    def test_cache_key_normalizes_text_and_includes_language(self):
        base = ("edge", "voice", "+0%", "+0%", "neutral", "en-US")
        first = build_tts_cache_key(*base, "Cafe\u0301  with\n spaces")
        normalized = build_tts_cache_key(*base, "Café with spaces")
        other_language = build_tts_cache_key(
            "edge", "voice", "+0%", "+0%", "neutral", "fr-FR", "Café with spaces"
        )

        self.assertEqual(first, normalized)
        self.assertNotEqual(first, other_language)

    def test_cache_key_separates_voice_rate_volume_and_emotion(self):
        base = ("edge", "voice", "+0%", "+0%", "neutral", "en-US", "Hello.")
        key = build_tts_cache_key(*base)

        for index, value in ((1, "other-voice"), (2, "+10%"), (3, "-10%"), (4, "happy")):
            changed = list(base)
            changed[index] = value
            with self.subTest(setting=index):
                self.assertNotEqual(key, build_tts_cache_key(*changed))

    def test_default_directory_is_resolved_on_first_access(self):
        cache = DiskTTSAudioCache()
        self.assertIsNone(cache._cache_dir)

        with tempfile.TemporaryDirectory() as tmp:
            expected = Path(tmp) / "tts_cache"
            with patch(
                "core.resource_manager.ResourceManager.get_writable_path",
                return_value=str(expected),
            ) as get_writable_path:
                self.assertIsNone(cache.get("missing"))

            get_writable_path.assert_called_once_with("tts_cache")
            self.assertEqual(cache._cache_dir, expected)
            self.assertFalse(expected.exists())

    def test_put_and_get_raw_pcm_and_ignore_empty_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = DiskTTSAudioCache(tmp)

            cache.put("sample", b"\x00\x01\xfe")
            cache.put("empty", b"")

            self.assertEqual(cache.get("sample"), b"\x00\x01\xfe")
            self.assertIsNone(cache.get("empty"))

    def test_hit_updates_lru_order_and_eviction_keeps_size_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = DiskTTSAudioCache(tmp, max_bytes=6)
            cache.put("first", b"111")
            cache.put("second", b"222")

            second_path = cache._path_for_key(Path(tmp), "second")
            os.utime(second_path, ns=(1_000_000_000, 1_000_000_000))
            self.assertEqual(cache.get("first"), b"111")
            cache.put("third", b"333")

            self.assertEqual(cache.get("first"), b"111")
            self.assertIsNone(cache.get("second"))
            self.assertEqual(cache.get("third"), b"333")
            self.assertEqual(
                sum(path.stat().st_size for path in Path(tmp).glob("*.pcm")), 6
            )

    def test_oversized_entries_are_skipped_and_io_errors_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = DiskTTSAudioCache(tmp, max_bytes=2)
            cache.put("large", b"123")
            self.assertIsNone(cache.get("large"))

            with patch("tts.tts_cache.os.replace", side_effect=OSError("disk full")):
                cache.put("failed", b"12")

            self.assertIsNone(cache.get("failed"))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_default_limit_is_50_mib(self):
        self.assertEqual(DEFAULT_MAX_BYTES, 50 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()

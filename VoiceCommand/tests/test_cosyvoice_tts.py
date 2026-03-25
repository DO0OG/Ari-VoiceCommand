import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tts.cosyvoice_tts import _PCMChunkBuffer, _normalize_text_cached


class PCMChunkBufferTests(unittest.TestCase):
    def test_pop_bytes_preserves_remainder(self):
        buffer = _PCMChunkBuffer()
        buffer.append(b"abcd")
        buffer.append(b"efgh")

        self.assertEqual(buffer.pop_bytes(3), b"abc")
        self.assertEqual(buffer.size, 5)
        self.assertEqual(buffer.pop_bytes(3), b"def")
        self.assertEqual(buffer.size, 2)
        self.assertEqual(buffer.pop_bytes(8), b"gh")
        self.assertEqual(buffer.size, 0)

    def test_normalize_cache_returns_same_value(self):
        first = _normalize_text_cached("12시 30분")
        second = _normalize_text_cached("12시 30분")
        self.assertEqual(first, second)
        self.assertIn("열두시", first)


if __name__ == "__main__":
    unittest.main()

import base64
import tempfile
import unittest
from pathlib import Path

from agent.llm_provider import LLMProvider


class VisionTests(unittest.TestCase):
    def test_load_image_base64_from_file(self):
        provider = LLMProvider()
        png_header = b"\x89PNG\r\n\x1a\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.png"
            path.write_bytes(png_header)

            data, media_type = provider._load_image_base64(str(path))

            self.assertEqual(media_type, "image/png")
            self.assertEqual(base64.b64decode(data), png_header)


if __name__ == "__main__":
    unittest.main()

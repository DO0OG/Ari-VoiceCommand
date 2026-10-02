import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from services.image_generator import ImageGenerator


class ImageGeneratorDownloadTests(unittest.TestCase):
    def test_rejects_non_https_image_url(self):
        generator = ImageGenerator()

        with self.assertRaises(ValueError):
            generator._download_image_url("file:///tmp/secret.png", "unused.png")

    def test_downloads_https_image_url_with_limited_urlopen(self):
        generator = ImageGenerator()
        response = Mock()
        response.read.return_value = b"image-bytes"
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.png"
            with patch("services.image_generator.safe_urlopen", return_value=response) as safe_urlopen:
                generator._download_image_url("https://example.com/image.png", str(path))

            safe_urlopen.assert_called_once_with("https://example.com/image.png", timeout=30, allowed_schemes=("https",))
            response.read.assert_called_once_with(30 * 1024 * 1024 + 1)
            self.assertEqual(path.read_bytes(), b"image-bytes")

    def test_rejects_image_download_over_30mb(self):
        generator = ImageGenerator()
        response = Mock()
        response.read.return_value = b"x" * (30 * 1024 * 1024 + 1)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.png"
            with patch("services.image_generator.safe_urlopen", return_value=response):
                with self.assertRaisesRegex(ValueError, "30MB"):
                    generator._download_image_url("https://example.com/image.png", str(path))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()

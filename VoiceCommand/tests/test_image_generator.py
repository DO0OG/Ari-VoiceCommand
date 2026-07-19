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

    def test_downloads_https_image_url_with_requests(self):
        generator = ImageGenerator()
        response = Mock()
        response.content = b"image-bytes"
        response.raise_for_status = Mock()

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.png"
            fake_requests = Mock()
            fake_requests.get.return_value = response
            with patch.dict("sys.modules", {"requests": fake_requests}):
                generator._download_image_url("https://example.com/image.png", str(path))

            fake_requests.get.assert_called_once_with("https://example.com/image.png", timeout=30)
            response.raise_for_status.assert_called_once_with()
            self.assertEqual(path.read_bytes(), b"image-bytes")


if __name__ == "__main__":
    unittest.main()

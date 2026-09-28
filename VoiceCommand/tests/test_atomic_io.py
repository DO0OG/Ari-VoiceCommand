import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.atomic_io import backup_corrupt_file, write_json_atomic, write_text_atomic


class AtomicIoTests(unittest.TestCase):
    def test_write_json_and_text_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp) / "settings.json"
            text_path = Path(tmp) / "history.txt"

            write_json_atomic(json_path, {"언어": "한국어"}, ensure_ascii=False, indent=2)
            write_text_atomic(text_path, "대화 기록")

            self.assertEqual(
                json.loads(json_path.read_text(encoding="utf-8")),
                {"언어": "한국어"},
            )
            self.assertEqual(text_path.read_text(encoding="utf-8"), "대화 기록")

    def test_json_write_failure_preserves_original_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text('{"value": 1}', encoding="utf-8")

            with patch("core.atomic_io.json.dump", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    write_json_atomic(path, {"value": 2})

            self.assertEqual(path.read_text(encoding="utf-8"), '{"value": 1}')
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_replace_failure_preserves_original_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text('{"value": 1}', encoding="utf-8")

            with patch("core.atomic_io.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    write_json_atomic(path, {"value": 2})

            self.assertEqual(path.read_text(encoding="utf-8"), '{"value": 1}')
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_corrupt_backup_preserves_bytes_and_avoids_collisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "facts.json"
            path.write_bytes(b"{broken json\xff")

            with patch("core.atomic_io.datetime") as mock_datetime:
                mock_datetime.now.return_value.strftime.return_value = "20260929-120000"
                first = backup_corrupt_file(path)
                second = backup_corrupt_file(path)

            self.assertEqual(first.name, "facts.corrupt-20260929-120000.json")
            self.assertEqual(second.name, "facts.corrupt-20260929-120000-1.json")
            self.assertEqual(first.read_bytes(), path.read_bytes())
            self.assertEqual(second.read_bytes(), path.read_bytes())


if __name__ == "__main__":
    unittest.main()

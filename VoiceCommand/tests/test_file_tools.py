import os
import tempfile
import unittest
from pathlib import Path

from agent import file_tools
from agent.file_tools import analyze_data_file, batch_rename_files, detect_file_set


class FileToolsTests(unittest.TestCase):
    def test_detect_file_set_groups_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "a.txt"), "w", encoding="utf-8").close()
            open(os.path.join(tmp, "b.csv"), "w", encoding="utf-8").close()

            result = detect_file_set(tmp)

            self.assertEqual(result["file_count"], 2)
            self.assertEqual(result["extensions"]["txt"], 1)
            self.assertEqual(result["extensions"]["csv"], 1)

    def test_batch_rename_files_applies_regex_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "hello world.txt"), "w", encoding="utf-8").close()

            result = batch_rename_files(tmp, r"\s+", "_")

            self.assertEqual(result["renamed_count"], 1)
            self.assertTrue(os.path.exists(os.path.join(tmp, "hello_world.txt")))

    def test_analyze_data_file_returns_numeric_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scores.csv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("name,score\nari,10\nbee,11\ncee,50\n")

            result = analyze_data_file(path)

            self.assertIn("numeric_summary", result)
            self.assertIn("score", result["numeric_summary"])
            self.assertIsInstance(result["numeric_summary"]["score"]["outlier_count"], int)

    def test_read_edit_search_and_move_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "sample.txt"

            write_result = file_tools.write_file(str(path), "alpha\nbeta\n")
            self.assertNotIn("error", write_result)

            read_result = file_tools.read_file(str(path), start_line=2)
            self.assertEqual(read_result["content"], "beta\n")

            edit_result = file_tools.edit_file(str(path), "beta", "gamma")
            self.assertTrue(edit_result["replaced"])

            search_result = file_tools.search_in_files(str(root), "gamma", "*.txt")
            self.assertEqual(search_result["count"], 1)

            moved = root / "moved.txt"
            move_result = file_tools.move_file(str(path), str(moved))
            self.assertTrue(move_result["moved"])

            delete_result = file_tools.delete_file(str(moved), confirmed=True)
            self.assertTrue(delete_result["deleted"])

    def test_edit_requires_unique_old_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dup.txt"
            path.write_text("same same", encoding="utf-8")
            result = file_tools.edit_file(str(path), "same", "once")
            self.assertIn("error", result)
            self.assertEqual(result["matches"], 2)


if __name__ == "__main__":
    unittest.main()

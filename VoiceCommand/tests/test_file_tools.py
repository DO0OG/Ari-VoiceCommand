import os
import tempfile
import unittest


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


if __name__ == "__main__":
    unittest.main()

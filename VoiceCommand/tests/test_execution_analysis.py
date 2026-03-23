import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.execution_analysis import (
    classify_failure_message,
    describes_open_action,
    describes_storage_action,
    existing_paths,
    extract_artifacts,
    is_read_only_step_content,
)


class ExecutionAnalysisTests(unittest.TestCase):
    def test_classify_failure_message(self):
        self.assertEqual(classify_failure_message("HTTP timeout while fetching"), "timeout")
        self.assertEqual(classify_failure_message("Access is denied"), "permission_denied")
        self.assertEqual(classify_failure_message("NameError: foo"), "code_generation_error")

    def test_read_only_step_detection(self):
        self.assertTrue(is_read_only_step_content("print('hello')", "정보 수집"))
        self.assertFalse(is_read_only_step_content("save_document('a','b','c')", "문서 저장"))

    def test_extract_artifacts_and_existing_paths(self):
        target = os.path.abspath(os.path.join(ROOT, "..", "README.md"))
        artifacts = extract_artifacts([f"saved: {target}", "see https://example.com/page"])
        self.assertIn(target, artifacts["paths"])
        self.assertIn("https://example.com/page", artifacts["urls"])
        self.assertIn(target, existing_paths(artifacts["paths"]))

    def test_description_helpers(self):
        self.assertTrue(describes_storage_action("문서 저장"))
        self.assertTrue(describes_open_action("앱 실행"))
        self.assertFalse(describes_open_action("정보 수집"))


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import threading
import unittest
import json


from agent.skill_library import Skill, SkillLibrary


class SkillLibraryTests(unittest.TestCase):
    def _make_library(self, tmpdir: str) -> SkillLibrary:
        library = SkillLibrary.__new__(SkillLibrary)
        library.file_path = os.path.join(tmpdir, "skill_library.json")
        library.skills = []
        library._save_lock = threading.RLock()
        library._save_timer = None
        library._save_delay_seconds = 0.05
        return library

    def test_try_extract_skill_captures_context_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = self._make_library(tmp)

            class _Step:
                step_id = 0
                step_type = "python"
                content = "open_url('https://example.com'); save_document(desktop_path, 'links', 'ok')"
                description_kr = "브라우저 링크 저장"
                expected_output = ""
                condition = ""
                on_failure = "abort"

            skill = library.try_extract_skill("브라우저 링크 저장해줘", [_Step()], True, 120)

            self.assertIsNotNone(skill)
            self.assertIn("웹", skill.context_tags)
            self.assertGreaterEqual(skill.confidence, 0.5)

    def test_get_applicable_skill_prefers_context_tag_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = self._make_library(tmp)
            library.skills = [
                Skill(skill_id="file", name="파일 열기", trigger_patterns=["열어"], steps=[], confidence=0.7, context_tags=["파일"]),
                Skill(skill_id="web", name="웹 열기", trigger_patterns=["열어"], steps=[], confidence=0.7, context_tags=["웹"]),
            ]

            selected = library.get_applicable_skill("브라우저 링크 열어줘")

            self.assertIsNotNone(selected)
            self.assertEqual(selected.skill_id, "web")

    def test_flush_persists_pending_skill_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = self._make_library(tmp)
            library.skills = [
                Skill(skill_id="web", name="웹 열기", trigger_patterns=["열어"], steps=[], confidence=0.7, context_tags=["웹"])
            ]
            library._schedule_save()

            library.flush()

            with open(library.file_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(len(payload), 1)


if __name__ == "__main__":
    unittest.main()

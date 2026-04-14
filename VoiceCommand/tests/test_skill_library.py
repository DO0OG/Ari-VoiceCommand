import os
import tempfile
import threading
import unittest
import json
from unittest.mock import patch


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
            self.assertGreaterEqual(skill.confidence, 0.4)

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

    def test_get_applicable_skill_uses_goal_embedding_similarity(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = self._make_library(tmp)
            library.skills = [
                Skill(
                    skill_id="chrome",
                    name="크롬 실행",
                    trigger_patterns=["실행"],
                    steps=[],
                    confidence=0.7,
                    context_tags=["웹"],
                    goal_embedding=[1.0, 0.0],
                ),
                Skill(
                    skill_id="note",
                    name="메모장 실행",
                    trigger_patterns=["실행"],
                    steps=[],
                    confidence=0.7,
                    context_tags=["웹"],
                    goal_embedding=[0.0, 1.0],
                ),
            ]

            with patch.object(library, "_embed_goal", return_value=[1.0, 0.0]):
                selected = library.get_applicable_skill("크롬 브라우저 실행")

            self.assertIsNotNone(selected)
            self.assertEqual(selected.skill_id, "chrome")

    def test_try_extract_skill_starts_with_single_success_and_embedding(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = self._make_library(tmp)

            class _Step:
                step_id = 0
                step_type = "python"
                content = "launch_browser('chrome')"
                description_kr = "크롬 실행"
                expected_output = ""
                condition = ""
                on_failure = "abort"

            with patch.object(library, "_embed_goal", return_value=[0.2, 0.8]):
                skill = library.try_extract_skill("크롬 브라우저 실행해줘", [_Step()], True, 90)

            self.assertIsNotNone(skill)
            self.assertEqual(skill.success_count, 1)
            self.assertAlmostEqual(skill.confidence, 0.42, places=2)
            self.assertEqual(skill.goal_embedding, [0.2, 0.8])

    def test_async_compile_marks_skill_as_failed_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = self._make_library(tmp)
            skill = Skill(
                skill_id="skill_1",
                name="웹 열기",
                trigger_patterns=["열기"],
                steps=[],
            )

            with patch("agent.skill_optimizer.get_skill_optimizer") as optimizer_factory:
                optimizer_factory.return_value.compile_to_python.return_value = None
                library._async_compile(skill)

            self.assertTrue(skill.compile_failed)
            optimizer_factory.return_value.compile_to_python.reset_mock()

            library._async_compile(skill)

            optimizer_factory.return_value.compile_to_python.assert_not_called()

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

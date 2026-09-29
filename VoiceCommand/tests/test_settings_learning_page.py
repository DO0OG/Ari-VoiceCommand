import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ui.settings_learning_page import format_skill_row


class LearningSettingsPageFormattingTests(unittest.TestCase):
    def test_skill_row_shows_recorded_success_rate_and_last_use(self):
        skill = SimpleNamespace(
            skill_id="skill_a",
            name="파일 정리",
            success_count=0,
            fail_count=0,
            enabled=True,
        )
        usage = {
            "skill_a": {
                "total": 4,
                "success_rate": 0.75,
                "last_used": "2026-09-29T12:34:00",
            }
        }

        with patch("ui.settings_learning_page._", side_effect=lambda value: value):
            label = format_skill_row(skill, usage)

        self.assertIn("성공률 75%", label)
        self.assertIn("마지막 사용: 2026-09-29 12:34", label)
        self.assertIn("상태: 사용 중", label)

    def test_skill_row_uses_saved_counts_when_history_is_missing(self):
        skill = SimpleNamespace(
            skill_id="skill_a",
            name="파일 정리",
            success_count=3,
            fail_count=1,
            enabled=False,
        )

        with patch("ui.settings_learning_page._", side_effect=lambda value: value):
            label = format_skill_row(skill, {})

        self.assertIn("성공률 75%", label)
        self.assertIn("마지막 사용: 기록 없음", label)
        self.assertIn("상태: 꺼짐", label)


if __name__ == "__main__":
    unittest.main()

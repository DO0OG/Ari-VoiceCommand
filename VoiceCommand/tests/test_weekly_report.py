import unittest
from types import SimpleNamespace
from unittest.mock import patch


from agent.weekly_report import WeeklyReport


class WeeklyReportTests(unittest.TestCase):
    def test_generate_includes_scheduled_runs_and_repeated_failures(self):
        report = WeeklyReport()
        fake_strategy_memory = SimpleNamespace(
            get_stats=lambda days=7: {"total": 5, "success": 3, "fail": 2, "success_rate": 0.6},
            get_repeated_failures=lambda min_count=2: [("timeout", 2)],
        )
        fake_skill_library = SimpleNamespace(
            list_skills=lambda: [
                SimpleNamespace(name="웹 저장", compiled=True, confidence=0.8),
                SimpleNamespace(name="파일 정리", compiled=False, confidence=0.4),
            ]
        )
        fake_scheduler = SimpleNamespace(
            get_task_runs=lambda limit=30: [
                {"started_at": "2099-01-01T09:00:00", "success": True},
                {"started_at": "2099-01-02T09:00:00", "success": False},
            ]
        )
        fake_learning_metrics = SimpleNamespace(
            get_report_lines=lambda limit=3: ["SkillLibrary 2회 활성 (활성 80% / 비활성 50% / lift +30%p)"]
        )
        fake_regression_guard = SimpleNamespace(
            check=lambda: "이번 주 성공률이 20% 하락했어요 (60% → 40%). 최근 변경 사항을 확인해보세요."
        )
        fake_context_manager = SimpleNamespace(context={"facts": {"name": "Ari"}})

        with patch("agent.strategy_memory.get_strategy_memory", return_value=fake_strategy_memory):
            with patch("agent.skill_library.get_skill_library", return_value=fake_skill_library):
                with patch("agent.proactive_scheduler.get_scheduler", return_value=fake_scheduler):
                    with patch("agent.learning_metrics.get_learning_metrics", return_value=fake_learning_metrics):
                        with patch("agent.regression_guard.get_regression_guard", return_value=fake_regression_guard):
                            with patch("memory.user_context.get_context_manager", return_value=fake_context_manager):
                                text = report.generate(days=7)

        self.assertIn("예약 작업 2건 처리", text)
        self.assertIn("반복 실패 패턴: timeout 2회", text)
        self.assertIn("신뢰도 낮은 스킬", text)
        self.assertIn("학습 기여도:", text)
        self.assertIn("회귀 경고:", text)


if __name__ == "__main__":
    unittest.main()

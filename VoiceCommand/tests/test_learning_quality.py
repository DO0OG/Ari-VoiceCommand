import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.goal_predictor import GoalPredictor
from agent.learning_metrics import LearningMetrics
from agent.regression_guard import RegressionGuard
from agent.reflection_engine import ReflectionEngine
from agent.strategy_memory import StrategyMemory


class LearningQualityTests(unittest.TestCase):
    def test_goal_predictor_warns_on_repeated_risky_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = StrategyMemory(filepath=os.path.join(tmp, "strategy.json"))
            memory.record("브라우저 다운로드 자동화", [], False, error="timeout", failure_kind="timeout", lesson="다운로드 버튼 재탐색")
            memory.record("브라우저 다운로드 자동화", [], False, error="timeout", failure_kind="timeout", lesson="대기 시간 증가")
            memory.record("브라우저 다운로드 자동화", [], False, error="timeout", failure_kind="timeout", lesson="도메인 셀렉터 검증")

            predictor = GoalPredictor()
            with patch("agent.strategy_memory.get_strategy_memory", return_value=memory):
                result = predictor.warn_if_high_risk("브라우저 다운로드", limit=5)

            self.assertTrue(result.warning)
            self.assertEqual(result.sample_size, 3)
            self.assertTrue(any("timeout" in item for item in result.risk_factors))

    def test_goal_predictor_warns_when_double_digit_failures_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = StrategyMemory(filepath=os.path.join(tmp, "strategy.json"))
            for _ in range(10):
                memory.record("브라우저 다운로드 자동화", [], False, error="timeout", failure_kind="timeout")
            for _ in range(9):
                memory.record("브라우저 다운로드 자동화", [], True)

            predictor = GoalPredictor()
            with patch("agent.strategy_memory.get_strategy_memory", return_value=memory):
                result = predictor.warn_if_high_risk("브라우저 다운로드", limit=30)

            self.assertTrue(result.warning)
            self.assertEqual(result.sample_size, 19)
            self.assertIn("반복", result.warning)

    def test_reflection_engine_uses_llm_payload_when_available(self):
        engine = ReflectionEngine()
        run_result = SimpleNamespace(
            step_results=[
                SimpleNamespace(
                    step=SimpleNamespace(description_kr="다운로드 버튼 클릭"),
                    exec_result=SimpleNamespace(success=False, error="timeout while waiting", output=""),
                )
            ]
        )
        fake_llm = SimpleNamespace(
            chat=lambda *args, **kwargs: '{"lesson":"다운로드 버튼 위치를 먼저 재검증하세요.","avoid_patterns":["무한 대기"],"fix_suggestion":"wait_selector를 추가하세요."}'
        )
        fake_memory = SimpleNamespace(get_lessons_by_cause=lambda *args, **kwargs: ["이전 교훈"])

        with patch("agent.llm_provider.get_llm_provider", return_value=fake_llm):
            with patch("agent.strategy_memory.get_strategy_memory", return_value=fake_memory):
                result = engine.reflect("브라우저 다운로드", run_result)

        self.assertEqual(result.root_cause, "timeout")
        self.assertIn("다운로드 버튼 위치를 먼저 재검증", result.lesson)
        self.assertIn("무한 대기", result.avoid_patterns)
        self.assertIn("wait_selector", result.fix_suggestion)

    def test_learning_metrics_tracks_activation_rates_and_lift(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics = LearningMetrics(filepath=os.path.join(tmp, "learning_metrics.json"))
            metrics.record("SkillLibrary", activated=True, success=True)
            metrics.record("SkillLibrary", activated=True, success=False)
            metrics.record("SkillLibrary", activated=False, success=False)
            metrics.record("SkillLibrary", activated=False, success=True)

            component = metrics.get_component("SkillLibrary")

            self.assertEqual(component.activated_count, 2)
            self.assertEqual(component.total_with, 2)
            self.assertEqual(component.total_without, 2)
            self.assertAlmostEqual(component.success_rate_with, 0.5)
            self.assertAlmostEqual(component.success_rate_without, 0.5)
            self.assertAlmostEqual(component.lift, 0.0)
            self.assertTrue(metrics.get_report_lines(limit=1))

    def test_regression_guard_warns_only_when_drop_and_sample_are_large_enough(self):
        guard = RegressionGuard()
        fake_strategy_memory = SimpleNamespace(
            get_stats=lambda days=7, offset=0: (
                {"total": 12, "success_rate": 0.40}
                if (days, offset) == (7, 0)
                else {"total": 12, "success_rate": 0.60}
            )
        )

        with patch("agent.strategy_memory.get_strategy_memory", return_value=fake_strategy_memory):
            result = guard.evaluate()

        self.assertTrue(result.is_regression)
        self.assertIn("하락", result.alert_message)

        low_sample_memory = SimpleNamespace(
            get_stats=lambda days=7, offset=0: (
                {"total": 5, "success_rate": 0.30}
                if (days, offset) == (7, 0)
                else {"total": 20, "success_rate": 0.80}
            )
        )
        with patch("agent.strategy_memory.get_strategy_memory", return_value=low_sample_memory):
            self.assertIsNone(guard.check())


if __name__ == "__main__":
    unittest.main()

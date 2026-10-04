import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch


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
        fake_metrics = SimpleNamespace(record_llm_call=lambda *args, **kwargs: None)

        with patch("agent.llm_provider.get_llm_provider", return_value=fake_llm):
            with patch("agent.strategy_memory.get_strategy_memory", return_value=fake_memory):
                with patch("agent.learning_metrics.get_learning_metrics", return_value=fake_metrics):
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
            metrics.record(
                "SkillLibrary", activated=False, success=False,
                holdout=True, eligible=True,
            )
            metrics.record(
                "SkillLibrary", activated=False, success=True,
                holdout=True, eligible=True,
            )
            metrics.record_counter("new_skills_created", count=2)
            metrics.record_counter("python_compiled_skills", count=1)
            metrics.record_llm_call("ReflectionEngine", estimated_tokens=120)

            component = metrics.get_component("SkillLibrary")
            summary = metrics.get_summary(days=7)

            self.assertEqual(component.activated_count, 2)
            self.assertEqual(component.total_with, 2)
            self.assertEqual(component.total_without, 2)
            self.assertAlmostEqual(component.success_rate_with, 0.5)
            self.assertAlmostEqual(component.success_rate_without, 0.5)
            self.assertAlmostEqual(component.lift, 0.0)
            self.assertTrue(metrics.get_report_lines(limit=1))
            self.assertEqual(summary["new_skills_created"], 2)
            self.assertEqual(summary["python_compiled_skills"], 1)
            self.assertEqual(summary["estimated_tokens"], 120)
            self.assertEqual(summary["components"][0]["name"], "SkillLibrary")

    def test_learning_metrics_uses_random_holdout_and_wilson_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            random_values = iter([0.5, 0.5, 0.05])
            metrics = LearningMetrics(
                filepath=os.path.join(tmp, "learning_metrics.json"),
                random_func=lambda: next(random_values),
            )
            no_data_trial = {}
            self.assertFalse(
                metrics.should_activate(
                    "EpisodeMemory", eligible=False, trials=no_data_trial
                )
            )
            self.assertEqual(no_data_trial, {})

            for _ in range(9):
                metrics.record(
                    "EpisodeMemory", activated=True, success=False,
                    eligible=True,
                )
                metrics.record(
                    "EpisodeMemory", activated=False, success=True,
                    holdout=True, eligible=True,
                )

            state = next(
                row for row in metrics.get_component_diagnostics()
                if row["name"] == "EpisodeMemory"
            )
            self.assertEqual(state["state"], "pending")
            first_trial = {}
            self.assertTrue(
                metrics.should_activate("EpisodeMemory", trials=first_trial)
            )
            self.assertFalse(first_trial["EpisodeMemory"]["holdout"])

            metrics.record(
                "EpisodeMemory", activated=True, success=False, eligible=True
            )
            metrics.record(
                "EpisodeMemory", activated=False, success=True,
                holdout=True, eligible=True,
            )
            state = next(
                row for row in metrics.get_component_diagnostics()
                if row["name"] == "EpisodeMemory"
            )
            self.assertEqual(state["state"], "disabled")
            self.assertLess(state["lift_upper"], 0)

            holdout_trial = {}
            self.assertFalse(
                metrics.should_activate("EpisodeMemory", trials=holdout_trial)
            )
            self.assertTrue(holdout_trial["EpisodeMemory"]["holdout"])
            exploration_trial = {}
            self.assertTrue(
                metrics.should_activate("EpisodeMemory", trials=exploration_trial)
            )
            self.assertFalse(exploration_trial["EpisodeMemory"]["holdout"])

    def test_learning_metrics_keeps_legacy_data_out_of_randomized_lift(self):
        with tempfile.TemporaryDirectory() as tmp:
            filepath = os.path.join(tmp, "learning_metrics.json")
            day = datetime.now().date().isoformat()
            with open(filepath, "w", encoding="utf-8") as handle:
                json.dump({
                    "components": {
                        "SkillLibrary": {
                            "name": "SkillLibrary",
                            "activated_count": 2,
                            "success_with": 1,
                            "total_with": 2,
                            "success_without": 1,
                            "total_without": 3,
                        }
                    },
                    "daily_components": {
                        day: {
                            "SkillLibrary": {
                                "success_with": 1,
                                "total_with": 2,
                                "success_without": 1,
                                "total_without": 3,
                            }
                        }
                    },
                }, handle)

            metrics = LearningMetrics(filepath=filepath)
            component = metrics.get_component("SkillLibrary")
            state = next(
                row for row in metrics.get_component_diagnostics()
                if row["name"] == "SkillLibrary"
            )

            self.assertFalse(component.holdout)
            self.assertEqual(component.total_with, 2)
            self.assertEqual(component.trial_total_with, 0)
            self.assertEqual(component.trial_success_with, 0)
            self.assertEqual(component.trial_total_holdout, 0)
            self.assertFalse(
                metrics._daily_components[day]["SkillLibrary"]["holdout"]
            )
            self.assertEqual(state["state"], "pending")
            self.assertEqual(state["applied_samples"], 0)
            self.assertEqual(state["holdout_samples"], 0)

    def test_eligible_non_holdout_assignment_counts_as_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics = LearningMetrics(filepath=os.path.join(tmp, "metrics.json"))
            metrics.record(
                "StrategyMemory",
                activated=False,
                success=True,
                holdout=False,
                eligible=True,
            )

            component = metrics.get_component("StrategyMemory")

            self.assertEqual(component.trial_total_with, 1)
            self.assertEqual(component.trial_success_with, 1)
            self.assertEqual(component.trial_total_holdout, 0)

    def test_learning_metrics_only_uses_the_recent_sixty_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics = LearningMetrics(filepath=os.path.join(tmp, "metrics.json"))
            old_day = (datetime.now().date() - timedelta(days=60)).isoformat()
            metrics._daily_components[old_day] = {
                "EpisodeMemory": {
                    "trial_total_with": 20,
                    "trial_success_with": 0,
                    "trial_total_holdout": 20,
                    "trial_success_holdout": 20,
                }
            }

            state = next(
                row for row in metrics.get_component_diagnostics()
                if row["name"] == "EpisodeMemory"
            )

            self.assertEqual(state["state"], "pending")
            self.assertEqual(state["applied_samples"], 0)
            self.assertEqual(state["holdout_samples"], 0)

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

    def test_learning_metrics_and_planner_feedback_keep_old_file_when_atomic_replace_fails(self):
        from agent.planner_feedback import PlannerFeedbackLoop

        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = os.path.join(tmp, "learning_metrics.json")
            stats_path = os.path.join(tmp, "planner_stats.json")
            metrics = LearningMetrics(filepath=metrics_path)
            metrics._save_locked()
            with patch("core.resource_manager.ResourceManager.get_writable_path", return_value=stats_path):
                feedback = PlannerFeedbackLoop()
            feedback.stats = {"click": {"success": 1, "fail": 0, "durations": []}}
            feedback._save()
            with open(metrics_path, encoding="utf-8") as handle:
                metrics_before = handle.read()
            with open(stats_path, encoding="utf-8") as handle:
                stats_before = handle.read()

            feedback.stats = {"changed": {"success": 0, "fail": 1, "durations": []}}
            with patch("core.atomic_io.os.replace", side_effect=OSError("교체 실패")):
                metrics.record_counter("changed")
                feedback._save()

            with open(metrics_path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), metrics_before)
            with open(stats_path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), stats_before)
            self.assertEqual(sorted(os.listdir(tmp)), ["learning_metrics.json", "planner_stats.json"])


if __name__ == "__main__":
    unittest.main()

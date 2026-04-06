import importlib
import os
import sys
import threading
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class SingletonFactoryTests(unittest.TestCase):
    def _assert_singleton_factory_thread_safe(
        self,
        module_name: str,
        singleton_name: str,
        class_name: str,
        getter_name: str,
    ) -> None:
        module = importlib.import_module(module_name)
        original_singleton = getattr(module, singleton_name)
        original_class = getattr(module, class_name)
        created = []

        class FakeSingleton:
            def __init__(self, *args, **kwargs):
                created.append((args, kwargs))

        setattr(module, singleton_name, None)
        setattr(module, class_name, FakeSingleton)
        try:
            instances = []
            append_lock = threading.Lock()

            def _worker() -> None:
                instance = getattr(module, getter_name)()
                with append_lock:
                    instances.append(instance)

            threads = [threading.Thread(target=_worker) for _ in range(12)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(len(created), 1, module_name)
            self.assertEqual(len({id(instance) for instance in instances}), 1, module_name)
        finally:
            setattr(module, class_name, original_class)
            setattr(module, singleton_name, original_singleton)

    def test_thread_safe_singleton_factories_create_one_instance(self):
        cases = [
            ("agent.few_shot_injector", "_injector", "FewShotInjector", "get_few_shot_injector"),
            ("agent.goal_predictor", "_predictor", "GoalPredictor", "get_goal_predictor"),
            ("agent.learning_metrics", "_metrics", "LearningMetrics", "get_learning_metrics"),
            ("agent.llm_router", "_router", "LLMRouter", "get_llm_router"),
            ("agent.planner_feedback", "_feedback_loop", "PlannerFeedbackLoop", "get_planner_feedback_loop"),
            ("agent.reflection_engine", "_engine", "ReflectionEngine", "get_reflection_engine"),
            ("agent.safety_checker", "_checker_instance", "SafetyChecker", "get_safety_checker"),
            ("agent.skill_optimizer", "_optimizer", "SkillOptimizer", "get_skill_optimizer"),
            ("agent.weekly_report", "_weekly_report", "WeeklyReport", "get_weekly_report"),
            ("memory.memory_consolidator", "_consolidator", "MemoryConsolidator", "get_memory_consolidator"),
            ("memory.memory_index", "_index", "MemoryIndex", "get_memory_index"),
            ("memory.user_profile_engine", "_engine", "UserProfileEngine", "get_user_profile_engine"),
        ]
        for case in cases:
            with self.subTest(module=case[0]):
                self._assert_singleton_factory_thread_safe(*case)


if __name__ == "__main__":
    unittest.main()

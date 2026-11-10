import importlib
import threading
import unittest
from unittest.mock import Mock

from agent.confirmation_manager import ConfirmationManager, remote_approval_scope
from agent.safety_checker import DangerLevel, SafetyReport


_MODULE_LOADERS = {
    "agent.confirmation_manager": lambda: importlib.import_module("agent.confirmation_manager"),
    "agent.few_shot_injector": lambda: importlib.import_module("agent.few_shot_injector"),
    "agent.goal_predictor": lambda: importlib.import_module("agent.goal_predictor"),
    "agent.learning_metrics": lambda: importlib.import_module("agent.learning_metrics"),
    "agent.llm_router": lambda: importlib.import_module("agent.llm_router"),
    "agent.planner_feedback": lambda: importlib.import_module("agent.planner_feedback"),
    "agent.reflection_engine": lambda: importlib.import_module("agent.reflection_engine"),
    "agent.safety_checker": lambda: importlib.import_module("agent.safety_checker"),
    "agent.skill_optimizer": lambda: importlib.import_module("agent.skill_optimizer"),
    "agent.weekly_report": lambda: importlib.import_module("agent.weekly_report"),
    "memory.memory_consolidator": lambda: importlib.import_module("memory.memory_consolidator"),
    "memory.memory_index": lambda: importlib.import_module("memory.memory_index"),
    "memory.user_profile_engine": lambda: importlib.import_module("memory.user_profile_engine"),
}


class ConfirmationManagerTests(unittest.TestCase):
    def setUp(self):
        self.manager = object.__new__(ConfirmationManager)
        self.manager._bridge = Mock()
        self.report = SafetyReport(DangerLevel.CAUTION, summary="danger")

        def show(action, report, holder):
            holder["result"] = True
            holder["event"].set()

        self.manager._bridge.request_dialog.emit.side_effect = show

    def test_local_confirmation_uses_existing_dialog(self):
        self.assertTrue(self.manager.request_confirmation("local", self.report))
        self.manager._bridge.request_dialog.emit.assert_called_once()

    def test_remote_scope_is_cleared_and_not_inherited_by_threads(self):
        remote = Mock(return_value=False)
        results = []
        with remote_approval_scope(remote):
            self.assertFalse(self.manager.request_confirmation("remote", self.report))
            worker = threading.Thread(target=lambda: results.append(
                self.manager.request_confirmation("local thread", self.report)))
            worker.start()
            worker.join(2)
        self.assertEqual(results, [True])
        self.assertTrue(self.manager.request_confirmation("local", self.report))
        remote.assert_called_once_with("remote", self.report)
        self.assertEqual(self.manager._bridge.request_dialog.emit.call_count, 2)

    def test_remote_error_denies_without_local_fallback(self):
        with remote_approval_scope(Mock(side_effect=RuntimeError("failed"))):
            self.assertFalse(self.manager.request_confirmation("remote", self.report))
        self.manager._bridge.request_dialog.emit.assert_not_called()

    def test_remote_scope_is_cleared_after_error(self):
        with self.assertRaises(RuntimeError):
            with remote_approval_scope(Mock(return_value=False)):
                raise RuntimeError("command failed")
        self.assertTrue(self.manager.request_confirmation("local", self.report))


class SingletonFactoryTests(unittest.TestCase):
    def _assert_singleton_factory_thread_safe(
        self,
        module_name: str,
        singleton_name: str,
        class_name: str,
        getter_name: str,
    ) -> None:
        module = _MODULE_LOADERS[module_name]()
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
            ("agent.confirmation_manager", "_manager_instance", "ConfirmationManager", "get_confirmation_manager"),
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

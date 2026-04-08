import threading
import time
import unittest
from types import SimpleNamespace


from agent.learning_engine import LearningEngine


class LearningEngineTests(unittest.TestCase):
    def test_schedule_post_run_update_uses_daemon_thread(self):
        event = threading.Event()
        engine = LearningEngine(is_developer_goal_fn=lambda goal: False)

        def fake_update(goal, run_result, duration_ms, policy_summary=""):
            event.set()

        engine._post_run_update_safe = fake_update
        engine.schedule_post_run_update(
            "테스트 목표",
            SimpleNamespace(step_results=[], achieved=True, learning_components={}),
            123,
        )

        self.assertIsNotNone(engine._post_run_thread)
        self.assertTrue(engine._post_run_thread.daemon)
        engine.wait_for_background_thread()
        self.assertTrue(event.is_set())

    def test_wait_for_background_thread_joins_running_thread(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        engine = LearningEngine(is_developer_goal_fn=lambda goal: False)

        def fake_update(goal, run_result, duration_ms, policy_summary=""):
            started.set()
            release.wait(timeout=2.0)
            finished.set()

        engine._post_run_update_safe = fake_update
        engine.schedule_post_run_update(
            "테스트 목표",
            SimpleNamespace(step_results=[], achieved=True, learning_components={}),
            123,
        )

        self.assertTrue(started.wait(timeout=1.0))
        self.assertTrue(engine._post_run_thread.is_alive())
        release.set()
        engine.wait_for_background_thread()

        self.assertTrue(finished.is_set())
        self.assertFalse(engine._post_run_thread.is_alive())

    def test_schedule_post_run_update_runs_inline_when_background_disabled(self):
        engine = LearningEngine(
            is_developer_goal_fn=lambda goal: False,
            background_updates_enabled=False,
        )
        calls = []

        def fake_update(goal, run_result, duration_ms, policy_summary=""):
            calls.append((goal, duration_ms, policy_summary))

        engine._post_run_update = fake_update

        before = time.monotonic()
        engine.schedule_post_run_update(
            "즉시 실행 목표",
            SimpleNamespace(step_results=[], achieved=True, learning_components={}),
            456,
        )
        elapsed = time.monotonic() - before

        self.assertEqual(calls, [("즉시 실행 목표", 456, "")])
        self.assertIsNone(engine._post_run_thread)
        self.assertLess(elapsed, 0.5)


if __name__ == "__main__":
    unittest.main()

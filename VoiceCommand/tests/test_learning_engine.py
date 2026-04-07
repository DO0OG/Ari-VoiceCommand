import os
import sys
import threading
import unittest
from types import SimpleNamespace


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

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


if __name__ == "__main__":
    unittest.main()

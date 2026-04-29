import threading
import time
import unittest

from agent.task_queue import AgentTaskQueue


class AgentTaskQueueTests(unittest.TestCase):
    def test_higher_priority_task_runs_first(self):
        queue = AgentTaskQueue(max_workers=1)
        self.addCleanup(queue.shutdown)
        first_started = threading.Event()
        release_first = threading.Event()
        order = []

        def slow_task(cancel_event):
            del cancel_event
            first_started.set()
            release_first.wait(timeout=1)
            order.append("slow")

        slow_id = queue.submit("slow", slow_task, priority=50)
        self.assertTrue(first_started.wait(timeout=1))
        urgent_id = queue.submit("urgent", lambda _event: order.append("urgent"), priority=1)
        normal_id = queue.submit("normal", lambda _event: order.append("normal"), priority=10)

        release_first.set()
        self._wait_for_status(queue, urgent_id, "completed")
        self._wait_for_status(queue, normal_id, "completed")
        self._wait_for_status(queue, slow_id, "completed")

        self.assertEqual(order, ["slow", "urgent", "normal"])

    def test_cancel_running_task_sets_event(self):
        queue = AgentTaskQueue(max_workers=1)
        self.addCleanup(queue.shutdown)
        started = threading.Event()

        def cancellable(cancel_event):
            started.set()
            while not cancel_event.is_set():
                time.sleep(0.01)
            return "noticed"

        task_id = queue.submit("cancel me", cancellable)
        self.assertTrue(started.wait(timeout=1))
        self.assertEqual(queue.cancel_current(task_id), 1)
        self._wait_for_status(queue, task_id, "cancelled")
        self.assertEqual(queue.result(task_id).result, "noticed")

    def _wait_for_status(self, queue, task_id, expected):
        deadline = time.time() + 2
        while time.time() < deadline:
            if queue.status(task_id) == expected:
                return
            time.sleep(0.01)
        self.fail(f"{task_id} did not reach {expected}; got {queue.status(task_id)}")


if __name__ == "__main__":
    unittest.main()

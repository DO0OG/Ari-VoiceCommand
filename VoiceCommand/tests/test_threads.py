import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.threads import TTSThread


class TTSThreadTests(unittest.TestCase):
    def test_collect_batch_merges_immediately_queued_messages(self):
        thread = TTSThread()
        thread.queue.put("둘째 문장입니다.")
        thread.queue.put("셋째 문장입니다.")

        combined, task_count, stop_requested = thread._collect_batch("첫째 문장입니다.")

        self.assertEqual(
            combined,
            "첫째 문장입니다. 둘째 문장입니다. 셋째 문장입니다.",
        )
        self.assertEqual(task_count, 3)
        self.assertFalse(stop_requested)

    def test_collect_batch_preserves_stop_signal(self):
        thread = TTSThread()
        thread.queue.put(None)

        combined, task_count, stop_requested = thread._collect_batch("안내 멘트입니다.")

        self.assertEqual(combined, "안내 멘트입니다.")
        self.assertEqual(task_count, 2)
        self.assertTrue(stop_requested)


if __name__ == "__main__":
    unittest.main()

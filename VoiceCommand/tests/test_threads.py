import unittest
from unittest.mock import patch


from core.threads import TTSThread, _wait_for_tts_playback_completion


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

    def test_wait_for_tts_playback_completion_uses_backoff(self):
        checks = iter([True, True, True, False])
        slept = []
        now_values = iter([0.0, 0.01, 0.08, 0.2])

        completed = _wait_for_tts_playback_completion(
            is_tts_playing=lambda: next(checks),
            sleep_fn=lambda seconds: slept.append(round(seconds, 3)),
            now_fn=lambda: next(now_values),
        )

        self.assertTrue(completed)
        self.assertEqual(slept, [0.05, 0.075, 0.113])

    def test_wait_for_tts_playback_completion_times_out(self):
        with patch("core.threads.logging.warning") as mocked_warning:
            completed = _wait_for_tts_playback_completion(
                is_tts_playing=lambda: True,
                timeout=0.1,
                sleep_fn=lambda _seconds: None,
                now_fn=iter([0.0, 0.05, 0.11]).__next__,
            )

        self.assertFalse(completed)
        mocked_warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()

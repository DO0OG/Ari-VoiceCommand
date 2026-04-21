import unittest
from unittest.mock import patch


from services.timer_manager import TimerManager


class _FakeTimer:
    def __init__(self, delay, callback):
        self.delay = delay
        self.callback = callback
        self.daemon = False
        self.cancelled = False
        self.started = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


class TimerManagerTests(unittest.TestCase):
    def test_set_timer_assigns_auto_name_and_lists_remaining_seconds(self):
        messages = []
        with patch("services.timer_manager.threading.Timer", side_effect=lambda delay, cb: _FakeTimer(delay, cb)):
            manager = TimerManager(tts_callback=messages.append)
            name = manager.set_timer(1.5)
            timers = manager.list_timers()

        self.assertEqual(name, "타이머 1")
        self.assertEqual(timers[0]["name"], "타이머 1")
        self.assertGreater(timers[0]["remaining_seconds"], 0)
        self.assertIn("1분 30초 타이머를 설정했습니다.", messages[0])

    def test_set_timer_replaces_same_named_timer(self):
        timers = []

        def _factory(delay, cb):
            timer = _FakeTimer(delay, cb)
            timers.append(timer)
            return timer

        with patch("services.timer_manager.threading.Timer", side_effect=_factory):
            manager = TimerManager(tts_callback=lambda message: None)
            manager.set_timer(1, name="요리")
            manager.set_timer(2, name="요리")

        self.assertTrue(timers[0].cancelled)
        self.assertFalse(timers[1].cancelled)
        self.assertEqual(len(manager.list_timers()), 1)

    def test_cancel_timer_without_name_cancels_latest_timer(self):
        with patch("services.timer_manager.threading.Timer", side_effect=lambda delay, cb: _FakeTimer(delay, cb)):
            manager = TimerManager(tts_callback=lambda message: None)
            manager.set_timer(1, name="첫번째")
            manager.set_timer(2, name="두번째")

            cancelled = manager.cancel_timer()

        self.assertTrue(cancelled)
        self.assertEqual([item["name"] for item in manager.list_timers()], ["첫번째"])

    def test_parse_timer_command_supports_english_and_japanese_units(self):
        manager = TimerManager(tts_callback=lambda message: None)

        english = manager.parse_timer_command("set timer for 1 hour 2 minutes 3 seconds")
        japanese = manager.parse_timer_command("1時間 5分 10秒 タイマー")

        self.assertAlmostEqual(english or 0.0, 62.05, places=2)
        self.assertAlmostEqual(japanese or 0.0, 65.1666, places=2)


if __name__ == "__main__":
    unittest.main()

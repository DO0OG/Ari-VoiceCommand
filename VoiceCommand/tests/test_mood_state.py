import json
import os
import tempfile
import unittest

from core.mood_state import MoodState


class MoodStateTests(unittest.TestCase):
    def test_decay_is_applied_after_restart_without_saving_event_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "mood_state.json")
            now = [1_000.0]
            mood = MoodState(path=path, clock=lambda: now[0])
            mood.record_interaction(praised=True)

            with open(path, "r", encoding="utf-8") as handle:
                saved = json.load(handle)

            self.assertEqual(set(saved), {"valence", "arousal", "updated_at"})
            restarted = MoodState(
                path=path,
                clock=lambda: now[0] + 2 * 60 * 60,
            )
            valence, arousal = restarted.values()

        self.assertAlmostEqual(valence, 0.12)
        self.assertAlmostEqual(arousal, 0.055)

    def test_long_return_enables_one_big_motion_per_minute(self):
        with tempfile.TemporaryDirectory() as tmp:
            mood = MoodState(
                path=os.path.join(tmp, "mood_state.json"),
                clock=lambda: 1_000.0,
            )
            mood.record_away_return(30 * 60)

            self.assertTrue(mood.claim_big_motion(now=1_000.0))
            self.assertFalse(mood.claim_big_motion(now=1_030.0))
            self.assertTrue(mood.claim_big_motion(now=1_060.0))

    def test_task_success_and_failure_change_character_mood(self):
        with tempfile.TemporaryDirectory() as tmp:
            positive = MoodState(
                path=os.path.join(tmp, "positive.json"),
                clock=lambda: 1_000.0,
            )
            negative = MoodState(
                path=os.path.join(tmp, "negative.json"),
                clock=lambda: 1_000.0,
            )

            positive.record_task_result(True)
            negative.record_task_result(False)

        self.assertGreater(positive.values()[0], 0.0)
        self.assertLess(negative.values()[0], 0.0)

    def test_corrupt_state_is_backed_up_and_defaults_to_neutral(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "mood_state.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{broken")

            mood = MoodState(path=path)
            backups = [name for name in os.listdir(tmp) if ".corrupt-" in name]

        self.assertEqual(mood.values(), (0.0, 0.0))
        self.assertEqual(len(backups), 1)


if __name__ == "__main__":
    unittest.main()

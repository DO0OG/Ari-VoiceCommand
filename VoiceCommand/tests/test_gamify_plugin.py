import tempfile
import unittest
from pathlib import Path

from plugins.ari_gamify import GamifyEngine, XP_TABLE, _level_for_xp


class _FixedRandom:
    def choice(self, items):
        return items[0]

    def randint(self, low, high):
        del high
        return low


class GamifyPluginTests(unittest.TestCase):
    def test_level_for_xp_uses_threshold_boundaries(self):
        self.assertEqual(_level_for_xp(0), 0)
        self.assertEqual(_level_for_xp(49), 0)
        self.assertEqual(_level_for_xp(50), 1)
        self.assertEqual(_level_for_xp(1000), 5)

    def test_command_event_adds_xp_and_first_command_achievement(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = GamifyEngine(str(Path(tmp) / "state.json"), rng=_FixedRandom())
            before = engine.state["xp"]

            events = engine.handle_command({"success": True, "command_type": "weather"})

            self.assertGreaterEqual(engine.state["xp"], before + XP_TABLE["voice_command"])
            self.assertIn("first_command", engine.state["achievements"])
            self.assertIn("first_command", events)

    def test_number_guess_win_updates_stats_and_xp(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = GamifyEngine(str(Path(tmp) / "state.json"), rng=_FixedRandom())
            engine.start_number_guess()
            before = engine.state["xp"]

            won, message = engine.guess_number(1)

            self.assertTrue(won)
            self.assertIn("정답", message)
            self.assertEqual(engine.state["minigame_stats"]["number_guess"]["wins"], 1)
            self.assertGreaterEqual(engine.state["xp"], before + XP_TABLE["minigame_win"])


if __name__ == "__main__":
    unittest.main()

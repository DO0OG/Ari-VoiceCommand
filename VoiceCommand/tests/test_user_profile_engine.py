import json
import os
import tempfile
import unittest

from memory.user_context import UserContextManager
from memory.user_profile_engine import UserProfile, UserProfileEngine


class UserProfileEngineTests(unittest.TestCase):
    def test_corrupt_profile_is_backed_up_before_defaults_are_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "user_profile.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{broken")
            engine = UserProfileEngine.__new__(UserProfileEngine)
            engine.file_path = path

            profile = engine._load()

            self.assertEqual(profile, UserProfile())
            backups = [name for name in os.listdir(tmp) if ".corrupt-" in name]
            self.assertEqual(len(backups), 1)
            with open(os.path.join(tmp, backups[0]), encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "{broken")

    @staticmethod
    def _context(tmp):
        return UserContextManager(context_file=os.path.join(tmp, "user_context.json"))

    @staticmethod
    def _read_bytes(path):
        with open(path, "rb") as handle:
            return handle.read()

    def test_legacy_profile_is_imported_and_left_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy_path = os.path.join(tmp, "user_profile.json")
            legacy = {
                "expertise_areas": {"coding": 0.5},
                "response_style": "brief",
                "active_hours": list(range(30)),
                "frequent_goals": ["weather"],
                "last_profiled": "2026-01-01T00:00:00",
            }
            with open(legacy_path, "w", encoding="utf-8") as handle:
                json.dump(legacy, handle)
            before = self._read_bytes(legacy_path)

            engine = UserProfileEngine(self._context(tmp))

            self.assertEqual(engine.get_profile().expertise_areas, {"coding": 0.5})
            self.assertEqual(engine.get_profile().active_hours, list(range(30)))
            self.assertEqual(engine.get_profile().frequent_goals, ["weather"])

            engine.update("hello", command_type="timer")

            self.assertEqual(self._read_bytes(legacy_path), before)
            with open(os.path.join(tmp, "user_context.json"), encoding="utf-8") as handle:
                saved = json.load(handle)["profile"]
            self.assertEqual(saved["frequent_goals"], ["timer", "weather"])
            reloaded = UserProfileEngine(self._context(tmp))
            self.assertEqual(reloaded.get_profile(), engine.get_profile())

    def test_existing_profile_key_ignores_legacy_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "user_profile.json"), "w", encoding="utf-8") as handle:
                json.dump({"frequent_goals": ["legacy"]}, handle)
            with open(os.path.join(tmp, "user_context.json"), "w", encoding="utf-8") as handle:
                json.dump({"profile": {"frequent_goals": ["current"]}}, handle)

            engine = UserProfileEngine(self._context(tmp))

            self.assertEqual(engine.get_profile().frequent_goals, ["current"])

    def test_profile_update_keeps_other_context_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = self._context(tmp)
            context.context["facts"] = {
                "job": context._normalize_fact_entry(
                    {"value": "developer", "updated_at": "2026-01-01T00:00:00"}
                )
            }
            context.context["preferences"] = {"food": {"kimchi": 2}}
            context.context["command_frequency"] = {"timer": 3}
            context.context["custom_key"] = {"keep": [1, 2]}
            context.update_bio("location", "Seoul")
            with open(context.context_file, encoding="utf-8") as handle:
                before = json.load(handle)

            UserProfileEngine(self._context(tmp)).update("hello", command_type="timer")

            with open(context.context_file, encoding="utf-8") as handle:
                after = json.load(handle)
            self.assertIn("profile", after)
            after.pop("profile")
            self.assertEqual(after, before)

    def test_corrupt_legacy_profile_starts_with_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy_path = os.path.join(tmp, "user_profile.json")
            with open(legacy_path, "w", encoding="utf-8") as handle:
                handle.write("{broken")
            before = self._read_bytes(legacy_path)

            engine = UserProfileEngine(self._context(tmp))

            self.assertEqual(engine.get_profile(), UserProfile())
            self.assertEqual(self._read_bytes(legacy_path), before)


if __name__ == "__main__":
    unittest.main()

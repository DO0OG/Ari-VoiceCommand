import os
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()

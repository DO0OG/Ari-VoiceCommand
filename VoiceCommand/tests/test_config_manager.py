import json
import os
import tempfile
import unittest
from unittest.mock import patch

from core.config_manager import ConfigManager


class ConfigManagerTests(unittest.TestCase):
    def test_normalize_settings_rejects_bool_for_int_field(self):
        with patch.object(
            ConfigManager,
            "DEFAULT_SETTINGS",
            {
                "stt_energy_threshold": 300,
                "weekly_report_enabled": False,
                "agent_response_cache_ttl": 600,
            },
        ):
            normalized = ConfigManager._normalize_settings(
                {
                    "stt_energy_threshold": True,
                    "weekly_report_enabled": False,
                    "agent_response_cache_ttl": "fast",
                }
            )

        self.assertEqual(normalized["stt_energy_threshold"], 300)
        self.assertEqual(normalized["agent_response_cache_ttl"], 600)

    def test_normalize_settings_rejects_non_bool_for_bool_field(self):
        with patch.object(
            ConfigManager,
            "DEFAULT_SETTINGS",
            {"stt_energy_threshold": 300, "weekly_report_enabled": False},
        ):
            normalized = ConfigManager._normalize_settings(
                {"stt_energy_threshold": 300, "weekly_report_enabled": 1}
            )

        self.assertFalse(normalized["weekly_report_enabled"])


    def test_save_settings_keeps_previous_file_when_write_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            original = {"stt_energy_threshold": 300}
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(original, handle)

            with patch("core.config_manager._settings_path", return_value=path):
                with patch("core.config_manager.json.dump", side_effect=OSError("disk full")):
                    saved = ConfigManager.save_settings({"stt_energy_threshold": 500})

            self.assertFalse(saved)
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), original)
            self.assertEqual(os.listdir(tmp), ["settings.json"])

    def test_local_decision_contradictions_are_normalized(self):
        from core.settings_schema import normalize_local_decision_settings

        cases = (
            ({"local_decision_mode": "adaptive", "local_decision_direct_execution": True}, "fast", True),
            ({"local_decision_mode": "adaptive", "local_decision_direct_execution": False}, "off", False),
            ({"local_decision_mode": "turbo", "local_decision_direct_execution": True}, "off", False),
            ({"local_decision_mode": "shadow", "local_decision_direct_execution": True}, "shadow", False),
            ({"local_decision_mode": "fast", "local_decision_direct_execution": False}, "fast", False),
        )
        for settings, mode, direct in cases:
            with self.subTest(settings=dict(settings)):
                normalize_local_decision_settings(settings)
                self.assertEqual(settings["local_decision_mode"], mode)
                self.assertIs(settings["local_decision_direct_execution"], direct)

    def test_old_default_shadow_moves_to_off_once_and_later_choice_stays(self):
        previous = ConfigManager._cached_settings
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"local_decision_mode": "shadow", "local_decision_direct_execution": False}, handle)
            try:
                with patch("core.config_manager._settings_path", return_value=path):
                    ConfigManager._cached_settings = None
                    self.assertEqual(ConfigManager.get("local_decision_mode"), "off")
                    with open(path, encoding="utf-8") as handle:
                        stored = json.load(handle)
                    self.assertEqual(stored["local_decision_mode"], "off")
                    self.assertEqual(stored["local_decision_settings_version"], 2)

                    stored["local_decision_mode"] = "shadow"
                    with open(path, "w", encoding="utf-8") as handle:
                        json.dump(stored, handle)
                    ConfigManager._cached_settings = None
                    self.assertEqual(ConfigManager.get("local_decision_mode"), "shadow")
            finally:
                ConfigManager._cached_settings = previous

    def test_explicit_fast_choice_survives_migration(self):
        from core.settings_schema import migrate_local_decision_settings

        settings = {"local_decision_mode": "fast", "local_decision_direct_execution": True}
        migrate_local_decision_settings(settings)
        self.assertEqual(settings["local_decision_mode"], "fast")
        self.assertTrue(settings["local_decision_direct_execution"])


if __name__ == "__main__":
    unittest.main()

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

    def test_v2_default_off_moves_to_fast_once_and_shadow_choice_stays(self):
        previous = ConfigManager._cached_settings
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({
                    "local_decision_mode": "off",
                    "local_decision_direct_execution": False,
                    "local_decision_settings_version": 2,
                }, handle)
            try:
                with patch("core.config_manager._settings_path", return_value=path):
                    ConfigManager._cached_settings = None
                    self.assertEqual(ConfigManager.get("local_decision_mode"), "fast")
                    self.assertIs(ConfigManager.get("local_decision_direct_execution"), True)
                    with open(path, encoding="utf-8") as handle:
                        stored = json.load(handle)
                    self.assertEqual(stored["local_decision_mode"], "fast")
                    self.assertTrue(stored["local_decision_direct_execution"])
                    self.assertEqual(stored["local_decision_settings_version"], 3)

                    stored["local_decision_mode"] = "off"
                    stored["local_decision_direct_execution"] = False
                    with open(path, "w", encoding="utf-8") as handle:
                        json.dump(stored, handle)
                    ConfigManager._cached_settings = None
                    self.assertEqual(ConfigManager.get("local_decision_mode"), "off")

                    stored["local_decision_mode"] = "shadow"
                    stored["local_decision_settings_version"] = 2
                    with open(path, "w", encoding="utf-8") as handle:
                        json.dump(stored, handle)
                    ConfigManager._cached_settings = None
                    self.assertEqual(ConfigManager.get("local_decision_mode"), "shadow")
                    self.assertFalse(ConfigManager.get("local_decision_direct_execution"))
                    with open(path, encoding="utf-8") as handle:
                        stored = json.load(handle)
                    self.assertEqual(stored["local_decision_settings_version"], 3)
            finally:
                ConfigManager._cached_settings = previous

    def test_stt_migration_resets_only_unusable_threshold(self):
        from core.settings_schema import migrate_stt_settings

        cases = (
            ({"stt_energy_threshold": 0}, 300),
            ({"stt_energy_threshold": 0, "stt_settings_version": 1}, 300),
            ({"stt_energy_threshold": "x"}, 300),
            ({"stt_energy_threshold": "NaN"}, 300),
            ({"stt_energy_threshold": 7}, 7),
            ({"stt_energy_threshold": 15, "stt_settings_version": 1}, 15),
        )
        for settings, expected in cases:
            with self.subTest(settings=settings):
                self.assertTrue(migrate_stt_settings(settings))
                self.assertEqual(settings["stt_energy_threshold"], expected)
                self.assertEqual(settings["stt_settings_version"], 2)

        reenabled = {"stt_dynamic_energy": True, "stt_settings_version": 1}
        migrate_stt_settings(reenabled)
        self.assertTrue(reenabled["stt_dynamic_energy"])
        self.assertFalse(migrate_stt_settings({"stt_energy_threshold": 0, "stt_settings_version": 2}))

    def test_legacy_auto_energy_is_disabled_once_without_changing_manual_threshold(self):
        previous = ConfigManager._cached_settings
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"stt_dynamic_energy": True, "stt_energy_threshold": 7}, handle)
            try:
                with patch("core.config_manager._settings_path", return_value=path):
                    ConfigManager._cached_settings = None
                    self.assertFalse(ConfigManager.get("stt_dynamic_energy"))
                    self.assertEqual(ConfigManager.get("stt_energy_threshold"), 7)
                    with open(path, encoding="utf-8") as handle:
                        stored = json.load(handle)
                    self.assertFalse(stored["stt_dynamic_energy"])
                    self.assertEqual(stored["stt_energy_threshold"], 7)
                    self.assertEqual(stored["stt_settings_version"], 2)

                    stored["stt_dynamic_energy"] = True
                    with open(path, "w", encoding="utf-8") as handle:
                        json.dump(stored, handle)
                    ConfigManager._cached_settings = None
                    self.assertTrue(ConfigManager.get("stt_dynamic_energy"))
            finally:
                ConfigManager._cached_settings = previous

    def test_shadow_stays_diagnostic_mode_across_settings_migrations(self):
        from core.settings_schema import migrate_local_decision_settings

        for version in (None, 1, 2):
            with self.subTest(version=version):
                settings = {
                    "local_decision_mode": "shadow",
                    "local_decision_direct_execution": False,
                }
                if version is not None:
                    settings["local_decision_settings_version"] = version

                migrate_local_decision_settings(settings)

                self.assertEqual(settings["local_decision_mode"], "shadow")
                self.assertFalse(settings["local_decision_direct_execution"])
                self.assertEqual(settings["local_decision_settings_version"], 3)

    def test_explicit_fast_choice_survives_migration(self):
        from core.settings_schema import migrate_local_decision_settings

        settings = {"local_decision_mode": "fast", "local_decision_direct_execution": True}
        migrate_local_decision_settings(settings)
        self.assertEqual(settings["local_decision_mode"], "fast")
        self.assertTrue(settings["local_decision_direct_execution"])


if __name__ == "__main__":
    unittest.main()

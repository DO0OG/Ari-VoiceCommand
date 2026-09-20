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


if __name__ == "__main__":
    unittest.main()

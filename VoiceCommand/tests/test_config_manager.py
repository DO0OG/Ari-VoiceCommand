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


if __name__ == "__main__":
    unittest.main()

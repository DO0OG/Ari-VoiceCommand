import unittest
from unittest.mock import patch

from agent.response_cache import ResponseCache


class ResponseCacheTests(unittest.TestCase):
    def test_from_config_uses_flat_agent_cache_settings(self):
        with patch(
            "core.config_manager.ConfigManager.load_settings",
            return_value={
                "agent_response_cache_ttl": 123,
                "agent_response_cache_max_size": 7,
            },
        ):
            cache = ResponseCache.from_config()

        self.assertEqual(cache.ttl_seconds, 123)
        self.assertEqual(cache.max_items, 7)

    def test_from_config_supports_nested_agent_settings(self):
        with patch(
            "core.config_manager.ConfigManager.load_settings",
            return_value={"agent": {"response_cache_ttl": 321, "response_cache_max_size": 9}},
        ):
            cache = ResponseCache.from_config()

        self.assertEqual(cache.ttl_seconds, 321)
        self.assertEqual(cache.max_items, 9)

    def test_invalid_values_fall_back_to_defaults(self):
        cache = ResponseCache(max_items=0, ttl_seconds="bad")

        self.assertEqual(cache.max_items, 50)
        self.assertEqual(cache.ttl_seconds, 600)


if __name__ == "__main__":
    unittest.main()

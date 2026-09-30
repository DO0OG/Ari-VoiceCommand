import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent import llm_provider
from core import core_manager


class _Client:
    def __init__(self, error=None):
        self.error = error
        self.closed = False

    def close(self):
        self.closed = True
        if self.error:
            raise self.error


class CoreManagerCleanupTests(unittest.TestCase):
    def test_cleanup_closes_and_releases_llm_clients(self):
        primary = _Client()
        planner = _Client(RuntimeError("close failed"))
        provider = SimpleNamespace(
            client=primary,
            planner_client=planner,
            execution_client=object(),
            memory_extractor_client=None,
        )

        with (
            patch.object(llm_provider, "_instance", provider),
            patch.object(core_manager.gc, "collect") as collect,
        ):
            core_manager._cleanup_llm_clients()

            self.assertIs(llm_provider._instance, provider)

        self.assertTrue(primary.closed)
        self.assertTrue(planner.closed)
        self.assertIsNone(provider.client)
        self.assertIsNone(provider.planner_client)
        self.assertIsNone(provider.execution_client)
        self.assertIsNone(provider.memory_extractor_client)
        collect.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

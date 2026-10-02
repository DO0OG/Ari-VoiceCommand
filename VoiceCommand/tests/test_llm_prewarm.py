import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent import llm_prewarm


_THREADS = []


class _QueuedThread:
    def __init__(self, target, args, daemon):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self):
        _THREADS.append(self)


class LlmPrewarmTests(unittest.TestCase):
    def setUp(self):
        _THREADS.clear()
        with llm_prewarm._state_lock:
            llm_prewarm._last_success_at.clear()
            llm_prewarm._in_flight.clear()
        self.thread_patch = patch.object(llm_prewarm.threading, "Thread", _QueuedThread)
        self.thread_patch.start()
        self.addCleanup(self.thread_patch.stop)

    def _configure(self, provider_id="groq", enabled=True, locked=False):
        client = SimpleNamespace(
            models=SimpleNamespace(list=Mock()),
            base_url="https://api.example/v1",
        )
        llm_provider = SimpleNamespace(
            provider=provider_id,
            model="model-a",
            client=client,
            get_role_target=lambda role: (client, llm_provider.provider, llm_provider.model),
        )
        self.settings_patch = patch(
            "core.config_manager.ConfigManager.get", return_value=enabled
        )
        self.lock_patch = patch(
            "core.VoiceCommand.is_session_lock_blocked", return_value=locked
        )
        self.provider_patch = patch(
            "agent.llm_provider.get_llm_provider", return_value=llm_provider
        )
        self.settings_patch.start()
        self.lock_patch.start()
        self.provider_mock = self.provider_patch.start()
        self.addCleanup(self.provider_patch.stop)
        self.addCleanup(self.lock_patch.stop)
        self.addCleanup(self.settings_patch.stop)
        return client

    def test_success_schedules_daemon_and_skips_for_five_minutes(self):
        client = self._configure()

        self.assertTrue(llm_prewarm.prewarm_current_llm_connection())
        self.assertEqual(len(_THREADS), 1)
        self.assertTrue(_THREADS[0].daemon)
        client.models.list.assert_not_called()
        self.assertFalse(llm_prewarm.prewarm_current_llm_connection())
        self.assertEqual(len(_THREADS), 1)

        _THREADS[0].target(*_THREADS[0].args)
        client.models.list.assert_called_once_with()
        self.assertFalse(llm_prewarm.prewarm_current_llm_connection())
        self.assertEqual(len(_THREADS), 1)
        # 성공 예열 뒤에도 모델이 달라지면 새 조합으로 예열한다.
        llm_provider = self.provider_mock.return_value
        llm_provider.model = "model-b"
        self.assertTrue(llm_prewarm.prewarm_current_llm_connection())
        self.assertEqual(len(_THREADS), 2)
        _THREADS[1].target(*_THREADS[1].args)
        client.base_url = "https://other.example/v1"
        self.assertTrue(llm_prewarm.prewarm_current_llm_connection())
        self.assertEqual(len(_THREADS), 3)

    def test_failed_request_is_ignored_and_can_be_retried(self):
        client = self._configure()
        client.models.list.side_effect = RuntimeError("temporary failure")

        self.assertTrue(llm_prewarm.prewarm_current_llm_connection())
        _THREADS[0].target(*_THREADS[0].args)
        self.assertTrue(llm_prewarm.prewarm_current_llm_connection())
        self.assertEqual(len(_THREADS), 2)

    def test_disabled_setting_skips_provider_lookup(self):
        self._configure(enabled=False)

        self.assertFalse(llm_prewarm.prewarm_current_llm_connection())
        self.provider_mock.assert_not_called()
        self.assertEqual(_THREADS, [])

    def test_locked_session_skips_provider_lookup(self):
        self._configure(locked=True)

        self.assertFalse(llm_prewarm.prewarm_current_llm_connection())
        self.provider_mock.assert_not_called()
        self.assertEqual(_THREADS, [])

    def test_lock_before_background_request_skips_model_lookup(self):
        client = self._configure()
        with patch(
            "core.VoiceCommand.is_session_lock_blocked",
            side_effect=(False, True),
        ):
            self.assertTrue(llm_prewarm.prewarm_current_llm_connection())
            _THREADS[0].target(*_THREADS[0].args)

        client.models.list.assert_not_called()
        self.assertNotIn(("groq", "model-a", "https://api.example/v1"), llm_prewarm._in_flight)

    def test_unsupported_provider_is_skipped(self):
        self._configure(provider_id="custom_provider")

        self.assertFalse(llm_prewarm.prewarm_current_llm_connection())
        self.assertEqual(_THREADS, [])


if __name__ == "__main__":
    unittest.main()

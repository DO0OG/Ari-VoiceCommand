import unittest
from types import SimpleNamespace

from core import plugin_sandbox


class _FakeProcess:
    def __init__(self):
        self.join_calls = []
        self.terminate_called = False
        self.kill_called = False
        self._alive_states = iter((True, True))
        self.exitcode = None

    def start(self):
        return None

    def join(self, timeout=None):
        self.join_calls.append(timeout)

    def is_alive(self):
        return next(self._alive_states, False)

    def terminate(self):
        self.terminate_called = True

    def kill(self):
        self.kill_called = True


class PluginSandboxTests(unittest.TestCase):
    def test_run_sandboxed_kills_process_when_terminate_does_not_finish(self):
        fake_process = _FakeProcess()
        fake_context = SimpleNamespace(
            Queue=lambda: SimpleNamespace(empty=lambda: True),
            Process=lambda **_kwargs: fake_process,
        )

        original_get_context = plugin_sandbox.mp.get_context
        plugin_sandbox.mp.get_context = lambda _method: fake_context
        try:
            result = plugin_sandbox.run_sandboxed("print('hello')", timeout=1)
        finally:
            plugin_sandbox.mp.get_context = original_get_context

        self.assertFalse(result["ok"])
        self.assertTrue(fake_process.terminate_called)
        self.assertTrue(fake_process.kill_called)
        self.assertEqual(fake_process.join_calls, [1, 3, 2])


if __name__ == "__main__":
    unittest.main()

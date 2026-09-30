import io
import os
import sys
import unittest
from unittest.mock import Mock, patch

from core.console_streams import hide_console


class _ConsoleStream(io.StringIO):
    def isatty(self):
        return True


class ConsoleStreamsTests(unittest.TestCase):
    def test_detached_console_streams_become_devnull(self):
        kernel32 = Mock()
        kernel32.FreeConsole.return_value = 1
        redirected = io.StringIO()
        with patch.object(sys, "stdout", _ConsoleStream()), patch.object(sys, "stderr", redirected):
            hide_console(kernel32, Mock())
            self.assertEqual(sys.stdout.name, os.devnull)
            self.assertIs(sys.stderr, redirected)
            sys.stdout.write("로그")
            sys.stdout.close()

    def test_failed_detach_hides_window_and_keeps_streams(self):
        kernel32 = Mock()
        kernel32.FreeConsole.return_value = 0
        kernel32.GetConsoleWindow.return_value = 0x10
        user32 = Mock()
        console = _ConsoleStream()
        with patch.object(sys, "stdout", console):
            hide_console(kernel32, user32)
            self.assertIs(sys.stdout, console)
        user32.ShowWindow.assert_called_once_with(0x10, 0)


if __name__ == "__main__":
    unittest.main()

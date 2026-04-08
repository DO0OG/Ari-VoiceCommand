import unittest


from agent.safety_checker import DangerLevel, SafetyChecker


class SafetyCheckerTests(unittest.TestCase):
    def setUp(self):
        self.checker = SafetyChecker()

    def test_sensitive_url_is_blocked(self):
        report = self.checker.check_url("https://example.com/delete-account")
        self.assertEqual(report.level, DangerLevel.DANGEROUS)
        self.assertEqual(report.category, "web")

    def test_trusted_app_is_safe_but_blocked_admin_tool_is_not(self):
        self.assertEqual(self.checker.check_app_launch("notepad").level, DangerLevel.SAFE)
        self.assertEqual(self.checker.check_app_launch("regedit").level, DangerLevel.DANGEROUS)

    def test_restart_and_logoff_shell_are_dangerous(self):
        self.assertEqual(self.checker.check_shell("shutdown /r /t 0").level, DangerLevel.DANGEROUS)
        self.assertEqual(self.checker.check_shell("logoff").level, DangerLevel.DANGEROUS)

    def test_url_checks_are_cached_without_changing_result(self):
        first = self.checker.check_url("https://example.com/delete-account")
        second = self.checker.check_url("https://example.com/delete-account")

        self.assertEqual(first.level, second.level)
        self.assertEqual(len(self.checker._url_cache), 1)


if __name__ == "__main__":
    unittest.main()

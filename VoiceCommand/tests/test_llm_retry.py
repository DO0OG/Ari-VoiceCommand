import unittest

from agent.llm_retry import extract_retry_delay_seconds, is_retryable_llm_error


class LlmRetryTests(unittest.TestCase):
    def test_is_retryable_llm_error_matches_rate_limit_and_timeout(self):
        self.assertTrue(is_retryable_llm_error(RuntimeError("429 Too Many Requests")))
        self.assertTrue(is_retryable_llm_error(RuntimeError("request timeout")))
        self.assertFalse(is_retryable_llm_error(RuntimeError("invalid api key")))

    def test_extract_retry_delay_seconds_parses_hint_and_clamps(self):
        self.assertEqual(extract_retry_delay_seconds(RuntimeError("Please retry in 12.5s"), 0), 12.5)
        self.assertEqual(extract_retry_delay_seconds(RuntimeError("retry in 0.1s"), 0), 0.5)
        self.assertEqual(extract_retry_delay_seconds(RuntimeError("retry in 900s"), 0), 60.0)

    def test_extract_retry_delay_seconds_backs_off_without_hint(self):
        self.assertEqual(extract_retry_delay_seconds(RuntimeError("boom"), 0), 2.0)
        self.assertEqual(extract_retry_delay_seconds(RuntimeError("boom"), 9), 10.0)


if __name__ == "__main__":
    unittest.main()

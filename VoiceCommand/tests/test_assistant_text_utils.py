import unittest

from agent.assistant_text_utils import strip_trailing_symbol_tokens


class AssistantTextUtilsTests(unittest.TestCase):
    def test_removes_mixed_trailing_symbol_artifacts(self):
        self.assertEqual(strip_trailing_symbol_tokens("Answer #]#"), "Answer")
        self.assertEqual(strip_trailing_symbol_tokens("Answer ]#"), "Answer")

    def test_preserves_single_and_repeated_sentence_symbols(self):
        self.assertEqual(strip_trailing_symbol_tokens("C# 기호: #"), "C# 기호: #")
        self.assertEqual(strip_trailing_symbol_tokens("a > b 일 때: >"), "a > b 일 때: >")
        self.assertEqual(strip_trailing_symbol_tokens("C++ output: >>"), "C++ output: >>")


if __name__ == "__main__":
    unittest.main()

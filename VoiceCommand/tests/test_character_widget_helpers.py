import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ui.character_widget import _is_thinking_bubble_text


class CharacterWidgetHelperTests(unittest.TestCase):
    def test_is_thinking_bubble_text_matches_exact_indicator(self):
        self.assertTrue(_is_thinking_bubble_text("생각 중..."))

    def test_is_thinking_bubble_text_rejects_other_messages(self):
        self.assertFalse(_is_thinking_bubble_text("작업 완료"))
        self.assertFalse(_is_thinking_bubble_text(""))


if __name__ == "__main__":
    unittest.main()

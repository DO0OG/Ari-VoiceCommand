import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from ui.proactive_suggestion_bar import ProactiveSuggestionBar

_LONG = [
    (f"최근 주제 '{word}'와 관련된 반복 전략이 보여요. 이어서 정리해드릴까요?", word)
    for word in ("열어줘", "안녕", "시야")
]


class ProactiveSuggestionBarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_host(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        with patch.object(ProactiveSuggestionBar, "_build_suggestions", return_value=list(_LONG)):
            bar = ProactiveSuggestionBar()
        layout.addWidget(bar)
        host.resize(420, 300)
        host.show()
        self.app.processEvents()
        self.addCleanup(host.close)
        return host, bar

    def test_long_suggestions_do_not_widen_window(self):
        host, bar = self._make_host()

        self.assertLessEqual(host.minimumSizeHint().width(), 420)
        self.assertEqual(host.width(), 420)
        buttons = bar.findChildren(QPushButton)
        self.assertEqual(len(buttons), 3)
        for button in buttons:
            self.assertLessEqual(button.geometry().right(), bar.width())
            self.assertGreater(button.width(), 48)
            self.assertTrue(button.text().endswith("…"))
            self.assertIn("반복 전략", button.toolTip())

    def test_unchanged_suggestions_keep_existing_chips(self):
        _host, bar = self._make_host()
        before = bar.findChildren(QPushButton)

        with patch.object(ProactiveSuggestionBar, "_build_suggestions", return_value=list(_LONG)):
            bar._refresh_suggestions()

        self.assertEqual(before, bar.findChildren(QPushButton))


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QLabel


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.proactive_scheduler import ScheduledTask
from ui.scheduler_panel import SchedulerPanel, TaskRow
from ui.text_interface import ChatWidget, TextInterface


class _DummyChatWidget:
    def __init__(self):
        self.history = []

    def add_message(self, message: str, is_user: bool = False) -> None:
        self.history.append({"message": message, "is_user": is_user})

    def update_message(self, index: int, message: str) -> None:
        self.history[index]["message"] = message


class _DummyTextInterface:
    _TTS_SENTENCE_SEPS = TextInterface._TTS_SENTENCE_SEPS
    _TTS_MIN_SENTENCE_LEN = TextInterface._TTS_MIN_SENTENCE_LEN

    def _try_stream_tts(self, chunk: str) -> None:
        TextInterface._try_stream_tts(self, chunk)

    def _handle_stream_chunk(self, chunk: str) -> None:
        TextInterface._handle_stream_chunk(self, chunk)

    def _handle_response(self, final_response: str) -> None:
        TextInterface._handle_response(self, final_response)

    def _is_tts_busy(self) -> bool:
        return getattr(self, "_busy", False)


class TextInterfaceStreamingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _make_interface(self):
        spoken = []
        interface = _DummyTextInterface()
        interface.tts_callback = spoken.append
        interface.chat_widget = _DummyChatWidget()
        interface._stream_message_index = None
        interface._stream_response_buffer = ""
        interface._stream_tts_buffer = ""
        interface._stream_tts_deferred = ""
        interface._stream_tts_spoken = False
        interface._busy = False
        interface.scroll_to_bottom = lambda: None
        interface.refresh_status_panel = lambda: None
        return interface, spoken

    def test_handle_stream_chunk_starts_tts_on_sentence_boundary(self):
        interface, spoken = self._make_interface()

        interface._handle_stream_chunk("첫 번째 문장입니다. 다음")

        self.assertEqual(spoken, ["첫 번째 문장입니다."])
        self.assertEqual(interface._stream_tts_buffer, "다음")
        self.assertEqual(interface.chat_widget.history[0]["message"], "첫 번째 문장입니다. 다음")

    def test_handle_stream_chunk_defers_following_sentences_while_tts_busy(self):
        interface, spoken = self._make_interface()

        interface._handle_stream_chunk("첫 번째 문장입니다. ")
        interface._busy = True
        interface._handle_stream_chunk("두 번째 문장입니다. ")

        self.assertEqual(spoken, ["첫 번째 문장입니다."])
        self.assertEqual(interface._stream_tts_deferred, "두 번째 문장입니다.")

    def test_handle_response_flushes_remaining_stream_tts_buffer_once(self):
        interface, spoken = self._make_interface()
        interface._stream_message_index = 0
        interface.chat_widget.add_message("", is_user=False)
        interface._stream_tts_spoken = True
        interface._stream_tts_deferred = "두 번째 문장입니다."
        interface._stream_tts_buffer = "남은 문장"
        interface._stream_response_buffer = "전체 응답"

        interface._handle_response("")

        self.assertEqual(spoken, ["두 번째 문장입니다. 남은 문장"])
        self.assertEqual(interface.chat_widget.history[0]["message"], "전체 응답")
        self.assertEqual(interface._stream_tts_buffer, "")
        self.assertEqual(interface._stream_tts_deferred, "")
        self.assertFalse(interface._stream_tts_spoken)

    def test_chat_widget_limits_bubble_width_to_viewport(self):
        widget = ChatWidget()
        widget.resize(360, 300)
        widget.add_message("긴 응답 " * 30, is_user=False)
        self._app.processEvents()

        row_widget = widget.layout().itemAt(0).widget()
        row_layout = row_widget.layout()
        bubble = next(
            item.widget()
            for index in range(row_layout.count())
            if (item := row_layout.itemAt(index)).widget() and isinstance(item.widget(), QFrame)
        )

        self.assertLessEqual(bubble.maximumWidth(), widget.width())
        self.assertLess(bubble.maximumWidth(), widget.width())

    def test_chat_widget_preserves_message_timestamp_across_rerender(self):
        widget = ChatWidget()
        widget.resize(360, 300)
        widget.add_message("안녕하세요", is_user=False, timestamp="09:30:00")
        widget.render_history()

        labels = widget.findChildren(QLabel)
        self.assertEqual(widget.history[0]["timestamp"], "09:30:00")
        self.assertIn("09:30:00", [label.text() for label in labels])

    def test_scheduler_task_row_wraps_long_text_labels(self):
        task = ScheduledTask(
            task_id="task-1",
            name="매우 긴 예약 작업 이름 " * 4,
            goal="예약 작업 설명이 길어서 여러 줄로 자연스럽게 줄바꿈되어야 합니다. " * 4,
            schedule_expr="매주 수요일 오후 11시 45분마다 아주 긴 설명이 붙는 스케줄",
            next_run="2026-04-06T23:45:00",
            last_run="2026-04-05T23:45:00",
            last_result="이전 실행 결과도 길어서 오른쪽으로 밀리지 않고 영역 안에서 줄바꿈되어야 합니다. " * 2,
        )
        row = TaskRow(task)
        labels = row.findChildren(QLabel)

        self.assertGreaterEqual(len(labels), 4)
        self.assertTrue(all(label.wordWrap() for label in labels))

    def test_scheduler_panel_disables_horizontal_scrollbar(self):
        panel = SchedulerPanel(scheduler=None)

        self.assertEqual(panel._scroll.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)


if __name__ == "__main__":
    unittest.main()

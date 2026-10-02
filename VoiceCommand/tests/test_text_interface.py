import importlib
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget,
)


from agent.proactive_scheduler import ScheduledTask
from ui import theme as theme_module
from ui.scheduler_panel import SchedulerPanel, TaskRow
from ui.text_interface import ChatWidget, TextInterface, TextInterfaceThread


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
    _TTS_BATCH_TARGET_LEN = TextInterface._TTS_BATCH_TARGET_LEN
    _TTS_MAX_BATCH_SENTENCES = TextInterface._TTS_MAX_BATCH_SENTENCES
    _speech_stopped = False

    def _try_stream_tts(self, chunk: str) -> None:
        TextInterface._try_stream_tts(self, chunk)

    def _queue_stream_tts_sentence(self, sentence: str) -> None:
        TextInterface._queue_stream_tts_sentence(self, sentence)

    def _flush_stream_tts_sentence_batch(self) -> None:
        TextInterface._flush_stream_tts_sentence_batch(self)

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
        interface._stream_tts_sentence_batch = []
        interface._stream_tts_spoken = False
        interface._busy = False
        interface.scroll_to_bottom = lambda: None
        interface.refresh_status_panel = lambda: None
        return interface, spoken

    def test_empty_ai_command_result_does_not_retry_with_provider(self):
        from types import SimpleNamespace
        from commands.ai_command import AICommand

        command = AICommand(Mock(), lambda _message: None, {"enabled": False})
        command.run_interaction = Mock(return_value="")
        provider = Mock()
        interface = TextInterfaceThread(provider, "cancel me")
        state = SimpleNamespace(command_registry=SimpleNamespace(commands=[command]))

        with patch("core.VoiceCommand._state", state):
            self.assertEqual(interface._execute_query(), "")
            provider.chat_with_tools.assert_not_called()

    def test_handle_stream_chunk_starts_tts_on_long_sentence_boundary(self):
        interface, spoken = self._make_interface()

        interface._handle_stream_chunk("조금 더 긴 첫 번째 문장입니다. 다음")

        self.assertEqual(spoken, ["조금 더 긴 첫 번째 문장입니다."])
        self.assertEqual(interface._stream_tts_buffer, "다음")
        self.assertEqual(interface.chat_widget.history[0]["message"], "조금 더 긴 첫 번째 문장입니다. 다음")

    def test_handle_stream_chunk_batches_two_short_sentences_before_tts(self):
        interface, spoken = self._make_interface()

        interface._handle_stream_chunk("안녕하세요. 반갑습니다. 다음")

        self.assertEqual(spoken, ["안녕하세요. 반갑습니다."])
        self.assertEqual(interface._stream_tts_buffer, "다음")
        self.assertEqual(interface._stream_tts_sentence_batch, [])

    def test_handle_stream_chunk_defers_following_sentences_while_tts_busy(self):
        interface, spoken = self._make_interface()

        interface._handle_stream_chunk("조금 더 긴 첫 번째 문장입니다. ")
        interface._busy = True
        interface._handle_stream_chunk("조금 더 긴 두 번째 문장입니다. ")

        self.assertEqual(spoken, ["조금 더 긴 첫 번째 문장입니다."])
        self.assertEqual(interface._stream_tts_deferred, "조금 더 긴 두 번째 문장입니다.")

    def test_handle_response_flushes_remaining_stream_tts_buffer_once(self):
        interface, spoken = self._make_interface()
        interface._stream_message_index = 0
        interface.chat_widget.add_message("", is_user=False)
        interface._stream_tts_spoken = True
        interface._stream_tts_deferred = "두 번째 문장입니다."
        interface._stream_tts_sentence_batch = ["세 번째 문장입니다."]
        interface._stream_tts_buffer = "남은 문장"
        interface._stream_response_buffer = "전체 응답"

        interface._handle_response("")

        self.assertEqual(spoken, ["두 번째 문장입니다. 세 번째 문장입니다. 남은 문장"])
        self.assertEqual(interface.chat_widget.history[0]["message"], "전체 응답")
        self.assertEqual(interface._stream_tts_buffer, "")
        self.assertEqual(interface._stream_tts_deferred, "")
        self.assertEqual(interface._stream_tts_sentence_batch, [])
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

    def test_chat_widget_bubble_grows_with_wrapped_lines(self):
        # 실제 UI와 같이 크기 조절되는 스크롤 영역 안에 넣어야 잘림이 재현된다.
        host = QWidget()
        host_layout = QVBoxLayout(host)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = ChatWidget()
        scroll.setWidget(widget)
        host_layout.addWidget(scroll)
        host.resize(600, 800)
        host.show()
        self.addCleanup(host.close)
        self._app.processEvents()

        widget.add_message("긴 응답 " * 30, is_user=False)
        self._app.processEvents()
        widget.layout().activate()

        row_layout = widget.layout().itemAt(0).widget().layout()
        bubble = next(
            item.widget()
            for index in range(row_layout.count())
            if (item := row_layout.itemAt(index)).widget() and isinstance(item.widget(), QFrame)
        )
        msg_lbl = max(bubble.findChildren(QLabel), key=lambda lbl: len(lbl.text()))

        # 배정된 폭에서 줄바꿈된 본문이 잘리지 않아야 한다.
        needed = msg_lbl.heightForWidth(msg_lbl.width())
        self.assertGreater(needed, 0)
        self.assertGreaterEqual(msg_lbl.height(), needed)

    def test_chat_bubble_fits_mixed_text_after_resize_and_theme_scale(self):
        host = QWidget()
        host_layout = QVBoxLayout(host)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        widget = ChatWidget()
        scroll.setWidget(widget)
        host_layout.addWidget(scroll)
        host.resize(640, 800)
        host.show()
        self.addCleanup(host.close)
        self._app.processEvents()

        message = (
            "한글과 English 문장이 섞여도 줄바꿈되어야 합니다.\n"
            "새 줄도 유지하고, 이어지는 응답도 모두 보여야 합니다.\n"
            + "unbrokenEnglishText" * 24
        )
        widget.add_message(message, is_user=True)

        def assert_bubble_fits():
            self._app.processEvents()
            widget.layout().activate()
            row_widget = widget.layout().itemAt(0).widget()
            row_layout = row_widget.layout()
            bubble = next(
                item.widget()
                for index in range(row_layout.count())
                if (item := row_layout.itemAt(index)).widget() and isinstance(item.widget(), QFrame)
            )
            msg_lbl = next(
                label for label in bubble.findChildren(QLabel) if label.text() == message
            )
            contents = widget.layout().contentsMargins()

            self.assertTrue(msg_lbl.wordWrap())
            self.assertEqual(msg_lbl.textFormat(), Qt.PlainText)
            self.assertLessEqual(
                bubble.width(), widget.width() - contents.left() - contents.right()
            )
            self.assertGreaterEqual(bubble.height(), bubble.minimumHeight())
            self.assertGreaterEqual(row_widget.height(), row_widget.minimumHeight())
            self.assertLessEqual(bubble.geometry().right() + 1, row_widget.width())
            needed = msg_lbl.heightForWidth(msg_lbl.width())
            self.assertGreater(needed, 0)
            long_line = "unbrokenEnglishText" * 24
            self.assertGreater(
                msg_lbl.fontMetrics().horizontalAdvance(long_line), msg_lbl.width()
            )
            self.assertGreater(needed, msg_lbl.fontMetrics().height() * 3)
            self.assertGreaterEqual(msg_lbl.height(), needed)
            self.assertLessEqual(msg_lbl.geometry().bottom() + 1, bubble.height())
            self.assertGreaterEqual(bubble.height(), bubble.layout().sizeHint().height())
            return msg_lbl

        previous_host_width = host.width()
        previous_widget_width = widget.width()
        for width in (640, 360, 240, 180):
            host.resize(width, 800)
            self._app.processEvents()
            self.assertLessEqual(widget.width(), scroll.viewport().width())
            if width < previous_host_width:
                self.assertLess(widget.width(), previous_widget_width)
            assert_bubble_fits()
            previous_host_width = width
            previous_widget_width = widget.width()

        original_settings = dict(theme_module._SETTINGS)
        original_scale = theme_module.theme_metadata()["scale"]
        target_scale = 0.9 if original_scale > 1.0 else 1.35
        try:
            with patch(
                "core.config_manager.ConfigManager.load_settings",
                return_value={**original_settings, "ui_theme_scale": target_scale},
            ):
                importlib.reload(theme_module)
            widget.refresh_theme()
            msg_lbl = assert_bubble_fits()
            self.assertEqual(theme_module.theme_metadata()["scale"], target_scale)
            self.assertEqual(msg_lbl.font().pointSize(), theme_module.FONT_SIZE_LARGE)
        finally:
            with patch(
                "core.config_manager.ConfigManager.load_settings",
                return_value=original_settings,
            ):
                importlib.reload(theme_module)
            widget.refresh_theme()

    def test_chat_widget_preserves_message_timestamp_across_rerender(self):
        widget = ChatWidget()
        widget.resize(360, 300)
        widget.add_message("안녕하세요", is_user=False, timestamp="09:30:00")
        widget.render_history()

        labels = widget.findChildren(QLabel)
        self.assertEqual(widget.history[0]["timestamp"], "09:30:00")
        self.assertIn("09:30:00", [label.text() for label in labels])

    def test_chat_widget_stream_update_replaces_only_that_row(self):
        widget = ChatWidget()
        widget.resize(360, 300)
        widget.add_message("질문", is_user=True)
        widget.add_message("", is_user=False)
        first_row = widget.layout().itemAt(0).widget()
        old_row = widget.layout().itemAt(1).widget()

        widget.update_message(1, "스트리밍 응답")

        self.assertEqual(widget.layout().count(), 2)
        self.assertIs(widget.layout().itemAt(0).widget(), first_row)
        self.assertIsNot(widget.layout().itemAt(1).widget(), old_row)
        self.assertTrue(old_row.isHidden())
        new_texts = [label.text() for label in widget.layout().itemAt(1).widget().findChildren(QLabel)]
        self.assertTrue(any("스트리밍 응답" in text for text in new_texts), new_texts)

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

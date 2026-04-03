import os
import sys
import unittest
from types import MethodType


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ui.text_interface import TextInterface


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


class TextInterfaceStreamingTests(unittest.TestCase):
    def _make_interface(self):
        spoken = []
        interface = _DummyTextInterface()
        interface.tts_callback = spoken.append
        interface.chat_widget = _DummyChatWidget()
        interface._stream_message_index = None
        interface._stream_response_buffer = ""
        interface._stream_tts_buffer = ""
        interface._stream_tts_spoken = False
        interface.scroll_to_bottom = lambda: None
        interface.refresh_status_panel = lambda: None
        interface._try_stream_tts = MethodType(TextInterface._try_stream_tts, interface)
        interface._handle_stream_chunk = MethodType(TextInterface._handle_stream_chunk, interface)
        interface._handle_response = MethodType(TextInterface._handle_response, interface)
        return interface, spoken

    def test_handle_stream_chunk_starts_tts_on_sentence_boundary(self):
        interface, spoken = self._make_interface()

        interface._handle_stream_chunk("첫 번째 문장입니다. 다음")

        self.assertEqual(spoken, ["첫 번째 문장입니다."])
        self.assertEqual(interface._stream_tts_buffer, "다음")
        self.assertEqual(interface.chat_widget.history[0]["message"], "첫 번째 문장입니다. 다음")

    def test_handle_response_flushes_remaining_stream_tts_buffer_once(self):
        interface, spoken = self._make_interface()
        interface._stream_message_index = 0
        interface.chat_widget.add_message("", is_user=False)
        interface._stream_tts_spoken = True
        interface._stream_tts_buffer = "남은 문장"
        interface._stream_response_buffer = "전체 응답"

        interface._handle_response("")

        self.assertEqual(spoken, ["남은 문장"])
        self.assertEqual(interface.chat_widget.history[0]["message"], "전체 응답")
        self.assertEqual(interface._stream_tts_buffer, "")
        self.assertFalse(interface._stream_tts_spoken)


if __name__ == "__main__":
    unittest.main()

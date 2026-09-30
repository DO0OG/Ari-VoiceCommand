import threading
import unittest
from unittest.mock import Mock

from tts.pcm_playback import (
    play_pcm_stream,
    write_pcm_chunks,
    write_pcm_stream_chunks,
)


class PCMPlaybackTests(unittest.TestCase):
    def test_cancel_stops_writing_after_current_chunk(self):
        stop_event = threading.Event()
        stream = Mock()
        stream.write.side_effect = lambda _chunk: stop_event.set()

        self.assertFalse(write_pcm_chunks(stream, b"x" * 1000, stop_event, 1000))

        stream.write.assert_called_once_with(b"x" * 200)

    def test_cancel_before_playback_writes_nothing(self):
        stop_event = threading.Event()
        stop_event.set()
        stream = Mock()

        self.assertFalse(write_pcm_chunks(stream, b"pcm", stop_event, 24000))

        stream.write.assert_not_called()

    def test_stream_carries_odd_byte_between_chunks(self):
        stream = Mock()

        self.assertTrue(
            write_pcm_stream_chunks(
                stream,
                [b"\x01", b"\x02\x03", b"\x04"],
                threading.Event(),
                24000,
            )
        )

        self.assertEqual(
            b"".join(call.args[0] for call in stream.write.call_args_list),
            b"\x01\x02\x03\x04",
        )

    def test_stream_stops_after_cancel_during_write(self):
        stop_event = threading.Event()
        next_chunk_read = threading.Event()
        stream = Mock()
        stream.write.side_effect = lambda _chunk: stop_event.set()

        def chunks():
            yield b"\x01\x02"
            next_chunk_read.set()
            yield b"\x03\x04"

        self.assertFalse(
            write_pcm_stream_chunks(stream, chunks(), stop_event, 24000)
        )

        stream.write.assert_called_once_with(b"\x01\x02")
        self.assertFalse(next_chunk_read.is_set())

    def test_stream_start_logs_after_write_and_completion_follows_close(self):
        stream = Mock()
        events = []
        stream.write.side_effect = lambda _chunk: events.append("write")

        self.assertTrue(
            play_pcm_stream(
                lambda: stream,
                lambda _stream: events.append("close"),
                [b"\x01\x02"],
                threading.Event(),
                24000,
                on_start=lambda: events.append("start"),
                on_complete=lambda success: events.append(("complete", success)),
            )
        )

        self.assertEqual(events, ["write", "start", "close", ("complete", True)])


if __name__ == "__main__":
    unittest.main()

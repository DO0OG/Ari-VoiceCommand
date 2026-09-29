import threading
import unittest
from unittest.mock import Mock

from tts.pcm_playback import write_pcm_chunks


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


if __name__ == "__main__":
    unittest.main()

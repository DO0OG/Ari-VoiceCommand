import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from audio import audio_manager
from core.VoiceCommand import SharedMicrophone, list_microphone_names


def _fake_pyaudio_module():
    return SimpleNamespace(PyAudio=MagicMock(), paInt16=8, get_sample_size=lambda _fmt: 2)


def _fake_global_audio(default_input=None):
    audio = MagicMock()
    audio.get_device_count.return_value = 2
    audio.get_device_info_by_index.side_effect = lambda index: {
        "name": f"Mic {index}", "defaultSampleRate": 48000.0,
    }
    if default_input is None:
        audio.get_default_input_device_info.side_effect = OSError(
            "No Default Input Device Available"
        )
    else:
        audio.get_default_input_device_info.return_value = default_input
    return audio


class OptionalAudioStartupTests(unittest.TestCase):
    def test_global_audio_initialization_failure_is_reported_without_raising(self):
        with patch.object(
            audio_manager.GlobalAudio,
            "get_instance",
            side_effect=OSError("no audio device available"),
        ):
            self.assertFalse(audio_manager.initialize_global_audio())

    def test_global_audio_initialization_reports_success(self):
        with patch.object(audio_manager.GlobalAudio, "get_instance", return_value=object()):
            self.assertTrue(audio_manager.initialize_global_audio())



class SharedMicrophoneTests(unittest.TestCase):
    def _patch_audio(self, audio, module):
        return (
            patch("core.VoiceCommand.GlobalAudio.get_instance", return_value=audio),
            patch.object(SharedMicrophone, "get_pyaudio", return_value=module),
        )

    def test_open_and_close_reuse_global_audio_without_terminate(self):
        audio = _fake_global_audio({"defaultSampleRate": 44100.0})
        module = _fake_pyaudio_module()
        patch_instance, patch_module = self._patch_audio(audio, module)
        with patch_instance, patch_module:
            microphone = SharedMicrophone()
            with microphone as source:
                self.assertIsNotNone(source.stream)
                self.assertIs(source.audio, audio)

        self.assertEqual(microphone.SAMPLE_RATE, 44100)
        self.assertIsNone(microphone.stream)
        audio.open.assert_called_once()
        audio.open.return_value.close.assert_called_once()
        module.PyAudio.assert_not_called()
        audio.terminate.assert_not_called()

    def test_missing_default_input_raises_os_error(self):
        audio = _fake_global_audio()
        module = _fake_pyaudio_module()
        patch_instance, patch_module = self._patch_audio(audio, module)
        with patch_instance, patch_module, self.assertRaises(OSError):
            SharedMicrophone()
        module.PyAudio.assert_not_called()
        audio.terminate.assert_not_called()

    def test_stream_open_failure_leaves_stream_empty(self):
        audio = _fake_global_audio({"defaultSampleRate": 16000})
        audio.open.side_effect = OSError("Invalid input device")
        module = _fake_pyaudio_module()
        patch_instance, patch_module = self._patch_audio(audio, module)
        with patch_instance, patch_module:
            microphone = SharedMicrophone(device_index=1)
            with microphone as source:
                self.assertIsNone(source.stream)
        audio.terminate.assert_not_called()

    def test_microphone_names_come_from_global_audio(self):
        audio = _fake_global_audio()
        with patch("core.VoiceCommand.GlobalAudio.get_instance", return_value=audio):
            self.assertEqual(list_microphone_names(), ["Mic 0", "Mic 1"])
        audio.terminate.assert_not_called()


if __name__ == "__main__":
    unittest.main()

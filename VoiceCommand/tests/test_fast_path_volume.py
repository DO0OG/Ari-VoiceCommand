import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from commands.ai_command import AICommand
from core import VoiceCommand as voice_command
from i18n.translator import _


class _Endpoint:
    def __init__(self, current=0.5):
        self.current = current
        self.scalar_calls = []
        self.mute_calls = []

    def GetMasterVolumeLevelScalar(self):
        return self.current

    def SetMasterVolumeLevelScalar(self, value, context):
        self.scalar_calls.append((value, context))

    def SetMute(self, value, context):
        self.mute_calls.append((value, context))


def _audio_modules(endpoint, *, get_speakers=None):
    speakers = SimpleNamespace(
        Activate=lambda iid, context, reserved: object(),
    )
    if get_speakers is None:
        get_speakers = lambda: speakers

    class _EndpointInterface:
        _iid_ = object()

    comtypes = types.ModuleType("comtypes")
    comtypes.CLSCTX_ALL = object()
    pycaw = types.ModuleType("pycaw")
    pycaw_impl = types.ModuleType("pycaw.pycaw")
    pycaw_impl.AudioUtilities = SimpleNamespace(GetSpeakers=get_speakers)
    pycaw_impl.IAudioEndpointVolume = _EndpointInterface
    pycaw.pycaw = pycaw_impl
    return {"comtypes": comtypes, "pycaw": pycaw, "pycaw.pycaw": pycaw_impl}


class FastPathVolumeTests(unittest.TestCase):
    def _call_volume(self, change, *, amount=None, announce=False, endpoint=None, get_speakers=None):
        endpoint = endpoint or _Endpoint()
        modules = _audio_modules(endpoint, get_speakers=get_speakers)
        with patch.dict(sys.modules, modules), patch("ctypes.cast", return_value=endpoint), patch(
            "ctypes.POINTER", return_value=object()
        ):
            result = voice_command.adjust_volume(change, amount=amount, announce=announce)
        return result, endpoint

    def test_numeric_delta_is_preserved_and_clamped(self):
        result, endpoint = self._call_volume(0.2, endpoint=_Endpoint(current=0.9))

        self.assertTrue(result)
        self.assertEqual(endpoint.scalar_calls, [(1.0, None)])

    def test_direction_amount_and_mute_use_shared_volume_path(self):
        result, endpoint = self._call_volume("down", amount=20, endpoint=_Endpoint(current=0.8))

        self.assertTrue(result)
        self.assertEqual(len(endpoint.scalar_calls), 1)
        self.assertAlmostEqual(endpoint.scalar_calls[0][0], 0.6)
        self.assertIsNone(endpoint.scalar_calls[0][1])

        result, endpoint = self._call_volume("mute")
        self.assertTrue(result)
        self.assertEqual(endpoint.mute_calls, [(1, None)])

    def test_new_pycaw_device_uses_endpoint_volume_without_activate(self):
        endpoint = _Endpoint(current=0.5)
        result, endpoint = self._call_volume(
            "up",
            amount=10,
            endpoint=endpoint,
            get_speakers=lambda: SimpleNamespace(EndpointVolume=endpoint),
        )

        self.assertTrue(result)
        self.assertAlmostEqual(endpoint.scalar_calls[0][0], 0.6)

    def test_invalid_amount_and_system_failure_report_failure(self):
        result, endpoint = self._call_volume("up", amount=-10)
        self.assertFalse(result)
        self.assertEqual(endpoint.scalar_calls, [])

        messages = []
        with patch.object(voice_command, "tts_wrapper", side_effect=messages.append):
            result, _endpoint = self._call_volume(
                "up",
                amount=10,
                announce=True,
                get_speakers=lambda: (_ for _ in ()).throw(OSError("audio unavailable")),
            )
        self.assertFalse(result)
        self.assertEqual(messages, [_('볼륨 조절 실패')])

    def test_handler_passes_amount_without_retrying(self):
        command = AICommand(Mock(), lambda message: None, {"enabled": False})
        with patch("core.VoiceCommand.adjust_volume", return_value=False) as adjust:
            result = command._handle_adjust_volume({"direction": "up", "amount": 101})

        self.assertEqual(result, _("볼륨 조절 실패"))
        adjust.assert_called_once_with("up", amount=101, announce=False)


if __name__ == "__main__":
    unittest.main()

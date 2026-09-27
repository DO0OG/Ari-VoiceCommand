from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QDialog

from ui.character_widget import CharacterWidget
from ui.settings_dialog import SettingsDialog, should_apply_microphone
from ui.tray_icon import SystemTrayIcon


def test_saving_settings_retries_microphone_only_when_voice_is_stopped():
    unchanged = _dialog(microphone_changed=False)
    stopped = SimpleNamespace(voice_thread=SimpleNamespace(microphone_available=False))
    running = SimpleNamespace(voice_thread=SimpleNamespace(microphone_available=True))

    assert should_apply_microphone(unchanged, stopped)
    assert not should_apply_microphone(unchanged, running)
    assert not should_apply_microphone(unchanged, None)
    assert should_apply_microphone(_dialog(microphone_changed=True), running)


def _dialog(accepted=True, microphone_changed=True):
    dialog = Mock()
    dialog.exec.return_value = QDialog.Accepted if accepted else QDialog.Rejected
    dialog.microphone_settings_changed.return_value = microphone_changed
    dialog.tts_settings_changed.return_value = False
    dialog.theme_settings_changed.return_value = False
    return dialog


def test_settings_dialog_reports_microphone_change():
    assert SettingsDialog.microphone_settings_changed(
        SimpleNamespace(changed_keys={"microphone"})
    )
    assert not SettingsDialog.microphone_settings_changed(
        SimpleNamespace(changed_keys={"audio_output_device"})
    )


def test_character_settings_flow_applies_only_saved_microphone_changes():
    widget = SimpleNamespace(apply_microphone_settings=Mock())
    for accepted, changed, expected_calls in (
        (True, True, 1),
        (True, False, 0),
        (False, True, 0),
    ):
        widget.apply_microphone_settings.reset_mock()
        with patch("ui.settings_dialog.SettingsDialog", return_value=_dialog(accepted, changed)):
            CharacterWidget.open_settings(widget)
        assert widget.apply_microphone_settings.call_count == expected_calls


def test_tray_settings_flow_applies_only_saved_microphone_changes():
    character = SimpleNamespace(apply_microphone_settings=Mock())
    tray = SimpleNamespace(character_widget=character)
    for accepted, changed, expected_calls in (
        (True, True, 1),
        (True, False, 0),
        (False, True, 0),
    ):
        character.apply_microphone_settings.reset_mock()
        with patch("ui.tray_icon.SettingsDialog", return_value=_dialog(accepted, changed)):
            SystemTrayIcon.open_settings(tray)
        assert character.apply_microphone_settings.call_count == expected_calls


def test_character_sends_saved_microphone_to_worker_thread():
    voice_thread = Mock()
    widget = SimpleNamespace(voice_thread=voice_thread)
    with patch(
        "core.config_manager.ConfigManager.load_settings",
        return_value={"microphone": "USB Microphone"},
    ):
        assert CharacterWidget.apply_microphone_settings(widget)

    voice_thread.set_microphone.assert_called_once_with("USB Microphone")

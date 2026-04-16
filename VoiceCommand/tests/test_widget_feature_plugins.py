import os
import sys
import tempfile
import types
import unittest
from datetime import date
from unittest.mock import patch

from PySide6.QtCore import QPoint, QRect

from plugins import affinity_plugin, bubble_history_plugin, focus_app_plugin, special_date_plugin, system_monitor_plugin


class _FakeWidget:
    def __init__(self):
        self.say_calls = []
        self.emotions = []

    def say(self, text, duration=5000):
        self.say_calls.append((text, duration))

    def set_emotion(self, emotion):
        self.emotions.append(emotion)


class _FakeOverlayWidget(_FakeWidget):
    def __init__(self, origin: QPoint, *, size: tuple[int, int] = (120, 180), current_screen=None):
        super().__init__()
        self._origin = origin
        self._rect = QRect(0, 0, size[0], size[1])
        self._current_screen = current_screen

    def rect(self):
        return QRect(self._rect)

    def width(self):
        return self._rect.width()

    def mapToGlobal(self, point: QPoint):
        return QPoint(self._origin.x() + point.x(), self._origin.y() + point.y())


class _FakeScreen:
    def __init__(self, rect: QRect):
        self._rect = rect

    def availableGeometry(self):
        return QRect(self._rect)


class _FakeOverlay:
    def __init__(self, *, width: int = 240, height: int = 100):
        self._width = width
        self._height = height
        self._x = 0
        self._y = 0

    def width(self):
        return self._width

    def height(self):
        return self._height

    def x(self):
        return self._x

    def y(self):
        return self._y

    def move(self, x, y):
        self._x = x
        self._y = y


class WidgetFeaturePluginTests(unittest.TestCase):
    def test_affinity_manager_levels_up_at_threshold(self):
        saved = {}

        def _save(payload):
            saved.update(payload)
            return True

        with (
            patch("core.config_manager.ConfigManager.load_settings", return_value={}),
            patch("core.config_manager.ConfigManager.save_settings", side_effect=_save),
        ):
            manager = affinity_plugin.AffinityManager()
            leveled_up = manager.add_points(50, "click")

        self.assertTrue(leveled_up)
        self.assertEqual(manager.level, 1)
        self.assertEqual(saved["affinity_points"], 50)
        self.assertEqual(saved["affinity_total_clicks"], 1)

    def test_focus_app_classification_matches_coding_apps(self):
        result = focus_app_plugin._classify_app("visual studio code", "code.exe")

        self.assertIsNotNone(result)
        rule_key, emotion, _messages, cooldown = result
        self.assertEqual(rule_key, "coding")
        self.assertEqual(emotion, "진지")
        self.assertEqual(cooldown, 600)

    def test_system_monitor_checks_thresholds_and_reacts(self):
        fake_psutil = types.SimpleNamespace(
            cpu_percent=lambda interval=1: 97,
            virtual_memory=lambda: types.SimpleNamespace(percent=96),
            sensors_battery=lambda: types.SimpleNamespace(percent=9, power_plugged=False),
        )

        with (
            patch.dict(sys.modules, {"psutil": fake_psutil}),
            patch("plugins.system_monitor_plugin._maybe_react") as react_mock,
        ):
            system_monitor_plugin._check_system()

        self.assertEqual(
            [call.args[0] for call in react_mock.call_args_list],
            ["cpu_critical", "ram_critical", "battery_critical"],
        )

    def test_special_date_plugin_fires_birthday_event_for_today(self):
        widget = _FakeWidget()
        today = date.today().strftime("%m-%d")

        with (
            patch("core.config_manager.ConfigManager.load_settings", return_value={"special_date_events_enabled": True, "user_birthday": today}),
            patch("PySide6.QtCore.QTimer.singleShot", side_effect=lambda _ms, callback: callback()),
            patch("plugins.special_date_plugin._RNG.choice", return_value="축하해요"),
        ):
            special_date_plugin._check_and_fire_event(widget)

        self.assertEqual(widget.emotions, ["기쁨"])
        self.assertEqual(widget.say_calls[-1], ("축하해요", 6000))

    def test_bubble_history_show_history_reports_empty_state_without_file(self):
        widget = _FakeWidget()
        bubble_history_plugin._widget_ref = widget

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bubble_history.json")
            with patch("core.resource_manager.ResourceManager.get_writable_path", return_value=path):
                bubble_history_plugin._show_history()

        self.assertTrue(widget.say_calls)

    def test_affinity_register_does_not_wrap_widget_say(self):
        widget = _FakeWidget()
        original_func = widget.say.__func__

        with (
            patch("core.config_manager.ConfigManager.load_settings", return_value={}),
            patch("core.config_manager.ConfigManager.save_settings", return_value=True),
        ):
            affinity_plugin.register(types.SimpleNamespace(character_widget=widget, register_menu_action=None))

        self.assertIs(widget.say.__func__, original_func)
        self.assertFalse(getattr(widget, "_affinity_chat_tracking_installed", False))

    def test_affinity_daily_login_persists_immediately_across_reload(self):
        saved = {}

        def _load():
            return dict(saved)

        def _save(payload):
            saved.update(payload)
            return True

        with (
            patch("core.config_manager.ConfigManager.load_settings", side_effect=_load),
            patch("core.config_manager.ConfigManager.save_settings", side_effect=_save),
        ):
            manager = affinity_plugin.AffinityManager()
            first = manager.record_daily_login()
            reloaded = affinity_plugin.AffinityManager()
            second = reloaded.record_daily_login()

        self.assertFalse(first)
        self.assertFalse(second)
        self.assertEqual(saved["affinity_last_login"], date.today().isoformat())
        self.assertEqual(saved["affinity_points"], 10)

    def test_affinity_menu_action_schedules_overlay_instead_of_bubble(self):
        widget = _FakeWidget()
        affinity_plugin._widget_ref = widget
        affinity_plugin._affinity_manager = types.SimpleNamespace(
            get_level=lambda: 2,
            get_level_name=lambda: "친구",
            points=220,
        )

        with (
            patch("PySide6.QtCore.QTimer.singleShot", side_effect=lambda _ms, callback: callback()),
            patch("plugins.affinity_plugin._show_affinity_overlay") as overlay_mock,
        ):
            affinity_plugin._on_show_affinity()

        overlay_mock.assert_called_once_with(widget, 2, "친구", 220, 500)
        self.assertEqual(widget.say_calls, [])

    def test_system_monitor_menu_action_schedules_overlay(self):
        widget = _FakeWidget()
        system_monitor_plugin._widget_ref = widget

        with (
            patch("PySide6.QtCore.QTimer.singleShot", side_effect=lambda _ms, callback: callback()),
            patch("plugins.system_monitor_plugin._show_system_overlay") as overlay_mock,
        ):
            system_monitor_plugin._on_show_system_monitor()

        overlay_mock.assert_called_once_with(widget)

    def test_affinity_overlay_uses_screen_at_character_position(self):
        primary = object()
        secondary = object()
        widget = _FakeOverlayWidget(QPoint(2050, 120), current_screen=primary)

        with (
            patch("PySide6.QtWidgets.QApplication.screenAt", return_value=secondary),
            patch("PySide6.QtWidgets.QApplication.primaryScreen", return_value=primary),
        ):
            screen = affinity_plugin._get_widget_screen(widget)

        self.assertIs(screen, secondary)

    def test_system_monitor_overlay_falls_back_to_character_current_screen(self):
        primary = object()
        secondary = object()
        widget = _FakeOverlayWidget(QPoint(2050, 120), current_screen=secondary)

        with (
            patch("PySide6.QtWidgets.QApplication.screenAt", return_value=None),
            patch("PySide6.QtWidgets.QApplication.primaryScreen", return_value=primary),
        ):
            screen = system_monitor_plugin._get_widget_screen(widget)

        self.assertIs(screen, secondary)

    def test_affinity_overlay_position_updates_when_character_moves(self):
        widget = _FakeOverlayWidget(QPoint(100, 200))
        overlay = _FakeOverlay(width=240, height=100)
        screen = _FakeScreen(QRect(0, 0, 1920, 1080))

        with patch("plugins.affinity_plugin._get_widget_screen", return_value=screen):
            affinity_plugin._sync_overlay_position(overlay, widget)
            first = (overlay.x(), overlay.y())
            widget._origin = QPoint(450, 260)
            affinity_plugin._sync_overlay_position(overlay, widget)

        self.assertNotEqual(first, (overlay.x(), overlay.y()))
        self.assertEqual((overlay.x(), overlay.y()), (390, 146))

    def test_system_monitor_overlay_position_updates_when_character_moves(self):
        widget = _FakeOverlayWidget(QPoint(300, 260))
        overlay = _FakeOverlay(width=260, height=120)
        screen = _FakeScreen(QRect(0, 0, 2560, 1440))

        with patch("plugins.system_monitor_plugin._get_widget_screen", return_value=screen):
            system_monitor_plugin._sync_overlay_position(overlay, widget)
            first = (overlay.x(), overlay.y())
            widget._origin = QPoint(700, 360)
            system_monitor_plugin._sync_overlay_position(overlay, widget)

        self.assertNotEqual(first, (overlay.x(), overlay.y()))
        self.assertEqual((overlay.x(), overlay.y()), (630, 226))


if __name__ == "__main__":
    unittest.main()

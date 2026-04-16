import os
import sys
import tempfile
import types
import unittest
from datetime import date
from unittest.mock import patch

from plugins import affinity_plugin, bubble_history_plugin, focus_app_plugin, special_date_plugin, system_monitor_plugin


class _FakeWidget:
    def __init__(self):
        self.say_calls = []
        self.emotions = []

    def say(self, text, duration=5000):
        self.say_calls.append((text, duration))

    def set_emotion(self, emotion):
        self.emotions.append(emotion)


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


if __name__ == "__main__":
    unittest.main()

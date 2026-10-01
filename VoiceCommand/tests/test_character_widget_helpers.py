import unittest
from unittest.mock import MagicMock, patch
import tempfile
import os
import json

from PySide6.QtCore import QPoint, QRect, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from ui.character_widget import (
    CharacterWidget,
    _append_bubble_history,
    _is_geometry_animation_running,
    _is_thinking_bubble_text,
    _load_random_custom_message,
    _sync_walk_animation_end_value,
)
from ui.speech_bubble import SpeechBubble


class _FakeAnimation:
    def __init__(self, state=QPropertyAnimation.Stopped, end_value=None):
        self._state = state
        self._end_value = end_value
        self.updated_end_value = None

    def state(self):
        return self._state

    def endValue(self):
        return self._end_value

    def setEndValue(self, value):
        self.updated_end_value = value
        self._end_value = value


class _FakeMouseEvent:
    def __init__(self, pos: QPoint, button=Qt.LeftButton):
        self._pos = pos
        self._button = button

    def globalPos(self):
        return self._pos

    def button(self):
        return self._button


class _FakeScreen:
    def __init__(self, geometry: QRect, available_geometry: QRect | None = None):
        self._geometry = geometry
        self._available_geometry = available_geometry or geometry

    def geometry(self):
        return self._geometry

    def availableGeometry(self):
        return self._available_geometry


class _FakeAffinityManager:
    def __init__(self):
        self.calls = []

    def add_points(self, points, reason=""):
        self.calls.append((points, reason))
        return False


class CharacterWidgetHelperTests(unittest.TestCase):
    def _make_widget(self):
        app = QApplication.instance() or QApplication([])

        with (
            patch.object(CharacterWidget, "show", autospec=True),
            patch.object(CharacterWidget, "move_to_bottom", autospec=True),
            patch.object(CharacterWidget, "_enforce_topmost", autospec=True),
        ):
            widget = CharacterWidget()

        self.addCleanup(widget.cleanup)
        self.addCleanup(app.processEvents)
        return widget

    def test_is_thinking_bubble_text_matches_exact_indicator(self):
        self.assertTrue(_is_thinking_bubble_text("생각 중..."))
        self.assertTrue(_is_thinking_bubble_text("Thinking..."))
        self.assertTrue(_is_thinking_bubble_text("考え中..."))

    def test_is_thinking_bubble_text_rejects_other_messages(self):
        self.assertFalse(_is_thinking_bubble_text("작업 완료"))
        self.assertFalse(_is_thinking_bubble_text(""))

    def test_is_geometry_animation_running_detects_running_animation(self):
        self.assertTrue(
            _is_geometry_animation_running(
                _FakeAnimation(state=QPropertyAnimation.Running)
            )
        )
        self.assertFalse(
            _is_geometry_animation_running(
                _FakeAnimation(state=QPropertyAnimation.Stopped)
            )
        )
        self.assertFalse(_is_geometry_animation_running(None))

    def test_sync_walk_animation_end_value_updates_ground_y_when_changed(self):
        animation = _FakeAnimation(end_value=QRect(10, 20, 30, 40))

        updated_target = _sync_walk_animation_end_value(
            animation,
            walk_target_y=20,
            ground_y=48,
        )

        self.assertEqual(updated_target, 48)
        self.assertEqual(animation.updated_end_value, QRect(10, 48, 30, 40))

    def test_sync_walk_animation_end_value_ignores_small_or_missing_changes(self):
        animation = _FakeAnimation(end_value=QRect(10, 20, 30, 40))

        unchanged_target = _sync_walk_animation_end_value(
            animation,
            walk_target_y=20,
            ground_y=21,
        )
        self.assertEqual(unchanged_target, 20)
        self.assertIsNone(animation.updated_end_value)

        no_rect_target = _sync_walk_animation_end_value(
            _FakeAnimation(end_value=None),
            walk_target_y=20,
            ground_y=48,
        )
        self.assertEqual(no_rect_target, 20)

    def test_character_widget_initializes_without_move_animation_attribute_error(self):
        widget = self._make_widget()

        self.assertIsNone(widget.move_animation)

    def test_emotion_keeps_idle_frame_animation_running_without_overlay(self):
        widget = self._make_widget()

        with patch("ui.character_widget._RNG.choices", return_value=["idle"]):
            widget._change_emotion_slot("기쁨")

        self.assertEqual(widget.current_animation, "idle")
        self.assertFalse(hasattr(widget, "emote_overlay"))
        self.assertTrue(widget.animation_timer.isActive())

    def test_speech_bubble_anchors_to_cached_opaque_frame_top(self):
        widget = self._make_widget()

        with tempfile.TemporaryDirectory() as tmp:
            image_path = os.path.join(tmp, "transparent-top.png")
            image = QImage(40, 40, QImage.Format_ARGB32)
            image.fill(Qt.transparent)
            image.setPixelColor(5, 12, QColor(255, 255, 255, 255))
            self.assertTrue(image.save(image_path))

            widget.image_scale = 1.0
            widget.animations = {"idle": [image_path]}
            widget.current_animation = "idle"
            widget.frame_index = 0
            widget.facing_right = True
            widget.move(100, 200)
            with (
                patch.object(widget, "get_ground_y", return_value=200),
                patch.object(
                    widget,
                    "get_screen_geometry",
                    return_value=QRect(0, 0, 1920, 1080),
                ),
            ):
                widget.update_frame()
                bubble = SpeechBubble("hello", widget)

            expected_y = (
                widget.mapToGlobal(QPoint(0, 0)).y()
                + 12
                - bubble.height()
                - 5
            )
            self.assertEqual(widget.head_top_offset(), 12)
            self.assertEqual(bubble.y(), max(10, expected_y))
            bubble.close()

    def test_speech_bubble_fits_newline_text_and_stays_on_screen(self):
        widget = self._make_widget()
        widget.move(-500, 300)
        one = SpeechBubble("a", widget)
        two = SpeechBubble("a\nb", widget)
        self.addCleanup(one.close)
        self.addCleanup(two.close)
        self.assertGreaterEqual(two.height() - one.height(), one.fm.height() - 1)
        area = widget.screen().availableGeometry()
        self.assertGreaterEqual(two.x(), area.left())

    def test_speech_bubble_caps_long_text_and_hides_markdown(self):
        widget = self._make_widget()
        short = SpeechBubble("짧은 말", widget)
        long = SpeechBubble("**가을:** " + "선선한 바람과 함께 산책하기 좋은 계절입니다. " * 40 + "마지막 문장", widget)
        self.addCleanup(short.close)
        self.addCleanup(long.close)

        self.assertLessEqual(
            long.height(),
            long.fm.lineSpacing() * SpeechBubble.MAX_LINES + long.padding * 2 + 15,
        )
        self.assertTrue(long.display_text.startswith("…"))
        self.assertTrue(long.display_text.endswith("마지막 문장"))
        self.assertNotIn("**", long.display_text)
        self.assertEqual(short.display_text, "짧은 말")

    def test_first_stream_token_survives_without_existing_bubble(self):
        widget = self._make_widget()
        widget._on_stream_token_slot("안")
        widget._on_stream_token_slot("녕")
        self.assertEqual(widget._stream_buffer, "안녕")
        self.assertEqual(widget.speech_bubble.text, "안녕")
        widget._hide_speech_bubble_slot()

    def test_open_settings_passes_update_checker_and_reinits_tts_async(self):
        widget = self._make_widget()
        checker = object()
        widget.set_update_checker(checker)
        dialog = MagicMock()
        dialog.exec.return_value = True
        dialog.tts_settings_changed.return_value = True
        dialog.theme_settings_changed.return_value = False
        with (
            patch("ui.settings_dialog.SettingsDialog", return_value=dialog) as cls,
            patch("ui.settings_dialog.should_apply_microphone", return_value=False),
            patch("ui.settings_dialog.reinitialize_tts_async") as reinit,
        ):
            widget.open_settings()
        cls.assert_called_once_with(widget, update_checker=checker)
        reinit.assert_called_once()

    def test_mouse_release_restarts_animation_timer_at_70ms(self):
        widget = self._make_widget()
        widget.dragging = True
        widget.animation_timer.setInterval(120)

        widget.mouseReleaseEvent(_FakeMouseEvent(QPoint(0, 0)))

        self.assertEqual(widget.animation_timer.interval(), 70)

    def test_smooth_ceiling_enforces_minimum_duration(self):
        widget = self._make_widget()
        screen = QRect(100, 50, 800, 600)
        widget.move(screen.x() + 10, screen.y() - 5)

        with patch.object(widget, "get_screen_geometry", return_value=screen):
            widget.smooth_ceiling()

        self.assertEqual(widget.move_animation.duration(), 100)

    def test_move_to_bottom_respects_screen_offsets(self):
        widget = self._make_widget()
        screen = QRect(100, 50, 800, 600)

        with (
            patch.object(widget, "get_screen_geometry", return_value=screen),
            patch.object(widget, "get_ground_y", return_value=432),
            patch("ui.character_widget._RNG.randint", return_value=123) as randint_mock,
        ):
            widget.move_to_bottom()

        randint_mock.assert_called_once_with(100, screen.x() + screen.width() - widget.width())
        self.assertEqual(widget.pos(), QPoint(123, 432))

    def test_mouse_move_event_clamps_to_offset_screen_bounds(self):
        widget = self._make_widget()
        widget.dragging = True
        widget.offset = QPoint(0, 0)
        screen = QRect(100, 50, 800, 600)
        margin = max(0, (widget.width() // 2) - 30)

        with patch.object(widget, "_get_virtual_desktop_rect", return_value=screen):
            widget.mouseMoveEvent(_FakeMouseEvent(QPoint(2000, 2000)))
            self.assertEqual(
                widget.pos(),
                QPoint(
                    screen.x() + screen.width() - widget.width() + margin,
                    screen.y() + screen.height() - widget.height() + 25,
                ),
            )

            widget.mouseMoveEvent(_FakeMouseEvent(QPoint(-500, -500)))
            self.assertEqual(
                widget.pos(),
                QPoint(screen.x() - margin, screen.y()),
            )

    def test_update_physics_clamps_horizontal_bounce_to_offset_screen_bounds(self):
        widget = self._make_widget()
        screen = QRect(100, 50, 800, 600)
        margin = max(0, (widget.width() // 2) - 30)
        ground_y = 400

        with (
            patch.object(widget, "get_screen_geometry", return_value=screen),
            patch.object(widget, "get_ground_y", return_value=ground_y),
            patch.object(widget, "_get_virtual_desktop_rect", return_value=screen),
            patch.object(widget, "_update_current_screen"),
        ):
            widget.move(300, ground_y)
            widget.velocity_x = -1000
            widget.velocity_y = 0
            widget.update_physics()
            self.assertEqual(widget.x(), screen.x() - margin)

            widget.move(300, ground_y)
            widget.velocity_x = 1000
            widget.velocity_y = 0
            widget.update_physics()
            self.assertEqual(
                widget.x(),
                screen.x() + screen.width() - widget.width() + margin,
            )

    def test_get_virtual_desktop_rect_combines_all_screens(self):
        widget = self._make_widget()
        screens = [
            _FakeScreen(QRect(-1280, 100, 1280, 1024)),
            _FakeScreen(QRect(0, 0, 1920, 1080)),
            _FakeScreen(QRect(2000, -50, 1600, 900)),
        ]

        with patch("ui.character_widget.QApplication.screens", return_value=screens):
            self.assertEqual(
                widget._get_virtual_desktop_rect(),
                QRect(-1280, -50, 4880, 1174),
            )

    def test_display_settings_are_clamped_to_allowed_range(self):
        widget = self._make_widget()
        settings = {"character_scale": 99.0, "character_ground_offset": -9999}

        with patch("core.config_manager.ConfigManager.load_settings", return_value=settings):
            widget._load_display_settings()

        self.assertEqual(widget.image_scale, CharacterWidget.SCALE_MAX)
        self.assertEqual(widget.ground_offset, CharacterWidget.GROUND_OFFSET_MIN)

    def test_display_settings_fall_back_to_defaults_on_invalid_value(self):
        widget = self._make_widget()
        settings = {"character_scale": "abc", "character_ground_offset": None}

        with patch("core.config_manager.ConfigManager.load_settings", return_value=settings):
            widget._load_display_settings()

        self.assertEqual(widget.image_scale, 1.0)
        self.assertEqual(widget.ground_offset, CharacterWidget.GROUND_OFFSET_DEFAULT)

    def test_get_ground_y_reflects_configured_ground_offset(self):
        widget = self._make_widget()
        screen = QRect(0, 0, 1920, 1040)

        with patch.object(widget, "get_screen_geometry", return_value=screen):
            widget.ground_offset = 4
            default_y = widget.get_ground_y(height=300)
            widget.ground_offset = -30
            raised_y = widget.get_ground_y(height=300)

        self.assertEqual(default_y - raised_y, 34)

    def test_apply_display_settings_clears_cache_and_refreshes_frame(self):
        widget = self._make_widget()
        widget.image_cache.put("stale", object())
        settings = {"character_scale": 1.5, "character_ground_offset": 10}

        with (
            patch("core.config_manager.ConfigManager.load_settings", return_value=settings),
            patch.object(widget, "update_frame") as update_frame,
        ):
            widget.apply_display_settings()

        self.assertEqual(widget.image_scale, 1.5)
        self.assertEqual(widget.ground_offset, 10)
        self.assertIsNone(widget.image_cache.get("stale"))
        update_frame.assert_called_once()

    def test_apply_display_settings_uses_given_values_without_reading_config(self):
        widget = self._make_widget()

        with (
            patch("core.config_manager.ConfigManager.load_settings") as load_settings,
            patch.object(widget, "update_frame"),
        ):
            widget.apply_display_settings(scale=1.8, ground_offset=-20)

        load_settings.assert_not_called()
        self.assertEqual(widget.image_scale, 1.8)
        self.assertEqual(widget.ground_offset, -20)

    def test_apply_display_settings_clamps_preview_values(self):
        widget = self._make_widget()

        with patch.object(widget, "update_frame"):
            widget.apply_display_settings(scale=50.0, ground_offset=5000)

        self.assertEqual(widget.image_scale, CharacterWidget.SCALE_MAX)
        self.assertEqual(widget.ground_offset, CharacterWidget.GROUND_OFFSET_MAX)

    def test_update_current_screen_tracks_screen_by_widget_center(self):
        widget = self._make_widget()
        primary = _FakeScreen(QRect(0, 0, 1920, 1080))
        secondary = _FakeScreen(QRect(1920, 0, 1920, 1080))
        widget._current_screen = primary
        widget._screen_geom_cache_time = 123
        widget.move(2100, 100)

        with patch("ui.character_widget.QApplication.screens", return_value=[primary, secondary]):
            widget._update_current_screen()

        self.assertIs(widget._current_screen, secondary)
        self.assertIsNone(widget._screen_geom_cache)
        self.assertEqual(widget._screen_geom_cache_time, 0)

    def test_update_current_screen_falls_back_to_nearest_screen_in_gap(self):
        widget = self._make_widget()
        primary = _FakeScreen(QRect(0, 0, 1920, 1080))
        secondary = _FakeScreen(QRect(2500, 0, 1920, 1080))
        widget._current_screen = primary
        widget._screen_geom_cache_time = 55
        widget.move(2350, 100)

        with patch("ui.character_widget.QApplication.screens", return_value=[primary, secondary]):
            widget._update_current_screen()

        self.assertIs(widget._current_screen, secondary)
        self.assertIsNone(widget._screen_geom_cache)
        self.assertEqual(widget._screen_geom_cache_time, 0)

    def test_get_screen_geometry_uses_current_screen_instead_of_primary_screen(self):
        widget = self._make_widget()
        primary = _FakeScreen(QRect(0, 0, 1920, 1080), QRect(0, 0, 1920, 1040))
        secondary = _FakeScreen(QRect(1920, 0, 1920, 1080), QRect(1920, 0, 1920, 1000))
        widget._current_screen = secondary
        widget._screen_geom_cache_time = 0

        with (
            patch("ui.character_widget.QApplication.primaryScreen", return_value=primary),
            patch("ui.character_widget.QApplication.screens", return_value=[primary, secondary]),
            patch("ui.character_widget.sys.platform", "linux"),
            patch("ui.character_widget.time.time", side_effect=[1.0, 1.0]),
        ):
            screen_geom = widget.get_screen_geometry()

        self.assertEqual(screen_geom, QRect(1920, 0, 1920, 1000))

    def test_smooth_walk_clamps_to_virtual_desktop_bounds(self):
        widget = self._make_widget()
        widget.move(3500, 300)
        current_screen = _FakeScreen(QRect(1920, 0, 1920, 1080))
        widget._current_screen = current_screen
        vd = QRect(0, 0, 3840, 1080)
        margin = max(0, (widget.width() // 2) - 30)

        with (
            patch.object(widget, "get_screen_geometry", return_value=current_screen.geometry()),
            patch.object(widget, "get_ground_y", return_value=400),
            patch.object(widget, "_get_virtual_desktop_rect", return_value=vd),
            patch("ui.character_widget._RNG.choice", return_value=1),
            patch("ui.character_widget._RNG.randint", return_value=400),
        ):
            widget.smooth_walk()

        self.assertEqual(
            widget.move_animation.endValue().x(),
            vd.x() + vd.width() - widget.width() + margin,
        )

    def test_mouse_release_updates_current_screen_immediately(self):
        widget = self._make_widget()
        primary = _FakeScreen(QRect(0, 0, 1920, 1080))
        secondary = _FakeScreen(QRect(1920, 0, 1920, 1080))
        widget._current_screen = primary
        widget.dragging = True
        widget.move(2100, 100)

        with patch("ui.character_widget.QApplication.screens", return_value=[primary, secondary]):
            widget.mouseReleaseEvent(_FakeMouseEvent(QPoint(0, 0)))

        self.assertIs(widget._current_screen, secondary)

    def test_update_physics_updates_current_screen_after_horizontal_crossing(self):
        widget = self._make_widget()
        primary = _FakeScreen(QRect(0, 0, 1920, 1080))
        secondary = _FakeScreen(QRect(1920, 0, 1920, 1080))
        widget._current_screen = primary
        widget.move(1890, 400)
        widget.velocity_x = 60
        widget.velocity_y = 0

        with (
            patch("ui.character_widget.QApplication.screens", return_value=[primary, secondary]),
            patch.object(widget, "get_ground_y", return_value=400),
            patch.object(widget, "_get_virtual_desktop_rect", return_value=QRect(0, 0, 3840, 1080)),
        ):
            widget.update_physics()

        self.assertIs(widget._current_screen, secondary)

    def test_append_bubble_history_keeps_latest_50_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bubble_history.json")
            with patch("core.resource_manager.ResourceManager.get_writable_path", return_value=path):
                for index in range(55):
                    _append_bubble_history(f"msg-{index}")

            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)

        self.assertEqual(len(payload["history"]), 50)
        self.assertEqual(payload["history"][0]["text"], "msg-54")
        self.assertEqual(payload["history"][-1]["text"], "msg-5")

    def test_load_random_custom_message_reads_saved_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "custom_messages.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"messages": ["alpha", "beta"]}, handle, ensure_ascii=False)

            with (
                patch("core.resource_manager.ResourceManager.get_writable_path", return_value=path),
                patch("ui.character_widget.secrets.SystemRandom.choice", return_value="beta"),
            ):
                self.assertEqual(_load_random_custom_message(), "beta")

    def test_update_sleepy_mode_adjusts_animation_interval_and_yawn_timer(self):
        widget = self._make_widget()
        widget._sleepy_mode = False

        with (
            patch("ui.character_widget.CharacterWidget._schedule_yawn") as schedule_mock,
            patch("datetime.datetime") as datetime_mock,
        ):
            datetime_mock.now.return_value.hour = 23
            widget._update_sleepy_mode()

        self.assertTrue(widget._sleepy_mode)
        self.assertEqual(widget.animation_timer.interval(), 110)
        schedule_mock.assert_called_once()

    def test_track_mouse_triggers_pet_when_hovering_slowly(self):
        widget = self._make_widget()
        widget._trigger_pet = MagicMock()
        widget.move(100, 100)
        widget.resize(120, 120)
        widget._pet_hover_duration = 1.4
        widget._prev_cursor_pos = QPoint(120, 120)

        with patch("ui.character_widget.QCursor.pos", return_value=QPoint(121, 121)):
            widget.track_mouse()

        widget._trigger_pet.assert_called_once()

    def test_mouse_release_rewards_click_without_drag_motion(self):
        widget = self._make_widget()
        affinity = _FakeAffinityManager()
        widget._affinity_manager = affinity
        widget.mousePressEvent(_FakeMouseEvent(QPoint(150, 150)))

        with patch.object(widget, "_update_current_screen"):
            widget.mouseReleaseEvent(_FakeMouseEvent(QPoint(150, 150)))

        self.assertEqual(affinity.calls, [(1, "click")])

    def test_character_click_requests_one_shot_listening(self):
        widget = self._make_widget()
        widget.voice_thread = MagicMock()

        with (
            patch("VoiceCommand.is_tts_playing", return_value=False),
            patch("ui.character_widget.ConfigManager.get", return_value="toggle"),
            patch.object(widget, "_update_current_screen"),
        ):
            widget.mousePressEvent(_FakeMouseEvent(QPoint(150, 150)))
            widget.mouseReleaseEvent(_FakeMouseEvent(QPoint(150, 150)))

        widget.voice_thread.request_listening.assert_called_once_with()
        widget.voice_thread.release_listening.assert_not_called()

    def test_character_click_stops_active_speech_without_starting_listening(self):
        widget = self._make_widget()
        widget.voice_thread = MagicMock()

        with (
            patch("VoiceCommand.is_tts_playing", return_value=True),
            patch("VoiceCommand.stop_speaking") as stop_speaking,
            patch.object(widget, "_update_current_screen"),
        ):
            widget.mousePressEvent(_FakeMouseEvent(QPoint(150, 150)))
            widget.mouseReleaseEvent(_FakeMouseEvent(QPoint(150, 150)))

        stop_speaking.assert_called_once_with()
        widget.voice_thread.request_listening.assert_not_called()
        widget.voice_thread.release_listening.assert_not_called()

    def test_character_long_press_uses_push_to_talk_until_release(self):
        widget = self._make_widget()
        widget.voice_thread = MagicMock()

        with (
            patch("ui.character_widget.ConfigManager.get", return_value="push_to_talk"),
            patch.object(widget, "_update_current_screen"),
        ):
            widget.mousePressEvent(_FakeMouseEvent(QPoint(150, 150)))
            widget._begin_character_push_to_talk()
            widget.mouseReleaseEvent(_FakeMouseEvent(QPoint(150, 150)))

        widget.voice_thread.request_listening.assert_called_once_with(
            push_to_talk=True
        )
        widget.voice_thread.release_listening.assert_called_once_with()

    def test_mouse_release_does_not_reward_drag_motion(self):
        widget = self._make_widget()
        affinity = _FakeAffinityManager()
        widget._affinity_manager = affinity
        widget.mousePressEvent(_FakeMouseEvent(QPoint(150, 150)))
        widget.mouseMoveEvent(_FakeMouseEvent(QPoint(170, 170)))

        with patch.object(widget, "_update_current_screen"):
            widget.mouseReleaseEvent(_FakeMouseEvent(QPoint(170, 170)))

        self.assertEqual(affinity.calls, [])


if __name__ == "__main__":
    unittest.main()

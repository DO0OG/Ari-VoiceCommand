import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QRect, QPropertyAnimation, Qt
from PySide6.QtWidgets import QApplication

from ui.character_widget import (
    CharacterWidget,
    _is_geometry_animation_running,
    _is_thinking_bubble_text,
    _sync_walk_animation_end_value,
)


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
            patch("ui.character_widget._RNG.randint", return_value=123) as randint_mock,
        ):
            widget.move_to_bottom()

        randint_mock.assert_called_once_with(100, 700)
        self.assertEqual(widget.pos(), QPoint(123, 450))

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


if __name__ == "__main__":
    unittest.main()

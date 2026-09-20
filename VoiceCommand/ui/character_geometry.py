from typing import Optional
from PySide6.QtCore import QPropertyAnimation, QRect


def _is_geometry_animation_running(animation: Optional[QPropertyAnimation]) -> bool:
    return animation is not None and animation.state() == QPropertyAnimation.Running


def _sync_walk_animation_end_value(
    animation: Optional[QPropertyAnimation],
    walk_target_y: Optional[int],
    ground_y: int,
    *,
    threshold: int = 2,
) -> Optional[int]:
    if animation is None or walk_target_y is None:
        return walk_target_y
    if abs(walk_target_y - ground_y) <= threshold:
        return walk_target_y

    end_value = animation.endValue()
    if end_value is None:
        return walk_target_y

    animation.setEndValue(
        QRect(end_value.x(), int(ground_y), end_value.width(), end_value.height())
    )
    return int(ground_y)



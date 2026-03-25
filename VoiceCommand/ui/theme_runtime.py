"""
실시간 테마 반영 유틸리티
테마 JSON 저장 후 앱 전체 재시작 없이 열려 있는 UI를 새 테마 기준으로 재생성합니다.
"""
from __future__ import annotations

import importlib
import logging


def apply_live_theme(tray_icon=None, character_widget=None):
    from ui import theme as theme_module

    importlib.reload(theme_module)

    from ui import speech_bubble as speech_bubble_module
    from ui import common as common_module
    from ui import memory_panel as memory_panel_module
    from ui import scheduler_panel as scheduler_panel_module
    from ui import text_interface as text_interface_module

    importlib.reload(speech_bubble_module)
    importlib.reload(common_module)
    importlib.reload(memory_panel_module)
    importlib.reload(scheduler_panel_module)
    importlib.reload(text_interface_module)

    if tray_icon is not None:
        try:
            tray_icon._apply_menu_theme()
        except Exception as exc:
            logging.debug(f"[ThemeRuntime] 트레이 메뉴 갱신 실패: {exc}")

    text_interface = getattr(tray_icon, "text_interface", None) if tray_icon else None
    if text_interface is None and character_widget is not None:
        text_interface = getattr(character_widget, "text_interface", None)
    if text_interface is not None and hasattr(text_interface, "refresh_theme"):
        try:
            text_interface.refresh_theme()
        except Exception as exc:
            logging.debug(f"[ThemeRuntime] 텍스트 UI 갱신 실패: {exc}")

    if character_widget is not None and hasattr(character_widget, "refresh_theme"):
        try:
            character_widget.refresh_theme()
        except Exception as exc:
            logging.debug(f"[ThemeRuntime] 캐릭터 갱신 실패: {exc}")

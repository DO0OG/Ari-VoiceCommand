"""
UI 테마 로더
기본 테마 JSON을 `theme/` 폴더에 두고, 배포 시 `%APPDATA%/Ari/theme`로 복사해
사용자가 Python 코드 수정 없이 JSON만 편집해 UI 테마를 바꿀 수 있게 합니다.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional


_DEFAULT_THEME_KEY = "default"
_DEFAULT_SCALE = 1.0
_BASE_FONT_SIZES = {
    "title": 11,
    "large": 10,
    "normal": 9,
    "small": 8,
}

_DEFAULT_THEME_DATA: Dict[str, object] = {
    "id": "default",
    "name": "기본 블루",
    "font_family": "맑은 고딕",
    "colors": {
        "primary": "#4a90e2",
        "primary_dark": "#357abd",
        "accent": "#ff7b54",
        "success": "#27ae60",
        "warning": "#e67e22",
        "danger": "#e74c3c",
        "muted": "#888888",
        "muted_light": "#aaaaaa",
        "text_primary": "#333333",
        "text_secondary": "#555555",
        "text_panel": "#4f5b66",
        "bg_main": "rgba(250, 250, 252, 245)",
        "bg_panel": "rgba(245, 247, 250, 248)",
        "bg_white": "#ffffff",
        "bg_input": "#f8f9fa",
        "bg_chat_user": "#e3f2fd",
        "bg_chat_aari": "#fff3e0",
        "bg_status": "qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(74,144,226,28), stop:1 rgba(255,123,84,28))",
        "bg_dashboard": "qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(74,144,226,18), stop:1 rgba(255,123,84,18))",
        "bg_suggestion": "rgba(248, 250, 255, 200)",
        "bg_chip_primary": "#e8f0fe",
        "bg_chip_warn": "#fff3e0",
        "titlebar": "#2c3e50",
        "border_light": "rgba(200, 200, 200, 100)",
        "border_div": "rgba(220, 220, 220, 120)",
        "border_input": "#e0e0e0",
        "border_card": "#e8ecf0",
    },
}


@dataclass(frozen=True)
class ThemePalette:
    key: str
    name: str
    font_family: str
    colors: Dict[str, str]


def _load_settings() -> dict:
    try:
        from core.config_manager import ConfigManager
        return ConfigManager.load_settings()
    except Exception:
        return {}


def _theme_scale(raw_value) -> float:
    try:
        scale = float(raw_value)
    except (TypeError, ValueError):
        return _DEFAULT_SCALE
    return max(0.9, min(scale, 1.35))


def theme_dir() -> str:
    try:
        from core.resource_manager import ResourceManager
        return ResourceManager.ensure_theme_files()
    except Exception:
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "theme")


def _theme_path(key: str) -> str:
    return os.path.join(theme_dir(), f"{key}.json")


def _safe_read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        logging.warning(f"[Theme] JSON 로드 실패: {path} ({exc})")
        return {}


def _normalize_theme_payload(payload: dict, fallback_key: str) -> ThemePalette:
    colors = dict(_DEFAULT_THEME_DATA["colors"])
    colors.update(payload.get("colors", {}) or {})
    return ThemePalette(
        key=str(payload.get("id", fallback_key) or fallback_key),
        name=str(payload.get("name", fallback_key) or fallback_key),
        font_family=str(payload.get("font_family", _DEFAULT_THEME_DATA["font_family"])),
        colors=colors,
    )


def load_theme_palette(theme_key: str = "") -> ThemePalette:
    key = (theme_key or _load_settings().get("ui_theme_preset", _DEFAULT_THEME_KEY) or _DEFAULT_THEME_KEY).strip()
    payload = _safe_read_json(_theme_path(key))
    if not payload and key != _DEFAULT_THEME_KEY:
        payload = _safe_read_json(_theme_path(_DEFAULT_THEME_KEY))
        key = _DEFAULT_THEME_KEY
    if not payload:
        payload = dict(_DEFAULT_THEME_DATA)
    palette = _normalize_theme_payload(payload, key)
    font_override = str(_load_settings().get("ui_font_family", "")).strip()
    if font_override:
        palette = ThemePalette(
            key=palette.key,
            name=palette.name,
            font_family=font_override,
            colors=palette.colors,
        )
    return palette


def available_theme_presets() -> List[tuple[str, str]]:
    presets: List[tuple[str, str]] = []
    folder = theme_dir()
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if not name.lower().endswith(".json"):
                continue
            key = os.path.splitext(name)[0]
            payload = _safe_read_json(os.path.join(folder, name))
            label = str(payload.get("name", key)) if payload else key
            presets.append((key, label))
    if not presets:
        presets.append((_DEFAULT_THEME_KEY, str(_DEFAULT_THEME_DATA["name"])))
    return presets


def save_custom_theme(theme_key: str, name: str, colors: Optional[Dict[str, str]] = None, font_family: str = "") -> str:
    normalized_key = (theme_key or "custom").strip().lower().replace(" ", "_")
    palette = load_theme_palette(_DEFAULT_THEME_KEY)
    payload = {
        "id": normalized_key,
        "name": name or normalized_key,
        "font_family": font_family or palette.font_family,
        "colors": dict(palette.colors),
    }
    if colors:
        payload["colors"].update(colors)
    path = _theme_path(normalized_key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


_SETTINGS = _load_settings()
_ACTIVE_THEME = load_theme_palette(_SETTINGS.get("ui_theme_preset", _DEFAULT_THEME_KEY))
_FONT_SCALE = _theme_scale(_SETTINGS.get("ui_theme_scale", _DEFAULT_SCALE))


def theme_metadata() -> dict:
    return {
        "preset_key": _ACTIVE_THEME.key,
        "preset_name": _ACTIVE_THEME.name,
        "font_family": _ACTIVE_THEME.font_family,
        "scale": _FONT_SCALE,
        "theme_dir": theme_dir(),
    }


def scaled_font(size: int) -> int:
    return max(7, int(round(size * _FONT_SCALE)))


def _color(name: str) -> str:
    return str(_ACTIVE_THEME.colors.get(name, _DEFAULT_THEME_DATA["colors"][name]))


FONT_KO = _ACTIVE_THEME.font_family
FONT_SIZE_TITLE = scaled_font(_BASE_FONT_SIZES["title"])
FONT_SIZE_LARGE = scaled_font(_BASE_FONT_SIZES["large"])
FONT_SIZE_NORMAL = scaled_font(_BASE_FONT_SIZES["normal"])
FONT_SIZE_SMALL = scaled_font(_BASE_FONT_SIZES["small"])

COLOR_PRIMARY = _color("primary")
COLOR_PRIMARY_DARK = _color("primary_dark")
COLOR_ACCENT = _color("accent")
COLOR_SUCCESS = _color("success")
COLOR_WARNING = _color("warning")
COLOR_DANGER = _color("danger")
COLOR_MUTED = _color("muted")
COLOR_MUTED_LIGHT = _color("muted_light")
COLOR_TEXT_PRIMARY = _color("text_primary")
COLOR_TEXT_SECONDARY = _color("text_secondary")
COLOR_TEXT_PANEL = _color("text_panel")
COLOR_BG_MAIN = _color("bg_main")
COLOR_BG_PANEL = _color("bg_panel")
COLOR_BG_WHITE = _color("bg_white")
COLOR_BG_INPUT = _color("bg_input")
COLOR_BG_CHAT_USER = _color("bg_chat_user")
COLOR_BG_CHAT_AARI = _color("bg_chat_aari")
COLOR_BG_STATUS = _color("bg_status")
COLOR_BG_DASHBOARD = _color("bg_dashboard")
COLOR_BG_SUGGESTION = _color("bg_suggestion")
COLOR_BG_CHIP_PRIMARY = _color("bg_chip_primary")
COLOR_BG_CHIP_WARN = _color("bg_chip_warn")
COLOR_TITLEBAR = _color("titlebar")
COLOR_BORDER_LIGHT = _color("border_light")
COLOR_BORDER_DIV = _color("border_div")
COLOR_BORDER_INPUT = _color("border_input")
COLOR_BORDER_CARD = _color("border_card")

TITLEBAR_HEIGHT = 42
WINDOW_W_CHAT = 420
WINDOW_H_CHAT = 640
WINDOW_W_SCHEDULER = 420
WINDOW_H_SCHEDULER = 560
WINDOW_W_MEMORY = 440
WINDOW_H_MEMORY = 560
BUTTON_SM = 22
BUTTON_MD = 28
BUTTON_LG = 32
BUTTON_XL = 36
RADIUS_XS = "6px"
RADIUS_SM = "8px"
RADIUS_MD = "12px"
RADIUS_LG = "14px"
RADIUS_XL = "15px"
RADIUS_CIRCLE = "50%"
SHADOW_BLUR = 15
SHADOW_BLUR_LG = 18
SHADOW_OFFSET = 5
SHADOW_OFFSET_SM = 4
MARGIN_PANEL = 10
MARGIN_INNER = 14
SPACING_SM = 4
SPACING_MD = 8
SPACING_LG = 10
ANIM_FAST = 250
ANIM_NORMAL = 300
SUGGESTION_REFRESH = 30_000
STATUS_REFRESH = 5_000
DASHBOARD_AUTO_HIDE = 5_000
TEMP_STATUS_DURATION = 4_000

SCROLLBAR_STYLE = f"""
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ border: none; background: {COLOR_BG_INPUT};
                          width: 8px; border-radius: 4px; }}
    QScrollBar::handle:vertical {{ background: {COLOR_BORDER_INPUT}; border-radius: 4px; }}
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{ border: none; background: none; }}
"""

SCROLLBAR_THIN_STYLE = f"""
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ border: none; background: {COLOR_BG_INPUT};
                          width: 7px; border-radius: 3px; }}
    QScrollBar::handle:vertical {{ background: {COLOR_BORDER_INPUT}; border-radius: 3px; }}
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{ border: none; background: none; }}
"""

INPUT_STYLE = f"""
    QLineEdit {{ border: 1px solid {COLOR_BORDER_INPUT}; border-radius: {RADIUS_XS};
                 padding: 0 10px; background: {COLOR_BG_INPUT}; height: 30px; color: {COLOR_TEXT_PRIMARY}; }}
    QLineEdit:focus {{ border: 1px solid {COLOR_PRIMARY}; background: {COLOR_BG_WHITE}; }}
"""

CHAT_INPUT_STYLE = f"""
    QLineEdit {{ border: 1px solid {COLOR_BORDER_INPUT}; border-radius: 18px;
                 padding: 0 15px; background: {COLOR_BG_INPUT}; color: {COLOR_TEXT_PRIMARY}; }}
    QLineEdit:focus {{ border: 1px solid {COLOR_PRIMARY}; background: {COLOR_BG_WHITE}; }}
"""

TAB_STYLE = f"""
    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{ font-family: '{FONT_KO}'; font-size: {FONT_SIZE_NORMAL}pt;
                    padding: 8px 18px; color: {COLOR_MUTED}; }}
    QTabBar::tab:selected {{ color: {COLOR_PRIMARY};
                             border-bottom: 2px solid {COLOR_PRIMARY}; }}
"""

MENU_STYLE = f"""
    QMenu {{
        background-color: {COLOR_BG_WHITE};
        border: 1px solid {COLOR_BORDER_LIGHT};
        border-radius: {RADIUS_SM};
        padding: 4px 0px;
    }}
    QMenu::item {{
        padding: 8px 30px;
        color: {COLOR_TEXT_PRIMARY};
        font-family: '{FONT_KO}';
        font-size: {FONT_SIZE_NORMAL}pt;
    }}
    QMenu::item:selected {{
        background-color: {COLOR_PRIMARY};
        color: white;
    }}
    QMenu::separator {{
        height: 1px;
        background: {COLOR_BORDER_DIV};
        margin: 4px 10px;
    }}
"""


def primary_btn_style(radius: str = RADIUS_SM) -> str:
    return (
        f"QPushButton {{ background: {COLOR_PRIMARY}; color: white; "
        f"border-radius: {radius}; border: none; }}"
        f"QPushButton:hover {{ background: {COLOR_PRIMARY_DARK}; }}"
    )


def secondary_btn_style(radius: str = RADIUS_SM) -> str:
    return (
        f"QPushButton {{ background: {COLOR_BG_INPUT}; color: {COLOR_TEXT_PRIMARY}; "
        f"border-radius: {radius}; border: 1px solid {COLOR_BORDER_INPUT}; }}"
        f"QPushButton:hover {{ background: {COLOR_BG_WHITE}; border-color: {COLOR_PRIMARY}; }}"
    )


def icon_btn_style(color: str, size: int) -> str:
    radius_px = size // 2
    return (
        f"QPushButton {{ background: {color}; color: white; border: none; "
        f"border-radius: {radius_px}px; font-weight: bold; }}"
        "QPushButton:hover { opacity: 0.85; }"
    )


def close_btn_style() -> str:
    return (
        "QPushButton { background: transparent; color: white; "
        "border: none; border-radius: 15px; font-weight: bold; }"
        f"QPushButton:hover {{ background: {COLOR_DANGER}; }}"
    )

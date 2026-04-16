"""포커스 앱 연동 반응 플러그인."""
from __future__ import annotations

import logging
import secrets
import time


PLUGIN_INFO = {
    "name": "focus_app_plugin",
    "version": "1.0.0",
    "api_version": "1.0",
    "description": "포그라운드 앱 유형에 따라 캐릭터 반응을 트리거한다",
}

_RNG = secrets.SystemRandom()
_widget_ref = None
_focus_timer = None
_last_alert_times: dict[str, float] = {}
_last_app_class = ""


def _get_app_rules():
    from i18n.translator import _

    return [
        (
            "coding",
            ["code", "pycharm", "vim", "notepad++", "sublime", "cursor", "intellij"],
            "진지",
            [_("집중하고 계시는군요!"), _("열심히 코딩 중~"), _("화이팅!")],
            600,
        ),
        (
            "video",
            ["youtube", "netflix", "wavve", "tving", "disney", "vlc", "mpv", "potplayer"],
            "기대",
            [_("뭐 보세요?"), _("재미있겠다~"), _("저도 보고 싶어요!")],
            600,
        ),
        (
            "browser",
            ["chrome", "firefox", "edge", "whale", "opera"],
            "평온",
            [_("인터넷 서핑 중~"), _("뭐 찾고 계세요?")],
            900,
        ),
        (
            "game",
            ["steam", "epicgames", "battlenet", "lol", "league"],
            "기대",
            [_("게임 하세요? 저도 보고 싶어요!"), _("이기세요!")],
            600,
        ),
        (
            "chat",
            ["discord", "slack", "kakao", "teams", "zoom"],
            "기쁨",
            [_("누구랑 얘기 중이에요?"), _("사교적이시네요~")],
            900,
        ),
        (
            "office",
            ["word", "excel", "powerpoint", "hwp", "한글"],
            "진지",
            [_("업무 중이시군요."), _("파이팅이에요!"), _("열심히 하시네요.")],
            900,
        ),
        (
            "explorer",
            ["explorer", "finder"],
            "평온",
            [_("파일 정리 중이세요?"), _("깔끔하게요~")],
            1200,
        ),
    ]


def _classify_app(title: str, process: str):
    combined = f"{title} {process}"
    for rule_key, keywords, emotion, messages, cooldown in _get_app_rules():
        if any(keyword in combined for keyword in keywords):
            return rule_key, emotion, messages, cooldown
    return None


def _check_focus_app():
    global _last_app_class

    from core.config_manager import ConfigManager
    from core.window_inspector import (
        get_foreground_process_name,
        get_foreground_window_title,
    )

    if not ConfigManager.get("focus_app_reaction_enabled", True):
        return

    title = get_foreground_window_title()
    process = get_foreground_process_name()
    if not title and not process:
        return

    result = _classify_app(title, process)
    if result is None:
        return

    rule_key, emotion, messages, cooldown = result
    now = time.time()
    if rule_key == _last_app_class and now - _last_alert_times.get(rule_key, 0) < cooldown:
        return

    _last_app_class = rule_key
    _last_alert_times[rule_key] = now
    widget = _widget_ref
    if widget:
        widget.set_emotion(emotion)
        widget.say(_RNG.choice(messages), duration=4000)


def _toggle_focus_reaction():
    from core.config_manager import ConfigManager

    current = bool(ConfigManager.get("focus_app_reaction_enabled", True))
    updated = not current
    ConfigManager.set_value("focus_app_reaction_enabled", updated)
    if _focus_timer is not None:
        if updated and not _focus_timer.isActive():
            _focus_timer.start(30_000)
        elif not updated and _focus_timer.isActive():
            _focus_timer.stop()


def register(context):
    from PySide6.QtCore import QTimer
    from i18n.translator import _

    global _widget_ref, _focus_timer

    _widget_ref = getattr(context, "character_widget", None)
    timer_owner = _widget_ref or getattr(context, "app", None)
    _focus_timer = QTimer(timer_owner)
    _focus_timer.timeout.connect(_check_focus_app)
    if timer_owner is not None:
        _focus_timer.start(30_000)

    if callable(getattr(context, "register_menu_action", None)):
        context.register_menu_action(_("🖥️ 앱 전환 반응"), _toggle_focus_reaction)

    logging.info("[FocusAppPlugin] 로드 완료")
    return {"message": "focus_app_plugin loaded", "has_widget": _widget_ref is not None}

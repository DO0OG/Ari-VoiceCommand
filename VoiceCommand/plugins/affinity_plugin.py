"""친밀도(호감도) 시스템 플러그인."""
from __future__ import annotations

import logging
import secrets
import threading
import time
from typing import Optional


PLUGIN_INFO = {
    "name": "affinity_plugin",
    "version": "1.0.0",
    "api_version": "1.0",
    "description": "사용자와의 상호작용을 추적하여 친밀도 레벨을 관리한다",
}

LEVEL_THRESHOLDS = [0, 50, 200, 500, 1000]
_RNG = secrets.SystemRandom()
_widget_ref = None
_affinity_manager: Optional["AffinityManager"] = None


def _get_widget():
    return _widget_ref


def _get_level_names():
    from i18n.translator import _

    return [_("초면"), _("지인"), _("친구"), _("친한친구"), _("절친")]


def _get_level_up_messages():
    from i18n.translator import _

    return {
        1: [_("앞으로 잘 부탁드려요."), _("조금 익숙해졌네요.")],
        2: [_("이제 편해졌네요."), _("함께하니 좋아요.")],
        3: [_("많이 친해졌네요."), _("이제 편하게 얘기해요.")],
        4: [_("오래 알고 지냈네요."), _("이제 많이 친해진 것 같아요.")],
    }


def _get_greeting_by_level():
    from i18n.translator import _

    return {
        0: [_("네, 주인님?"), _("부르셨나요, 주인님?")],
        1: [_("네?"), _("왜요?")],
        2: [_("왜요?"), _("뭐예요?")],
        3: [_("응?"), _("왜~?")],
        4: [_("응?ㅋ"), _("왜ㅋ")],
    }


class AffinityManager:
    _SAVE_DEBOUNCE_SEC = 30.0  # 마지막 변경 후 30초 뒤 한 번만 저장

    def __init__(self):
        self._save_timer: Optional[threading.Timer] = None
        self._load()

    def _load(self):
        from core.config_manager import ConfigManager

        settings = ConfigManager.load_settings()
        self.points = int(settings.get("affinity_points", 0))
        self.level = int(settings.get("affinity_level", 0))
        self.total_clicks = int(settings.get("affinity_total_clicks", 0))
        self.total_pets = int(settings.get("affinity_total_pets", 0))
        self.total_chats = int(settings.get("affinity_total_chats", 0))
        self.last_login = str(settings.get("affinity_last_login", ""))

    def _save(self):
        from core.config_manager import ConfigManager

        settings = ConfigManager.load_settings()
        settings.update(
            {
                "affinity_points": self.points,
                "affinity_level": self.level,
                "affinity_total_clicks": self.total_clicks,
                "affinity_total_pets": self.total_pets,
                "affinity_total_chats": self.total_chats,
                "affinity_last_login": self.last_login,
            }
        )
        ConfigManager.save_settings(settings)

    def _schedule_save(self) -> None:
        """마지막 add_points 호출 후 30초 뒤에 한 번만 디스크에 저장한다."""
        if self._save_timer is not None:
            self._save_timer.cancel()
        t = threading.Timer(self._SAVE_DEBOUNCE_SEC, self._save)
        t.daemon = True
        self._save_timer = t
        t.start()

    def _calculate_level(self) -> int:
        for level in range(len(LEVEL_THRESHOLDS) - 1, -1, -1):
            if self.points >= LEVEL_THRESHOLDS[level]:
                return level
        return 0

    def add_points(self, points: int, reason: str = "") -> bool:
        self.points += int(points)
        if reason == "click":
            self.total_clicks += 1
        elif reason == "pet":
            self.total_pets += 1
        elif reason == "chat":
            self.total_chats += 1

        old_level = self.level
        self.level = self._calculate_level()
        leveled_up = self.level > old_level
        if leveled_up:
            self._save()  # 레벨업 시 즉시 저장
        else:
            self._schedule_save()  # 일반 상호작용은 디바운스 저장
        return leveled_up

    def get_level(self) -> int:
        return self.level

    def get_level_name(self) -> str:
        names = _get_level_names()
        return names[min(self.level, len(names) - 1)]

    def get_level_up_message(self) -> str:
        messages = _get_level_up_messages()
        candidates = messages.get(self.level, [])
        return _RNG.choice(candidates) if candidates else ""

    def get_greeting(self) -> str:
        greetings = _get_greeting_by_level()
        return _RNG.choice(greetings.get(self.level, greetings[0]))

    def record_daily_login(self) -> bool:
        from datetime import date

        today = date.today().isoformat()
        if self.last_login == today:
            return False
        self.last_login = today
        return self.add_points(10, "login")


def _call_original_say(widget, text: str, duration: int = 5000) -> None:
    original_say = getattr(widget, "_affinity_original_say", None)
    if callable(original_say):
        original_say(text, duration)
    else:
        widget.say(text, duration)


def _notify_level_up() -> None:
    widget = _get_widget()
    if widget is None or _affinity_manager is None:
        return

    message = _affinity_manager.get_level_up_message()
    if not message:
        return

    def _delayed_bubble():
        time.sleep(0.8)
        try:
            _call_original_say(widget, message, 3000)
        except Exception as exc:
            logging.debug("[AffinityPlugin] 레벨업 말풍선 표시 실패: %s", exc)

    threading.Thread(
        target=_delayed_bubble,
        daemon=True,
        name="ari-affinity-level-up",
    ).start()

def _on_show_affinity():
    from i18n.translator import _

    widget = _get_widget()
    if not widget or not _affinity_manager:
        return

    level = _affinity_manager.get_level()
    level_name = _affinity_manager.get_level_name()
    points = _affinity_manager.points
    _call_original_say(
        widget,
        _("현재 친밀도: {level_name} (Lv.{level}) — {points}pt",
          level_name=level_name, level=level, points=points),
        4000,
    )


def register(context):
    from i18n.translator import _

    global _widget_ref, _affinity_manager

    _widget_ref = getattr(context, "character_widget", None)
    _affinity_manager = AffinityManager()

    if _widget_ref:
        _widget_ref._affinity_manager = _affinity_manager
        _widget_ref._affinity_on_level_up = _notify_level_up
        if _affinity_manager.record_daily_login():
            _notify_level_up()

    if callable(getattr(context, "register_menu_action", None)):
        context.register_menu_action(_("💝 친밀도 확인"), _on_show_affinity)

    logging.info("[AffinityPlugin] 로드 완료")
    return {
        "message": "affinity_plugin loaded",
        "has_widget": _widget_ref is not None,
    }

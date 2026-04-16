"""특별 날짜 이벤트 플러그인."""
from __future__ import annotations

import logging
import secrets


PLUGIN_INFO = {
    "name": "special_date_plugin",
    "version": "1.0.0",
    "api_version": "1.0",
    "description": "특정 날짜와 사용자 생일에 맞춰 캐릭터 반응을 표시한다",
}

_RNG = secrets.SystemRandom()
_widget_ref = None


def _get_special_dates():
    from i18n.translator import _

    return {
        (1, 1): ("기쁨", [_("새해 복 많이 받으세요!"), _("올해도 잘 부탁해요~"), _("새해가 밝았어요!")]),
        (2, 14): ("수줍", [_("오늘은 발렌타인데이예요~"), _("초콜릿... 드릴게요 헤헤")]),
        (3, 14): ("기대", [_("화이트데이예요!"), _("저한테 사탕 주실 건가요?")]),
        (4, 5): ("평온", [_("오늘은 식목일이에요!"), _("나무 심어요~")]),
        (5, 5): ("기쁨", [_("어린이날이에요!"), _("저도 어린이예요 헤헤")]),
        (5, 8): ("진지", [_("어버이날이에요. 부모님께 연락해보세요 :)")]),
        (6, 6): ("진지", [_("현충일이에요. 감사한 마음 가져요.")]),
        (8, 15): ("기쁨", [_("광복절이에요! 대한민국 만세~")]),
        (10, 3): ("기쁨", [_("개천절이에요!")]),
        (10, 9): ("진지", [_("한글날이에요. 한글은 정말 멋져요!")]),
        (10, 31): ("놀람", [_("으스스~ 할로윈이에요!"), _("BOO! 깜짝이야~")]),
        (12, 24): ("기대", [_("내일은 크리스마스예요!"), _("선물 기대돼요~")]),
        (12, 25): ("기쁨", [_("메리 크리스마스!"), _("즐거운 성탄절 되세요!")]),
        (12, 31): ("기대", [_("올해 마지막 날이에요! 잘 마무리해요~")]),
    }


def _get_birthday_messages():
    from i18n.translator import _

    return [
        _("오늘 생일이세요?! 축하해요!!"),
        _("생일 축하해요~ 오늘 주인공은 당신이에요!"),
        _("생일이에요! 케이크 드세요~"),
        _("헤헤, 생일 축하드려요! 좋은 하루 되세요!"),
    ]


def _check_and_fire_event(widget) -> None:
    from datetime import date

    from PySide6.QtCore import QTimer
    from core.config_manager import ConfigManager

    settings = ConfigManager.load_settings()
    if not settings.get("special_date_events_enabled", True):
        return

    today = date.today()
    birthday_str = str(settings.get("user_birthday", ""))
    if birthday_str and len(birthday_str) == 5:
        try:
            month, day = map(int, birthday_str.split("-"))
            if today.month == month and today.day == day:
                messages = _get_birthday_messages()
                QTimer.singleShot(
                    3000,
                    lambda: (
                        widget.set_emotion("기쁨"),
                        widget.say(_RNG.choice(messages), duration=6000),
                    ),
                )
                return
        except ValueError:
            logging.debug("[SpecialDatePlugin] 잘못된 생일 형식: %s", birthday_str)

    entry = _get_special_dates().get((today.month, today.day))
    if entry is None:
        return
    emotion, messages = entry
    QTimer.singleShot(
        3000,
        lambda: (
            widget.set_emotion(emotion),
            widget.say(_RNG.choice(messages), duration=6000),
        ),
    )


def _open_birthday_dialog():
    from PySide6.QtWidgets import QInputDialog
    from core.config_manager import ConfigManager
    from i18n.translator import _

    text, ok = QInputDialog.getText(
        None,
        _("생일 등록"),
        _("생일을 입력하세요 (MM-DD 형식, 예: 03-15):"),
    )
    if not ok or not text:
        return

    raw = text.strip()
    parts = raw.split("-")
    if len(parts) == 2 and all(part.isdigit() for part in parts):
        ConfigManager.set_value("user_birthday", raw)
        widget = _widget_ref
        if widget:
            widget.say(_("생일 등록 완료! {date}", date=raw), duration=3000)


def register(context):
    from i18n.translator import _

    global _widget_ref

    _widget_ref = getattr(context, "character_widget", None)
    if _widget_ref:
        _check_and_fire_event(_widget_ref)

    if callable(getattr(context, "register_menu_action", None)):
        context.register_menu_action(_("🎂 생일 등록"), _open_birthday_dialog)

    logging.info("[SpecialDatePlugin] 로드 완료")
    return {"message": "special_date_plugin loaded", "has_widget": _widget_ref is not None}

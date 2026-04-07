"""
Ari 국제화(i18n) 번역 엔진.

사용법:
    from i18n.translator import _, ngettext, set_language, get_language

    _("설정")
    _("주의: {msg}", msg=report.text)
    ngettext("{n}개 파일", "{n}개 파일들", n, n=n)

주의: _()는 반드시 함수/메서드 내부에서만 호출할 것.
      모듈 레벨 상수에 사용하면 init() 전에 평가되어 번역 미적용.
"""
from __future__ import annotations

import builtins
import gettext
import logging
import os
import threading
from typing import Optional

_LOCALE_DIR = os.path.join(os.path.dirname(__file__), "locales")
_DOMAIN = "ari"
_DEFAULT_LANG = "ko"
_SUPPORTED = {"ko", "en", "ja"}

_current_lang: str = _DEFAULT_LANG
_translation: Optional[gettext.GNUTranslations] = None
_lock = threading.RLock()

logger = logging.getLogger(__name__)


def _load(lang: str) -> gettext.GNUTranslations:
    try:
        return gettext.translation(_DOMAIN, localedir=_LOCALE_DIR, languages=[lang])
    except FileNotFoundError:
        logger.warning("[i18n] '%s' translation not found, using fallback", lang)
        return gettext.NullTranslations()


def init(lang: Optional[str] = None) -> None:
    """앱 시작 시 한 번 호출. lang이 None이면 settings에서 읽음."""
    global _current_lang, _translation
    if lang is None:
        try:
            from core.config_manager import ConfigManager
            lang = ConfigManager.get("language", _DEFAULT_LANG)
        except Exception:
            lang = _DEFAULT_LANG

    lang = lang if lang in _SUPPORTED else _DEFAULT_LANG

    with _lock:
        _current_lang = lang
        _translation = _load(lang)
        _translation.install()
        builtins.__dict__["_"] = gettext_func
        builtins.__dict__["ngettext"] = ngettext_func

    logger.info("[i18n] Language set: %s", lang)


def set_language(lang: str) -> None:
    """런타임 언어 전환. UI 반영은 재시작 필요."""
    if lang not in _SUPPORTED:
        logger.warning("[i18n] Unsupported language: %s", lang)
        return
    global _current_lang, _translation
    with _lock:
        _current_lang = lang
        _translation = _load(lang)
        _translation.install()
        builtins.__dict__["_"] = gettext_func
        builtins.__dict__["ngettext"] = ngettext_func
    logger.info("[i18n] Language changed: %s", lang)


def get_language() -> str:
    return _current_lang


def gettext_func(message: str, **kwargs) -> str:
    with _lock:
        t = _translation or gettext.NullTranslations()
    translated = t.gettext(message)
    return translated.format(**kwargs) if kwargs else translated


def ngettext_func(singular: str, plural: str, n: int, **kwargs) -> str:
    with _lock:
        t = _translation or gettext.NullTranslations()
    translated = t.ngettext(singular, plural, n)
    return translated.format(n=n, **kwargs) if kwargs else translated


_ = gettext_func
ngettext = ngettext_func

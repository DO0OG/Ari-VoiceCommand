"""시스템 상태 알림 반응 플러그인."""
from __future__ import annotations

import logging
import secrets
import threading
import time


PLUGIN_INFO = {
    "name": "system_monitor_plugin",
    "version": "1.0.0",
    "api_version": "1.0",
    "description": "CPU/메모리/배터리 상태에 따라 캐릭터 반응을 표시한다",
}

_RNG = secrets.SystemRandom()
_widget_ref = None
_monitor_running = False
_monitor_thread = None
_last_alert_times: dict[str, float] = {}

THRESHOLDS = {
    "cpu": {"warn": 85, "critical": 95},
    "ram": {"warn": 85, "critical": 95},
    "battery_low": 20,
    "battery_critical": 10,
}

COOLDOWNS = {
    "cpu_warn": 300,
    "cpu_critical": 120,
    "ram_warn": 300,
    "ram_critical": 120,
    "battery_low": 600,
    "battery_critical": 60,
}


def _get_messages():
    from i18n.translator import _

    return {
        "cpu_warn": (
            "화남",
            [_("CPU가 힘들어하고 있어요!"), _("컴퓨터가 뜨거워요!"), _("프로그램이 너무 많아요~")],
        ),
        "cpu_critical": (
            "걱정",
            [_("CPU가 너무 바빠요! 좀 쉬게 해줘요!"), _("과부하예요, 조심해요!")],
        ),
        "ram_warn": (
            "걱정",
            [_("메모리가 꽉 찼어요..."), _("램이 부족해요!"), _("창을 좀 닫아주세요~")],
        ),
        "ram_critical": (
            "화남",
            [_("메모리가 위험해요!"), _("지금 당장 뭔가 닫아야 해요!")],
        ),
        "battery_low": (
            "걱정",
            [_("배터리가 얼마 없어요!"), _("충전기 꽂아주세요~"), _("방전되면 안 돼요!")],
        ),
        "battery_critical": (
            "화남",
            [_("충전 빨리요!!"), _("배터리가 {pct}%예요!"), _("꺼지기 전에 충전해요!")],
        ),
    }


def _maybe_react(key: str, now: float, pct: int = 0) -> None:
    last = _last_alert_times.get(key, 0.0)
    if now - last < COOLDOWNS[key]:
        return
    _last_alert_times[key] = now

    emotion, messages = _get_messages()[key]
    message = _RNG.choice(messages)
    if "{pct}" in message:
        message = message.format(pct=pct)

    widget = _widget_ref
    if widget:
        widget.set_emotion(emotion)
        widget.say(message, duration=5000)


def _check_system():
    import psutil

    now = time.time()
    cpu = psutil.cpu_percent(interval=1)
    if cpu >= THRESHOLDS["cpu"]["critical"]:
        _maybe_react("cpu_critical", now)
    elif cpu >= THRESHOLDS["cpu"]["warn"]:
        _maybe_react("cpu_warn", now)

    ram = psutil.virtual_memory().percent
    if ram >= THRESHOLDS["ram"]["critical"]:
        _maybe_react("ram_critical", now)
    elif ram >= THRESHOLDS["ram"]["warn"]:
        _maybe_react("ram_warn", now)

    battery = psutil.sensors_battery()
    if battery and not battery.power_plugged:
        pct = int(battery.percent)
        if pct <= THRESHOLDS["battery_critical"]:
            _maybe_react("battery_critical", now, pct=pct)
        elif pct <= THRESHOLDS["battery_low"]:
            _maybe_react("battery_low", now, pct=pct)


def _monitor_loop():
    while _monitor_running:
        try:
            _check_system()
        except Exception as exc:
            logging.debug("[SystemMonitorPlugin] 오류: %s", exc)
        time.sleep(30)


def _start_monitor_thread() -> None:
    global _monitor_thread, _monitor_running

    if _monitor_running:
        return
    _monitor_running = True
    _monitor_thread = threading.Thread(
        target=_monitor_loop,
        daemon=True,
        name="ari-sysmon",
    )
    _monitor_thread.start()


def _toggle_monitor():
    from core.config_manager import ConfigManager

    global _monitor_running

    current = bool(ConfigManager.get("system_monitor_enabled", True))
    updated = not current
    ConfigManager.set_value("system_monitor_enabled", updated)
    if updated:
        _start_monitor_thread()
    else:
        _monitor_running = False


def register(context):
    from core.config_manager import ConfigManager
    from i18n.translator import _

    global _widget_ref
    _widget_ref = getattr(context, "character_widget", None)

    if ConfigManager.get("system_monitor_enabled", True):
        _start_monitor_thread()

    if callable(getattr(context, "register_menu_action", None)):
        context.register_menu_action(_("💻 시스템 모니터"), _toggle_monitor)

    logging.info("[SystemMonitorPlugin] 로드 완료")
    return {"message": "system_monitor_plugin loaded", "has_widget": _widget_ref is not None}

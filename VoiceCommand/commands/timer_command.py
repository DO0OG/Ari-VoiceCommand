"""타이머 명령"""
import re
from commands.base_command import BaseCommand
from i18n.translator import _


class TimerCommand(BaseCommand):
    """타이머 명령"""
    priority = 30

    def __init__(self, timer_manager, tts_func):
        self.timer_manager = timer_manager
        self.tts_wrapper = tts_func

    def matches(self, text: str) -> bool:
        return _("타이머") in text or _("알람") in text

    def execute(self, text: str) -> None:
        if any(keyword in text for keyword in (_("취소"), _("끄기"), _("중지"))):
            name = self._extract_timer_name(text)
            self.timer_manager.cancel_timer(name=name)
        elif any(keyword in text for keyword in (_("남은"), _("얼마"), _("확인"))):
            timers = self.timer_manager.list_timers()
            if not timers:
                self.tts_wrapper(_("현재 실행 중인 타이머가 없습니다."))
            else:
                target = timers[-1]
                name = target["name"]
                remaining = target["remaining_seconds"]
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                
                # 타이머 이름 처리 (번역된 접두사 사용)
                prefix = _("타이머") if target.get("auto_named") else _("'{name}' 타이머").format(name=name)
                
                if mins > 0 and secs > 0:
                    self.tts_wrapper(_("{prefix} {mins}분 {secs}초 남았습니다.").format(prefix=prefix, mins=mins, secs=secs))
                elif mins > 0:
                    self.tts_wrapper(_("{prefix} {mins}분 남았습니다.").format(prefix=prefix, mins=mins))
                else:
                    self.tts_wrapper(_("{prefix} {secs}초 남았습니다.").format(prefix=prefix, secs=secs))
        else:
            minutes = self.timer_manager.parse_timer_command(text)
            if minutes is not None:
                self.timer_manager.set_timer(minutes, name=self._extract_timer_name(text))
            else:
                self.tts_wrapper(_("타이머 시간을 정확히 말씀해 주세요."))

    @staticmethod
    def _extract_timer_name(text: str) -> str:
        # 정규식 패턴에서 '타이머'는 한국어 매칭을 위해 유지하되, 번역 가능하도록 보강 가능
        match = re.search(r'["\']([^"\']+)["\']\s*' + _("타이머"), text)
        if match:
            return match.group(1).strip()
        named_match = re.search(r'([가-힣a-zA-Z0-9 _-]+)\s*' + _("타이머"), text)
        if not named_match:
            return ""
        candidate = named_match.group(1).strip()
        # 제외 키워드들도 번역된 값으로 체크
        exclude = (_("취소"), _("남은"), _("얼마"), _("확인"))
        return "" if any(token in candidate for token in exclude) else candidate

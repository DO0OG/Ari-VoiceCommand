"""메모리 관련 음성 명령."""
from __future__ import annotations

import html
import re

from commands.base_command import BaseCommand
from i18n.translator import _
from memory.sensitive_patterns import is_sensitive_memory_text


_REMEMBER_PATTERNS = (
    re.compile(r"\s*이거\s*기억해\s*둬(?:\s*[:：]\s*(.*)|\s+(.*)|\s*)", re.I),
    re.compile(r"\s*기억해(?:\s*줘)?(?:\s*[:：]\s*(.*)|\s+(.*)|\s*)", re.I),
    re.compile(r"\s*remember\s+this(?:\s*[:：]\s*(.*)|\s+(.*)|\s*)", re.I),
    re.compile(r"\s*remember\s+that(?:\s*[:：]\s*(.*)|\s+(.*)|\s*)", re.I),
    re.compile(r"\s*remember(?:\s*[:：]\s*(.*)|\s+(.*)|\s*)", re.I),
    re.compile(r"\s*これ(?:を)?覚えておいて(?:\s*[:：]\s*(.*)|\s+(.*)|\s*)"),
    re.compile(r"\s*覚えておいて(?:\s*[:：]\s*(.*)|\s+(.*)|\s*)"),
    re.compile(r"\s*覚えて(?:\s*[:：]\s*(.*)|\s+(.*)|\s*)"),
)
_FORGET_PREFIX_PATTERNS = (
    re.compile(r"\s*잊어(?:\s*줘)?(?:\s*[:：]\s*(.*)|\s+(.*)|\s*)", re.I),
    re.compile(r"\s*forget\s+about(?:\s*[:：]\s*(.*)|\s+(.*)|\s*)", re.I),
    re.compile(r"\s*forget(?:\s*[:：]\s*(.*)|\s+(.*)|\s*)", re.I),
    re.compile(r"\s*忘れて(?:\s*[:：]\s*(.*)|\s+(.*)|\s*)"),
)
_FORGET_SUFFIX_PATTERNS = (
    re.compile(r"\s*(.+?)\s*(?:은|는|이|가|을|를)?\s*잊어(?:\s*줘)?\s*", re.I),
    re.compile(r"\s*(.+?)\s*(?:のこと(?:を|は)?|を)?\s*忘れて\s*"),
)
_RECENT_FORGET_ALIASES = {
    "방금 거 잊어", "방금 거 잊어줘", "방금 것 잊어", "방금 기억 잊어",
    "마지막 기억 잊어줘", "forget that", "forget this", "forget it",
    "forget that memory",
    "forget the last thing", "forget the last one", "forget my last memory",
    "forget the latest memory", "forget last thing", "forget the most recent thing",
    "今のを忘れて", "さっきのを忘れて", "直前の記憶を忘れて", "最後の記憶を忘れて",
}
_EMPTY_REMEMBER_ALIASES = {
    "이거 기억해 둬", "이거 기억해둬", "기억해 둬", "기억해둬",
    "remember this", "remember that", "remember this for me",
    "これ覚えておいて", "これを覚えておいて", "覚えておいて",
}
_MEMORY_COMMAND_PHRASES = (
    "자주 하는 작업", "저번에 내가", "내 스킬 목록", "스킬 목록",
    "이 스킬 삭제", "메모리 정리", "나에 대해 뭐 알아", "나에 대해 뭘 알아",
)


def _parse_explicit_command(text: str) -> tuple[str, str] | None:
    normalized = text.strip().rstrip(" .!?。！？").casefold()
    if normalized in _EMPTY_REMEMBER_ALIASES:
        return "remember", ""

    for pattern in _REMEMBER_PATTERNS:
        match = pattern.fullmatch(text)
        if match:
            return "remember", (match.group(1) or match.group(2) or "").strip()

    if normalized in _RECENT_FORGET_ALIASES:
        return "forget_recent", ""

    for pattern in _FORGET_PREFIX_PATTERNS:
        match = pattern.fullmatch(text)
        if match:
            return "forget", (match.group(1) or match.group(2) or "").strip()

    for pattern in _FORGET_SUFFIX_PATTERNS:
        match = pattern.fullmatch(text)
        if match:
            return "forget", match.group(1).strip()
    return None


def is_memory_command(text: str) -> bool:
    """메모리 명령 턴인지 확인한다."""
    return bool(_parse_explicit_command(text)) or any(
        phrase in text for phrase in _MEMORY_COMMAND_PHRASES
    )


class MemoryCommand(BaseCommand):
    priority = 45

    def __init__(self, tts_func):
        self.tts_wrapper = tts_func

    def matches(self, text: str) -> bool:
        return is_memory_command(text)

    def execute(self, text: str) -> None:
        explicit = _parse_explicit_command(text)
        if explicit:
            action, content = explicit
            if action == "remember":
                self._remember(content)
            else:
                self._forget(content, recent=action == "forget_recent")
            return

        if "자주 하는 작업" in text:
            from memory.user_profile_engine import get_user_profile_engine
            goals = get_user_profile_engine().get_profile().frequent_goals[:3]
            msg = _("자주 하는 작업을 아직 충분히 배우지 못했어요.") if not goals else _(
                "자주 하는 작업은 {goals}예요.", goals=", ".join(goals)
            )
            self.tts_wrapper(msg)
            return

        if "저번에 내가" in text:
            from memory.memory_index import get_memory_index
            results = get_memory_index().search("기억 OR 사용자", limit=3)
            if not results:
                self.tts_wrapper(_("아직 떠올릴 만한 기록이 충분하지 않아요."))
                return
            self.tts_wrapper(_("기억나는 최근 기록은 {records}", records=" / ".join(result.content[:60] for result in results)))
            return

        if "스킬 목록" in text:
            from agent.skill_library import get_skill_library
            skills = get_skill_library().list_skills()
            if not skills:
                self.tts_wrapper(_("아직 저장된 스킬이 없어요."))
                return
            self.tts_wrapper(_("현재 스킬은 {skills}예요.", skills=", ".join(skill.name for skill in skills[:5])))
            return

        if "이 스킬 삭제" in text:
            from agent.skill_library import get_skill_library
            skills = get_skill_library().list_skills()
            if not skills:
                self.tts_wrapper(_("삭제할 스킬이 없어요."))
                return
            get_skill_library().deprecate_skill(skills[0].skill_id)
            self.tts_wrapper(_("{name} 스킬을 비활성화했어요.", name=skills[0].name))
            return

        if "메모리 정리" in text:
            from memory.memory_consolidator import get_memory_consolidator
            result = get_memory_consolidator().run_all()
            self.tts_wrapper(
                _(
                    "메모리 정리를 마쳤어요. 사실 {facts}개, 전략 {strategies}개가 현재 유지 중이에요.",
                    facts=result["facts"],
                    strategies=result["strategies"],
                )
            )
            return

        if "나에 대해 뭐 알아" in text or "나에 대해 뭘 알아" in text:
            from memory.user_profile_engine import get_user_profile_engine
            from memory.memory_manager import get_memory_manager
            profile = get_user_profile_engine().get_prompt_injection()
            facts = get_memory_manager().get_top_facts_prompt(3)
            self.tts_wrapper(f"{profile} {facts}".strip())

    def _remember(self, content: str, source: str = "user") -> None:
        if not content:
            from memory.conversation_history import get_conversation_history

            recent = get_conversation_history().get_recent(1)
            content = str(recent[-1].get("user", "")).strip() if recent else ""
            if not content:
                self.tts_wrapper(_("무엇을 기억할까요?"))
                return
        if is_sensitive_memory_text(content):
            self.tts_wrapper(_("민감 정보는 저장하지 않아요."))
            return

        key, value = content, content
        for separator in ("=", "＝"):
            if separator in content:
                candidate_key, candidate_value = content.split(separator, 1)
                if candidate_key.strip() and candidate_value.strip():
                    key, value = candidate_key.strip(), candidate_value.strip()
                break

        from memory.user_context import get_context_manager

        context = get_context_manager()
        if not context.record_fact(
            key, value, source=source, confidence=1.0, ttl_days=0, force=True
        ):
            self.tts_wrapper(_("기억을 저장하지 못했어요."))
            return
        self.tts_wrapper(_("기억했어요: {value}", value=value))

    def _forget(self, content: str, recent: bool = False) -> None:
        if not content and not recent:
            self.tts_wrapper(_("무엇을 잊을까요?"))
            return

        from memory.user_context import get_context_manager

        context = get_context_manager()
        facts = context.get_facts_snapshot()
        if recent:
            matches = list(facts.items())
            matches.sort(
                key=lambda item: str(item[1].get("updated_at", "")), reverse=True
            )
            candidates = [("fact", key, fact) for key, fact in matches[:1]]
            query = ""
        else:
            query = content.strip().rstrip(" .!?。！？,，:：;；").strip().casefold()
            if not query:
                self.tts_wrapper(_("무엇을 잊을까요?"))
                return
            preference_items = [
                (category, value, count)
                for category, values in context.get_preferences_snapshot().items()
                for value, count in values.items()
            ]
            exact = [
                ("fact", key, fact)
                for key, fact in facts.items()
                if query == str(key).casefold()
                or query == str(fact.get("value", "")).casefold()
            ]
            candidates = exact or [
                ("fact", key, fact)
                for key, fact in facts.items()
                if query in str(key).casefold()
                or query in str(fact.get("value", "")).casefold()
            ]
            if not candidates:
                candidates.extend(
                    ("preference", category, {"value": value, "count": count})
                    for category, value, count in preference_items
                    if query == str(category).casefold()
                    or query == str(value).casefold()
                )
                if not candidates:
                    candidates.extend(
                        ("preference", category, {"value": value, "count": count})
                        for category, value, count in preference_items
                        if query in str(category).casefold()
                        or query in str(value).casefold()
                    )

        if not candidates:
            self.tts_wrapper(_("잊을 기억이 없어요."))
            return
        if len(candidates) > 1:
            self.tts_wrapper(
                _(
                    "여러 기억이 있어요: {items}. 어떤 기억인지 골라 주세요.",
                    items=", ".join(
                        f"{_('선호: {key}', key=key) if kind == 'preference' else key}: "
                        f"{fact.get('value', '')}"
                        for kind, key, fact in candidates
                    ),
                )
            )
            return

        kind, key, fact = candidates[0]
        display_key = _("선호: {key}", key=key) if kind == "preference" else key
        display = html.escape(f"{display_key}: {fact.get('value', '')}")
        try:
            from agent.confirmation_manager import get_confirmation_manager
            from agent.safety_checker import DangerLevel, SafetyReport

            report = SafetyReport(
                level=DangerLevel.DANGEROUS,
                matched_patterns=[_("기억 삭제")],
                summary=_("기억, 관련 대화 기록, 맞는 선호를 삭제합니다."),
                category="memory",
            )
            confirmed = get_confirmation_manager().request_confirmation(
                _("기억·관련 대화 기록·맞는 선호 삭제: {fact}", fact=display),
                report,
                self.tts_wrapper,
            )
        except (ImportError, RuntimeError):
            confirmed = False
        if not confirmed:
            self.tts_wrapper(_("삭제를 취소했어요."))
            return
        deleted = (
            context.delete_fact(
                key,
                delete_conversations=len(str(fact.get("value", "")).strip()) > 1,
                expected_value=str(fact.get("value", "")),
            )
            if kind == "fact"
            else context.delete_preference(
                key,
                str(fact.get("value", "")),
                delete_conversations=len(str(fact.get("value", "")).strip()) > 1,
            )
        )
        if deleted and kind == "fact":
            # 한 글자 이하로는 무관한 선호까지 걸리므로 맞춰 보지 않는다.
            fact_value = str(fact.get("value", "")).strip()
            if len(fact_value) > 1:
                for category, values in context.get_preferences_snapshot().items():
                    for value in values:
                        if fact_value.casefold() in str(value).casefold():
                            context.delete_preference(
                                category, value, delete_conversations=True
                            )
        if deleted:
            self.tts_wrapper(_("기억을 잊었어요: {key}", key=key))
        else:
            self.tts_wrapper(_("기억을 삭제하지 못했어요."))


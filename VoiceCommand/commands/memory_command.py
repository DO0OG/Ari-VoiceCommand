"""메모리 관련 음성 명령."""
from __future__ import annotations

from commands.base_command import BaseCommand


class MemoryCommand(BaseCommand):
    priority = 45

    def __init__(self, tts_func):
        self.tts_wrapper = tts_func

    def matches(self, text: str) -> bool:
        patterns = (
            "자주 하는 작업", "저번에 내가", "내 스킬 목록", "스킬 목록",
            "이 스킬 삭제", "메모리 정리", "나에 대해 뭐 알아", "나에 대해 뭘 알아",
        )
        return any(pattern in text for pattern in patterns)

    def execute(self, text: str) -> None:
        if "자주 하는 작업" in text:
            from memory.user_profile_engine import get_user_profile_engine
            goals = get_user_profile_engine().get_profile().frequent_goals[:3]
            msg = "자주 하는 작업을 아직 충분히 배우지 못했어요." if not goals else f"자주 하는 작업은 {', '.join(goals)}예요."
            self.tts_wrapper(msg)
            return

        if "저번에 내가" in text:
            from memory.memory_index import get_memory_index
            results = get_memory_index().search("기억 OR 사용자", limit=3)
            if not results:
                self.tts_wrapper("아직 떠올릴 만한 기록이 충분하지 않아요.")
                return
            self.tts_wrapper("기억나는 최근 기록은 " + " / ".join(result.content[:60] for result in results))
            return

        if "스킬 목록" in text:
            from agent.skill_library import get_skill_library
            skills = get_skill_library().list_skills()
            if not skills:
                self.tts_wrapper("아직 저장된 스킬이 없어요.")
                return
            self.tts_wrapper("현재 스킬은 " + ", ".join(skill.name for skill in skills[:5]) + "예요.")
            return

        if "이 스킬 삭제" in text:
            from agent.skill_library import get_skill_library
            skills = get_skill_library().list_skills()
            if not skills:
                self.tts_wrapper("삭제할 스킬이 없어요.")
                return
            get_skill_library().deprecate_skill(skills[0].skill_id)
            self.tts_wrapper(f"{skills[0].name} 스킬을 비활성화했어요.")
            return

        if "메모리 정리" in text:
            from memory.memory_consolidator import get_memory_consolidator
            result = get_memory_consolidator().run_all()
            self.tts_wrapper(
                f"메모리 정리를 마쳤어요. 사실 {result['facts']}개, 전략 {result['strategies']}개가 현재 유지 중이에요."
            )
            return

        if "나에 대해 뭐 알아" in text or "나에 대해 뭘 알아" in text:
            from memory.user_profile_engine import get_user_profile_engine
            from memory.memory_manager import get_memory_manager
            profile = get_user_profile_engine().get_prompt_injection()
            facts = get_memory_manager().get_top_facts_prompt(3)
            self.tts_wrapper(f"{profile} {facts}".strip())


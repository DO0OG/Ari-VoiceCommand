"""Ari 일상 상호작용에 XP, 퀘스트, 업적, 미니게임을 더하는 플러그인."""
from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from commands.base_command import BaseCommand, CommandResult
from i18n.translator import _


PLUGIN_INFO = {
    "name": "ari_gamify",
    "version": "1.0.0",
    "api_version": "1.0",
    "trust_level": "verified",
    "description": "Ari에게 XP, 레벨, 업적, 퀘스트, 미니게임을 추가합니다.",
}

XP_TABLE = {
    "voice_command": 5,
    "agent_task_complete": 20,
    "daily_login": 10,
    "streak_bonus": 15,
    "minigame_win": 30,
    "achievement": 20,
}

LEVEL_THRESHOLDS = [0, 50, 150, 300, 600, 1000, 1500, 2200, 3000, 4000]
LEVEL_TITLES = [
    "입문자",
    "탐험가",
    "모험가",
    "영웅",
    "전설",
    "신화",
    "아리의 동반자",
    "아리의 친구",
    "아리의 단짝",
    "아리의 파트너",
]

ACHIEVEMENTS = {
    "first_command": "첫 명령",
    "streak_3": "3일 연속",
    "streak_7": "일주일 동반자",
    "night_owl": "야행성",
    "early_bird": "새벽형 인간",
    "agent_10": "에이전트 마스터",
    "minigame_3": "게임 입문",
}

DAILY_QUESTS = [
    {"id": "use_3_commands", "description": "명령 3회 사용", "goal": 3, "reward_xp": 30},
    {"id": "use_weather", "description": "날씨 확인하기", "goal": 1, "reward_xp": 15},
    {"id": "use_timer", "description": "타이머 사용하기", "goal": 1, "reward_xp": 15},
    {"id": "agent_task", "description": "에이전트 작업 완료", "goal": 1, "reward_xp": 40},
    {"id": "play_minigame", "description": "미니게임 1판", "goal": 1, "reward_xp": 25},
]

WEEKLY_QUESTS = [
    {"id": "agent_task_5", "description": "에이전트 작업 5회", "goal": 5, "reward_xp": 150},
    {"id": "streak_5", "description": "5일 연속 사용", "goal": 5, "reward_xp": 200},
    {"id": "all_daily_7", "description": "일일 퀘스트 7회 완료", "goal": 7, "reward_xp": 300},
]

TRIVIA = [
    ("지구는 태양계에서 세 번째 행성이다.", True, "지구는 태양으로부터 세 번째 행성이에요."),
    ("한글은 세종대왕 시대에 창제되었다.", True, "훈민정음은 세종대왕 시대에 만들어졌어요."),
    ("물은 표준 기압에서 50도에 끓는다.", False, "물은 표준 기압에서 100도에 끓어요."),
]


def _default_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "xp": 0,
        "level": 0,
        "streak_days": 0,
        "last_login_date": None,
        "total_commands": 0,
        "total_agent_tasks": 0,
        "daily_completed_count": 0,
        "achievements": [],
        "daily_quest": {},
        "weekly_quest": {},
        "minigame_stats": {
            "number_guess": {"wins": 0, "best_attempts": None},
            "word_chain": {"wins": 0, "best_streak": 0},
            "trivia": {"wins": 0, "best_score": 0},
        },
    }


def _level_for_xp(xp: int) -> int:
    level = 0
    for index, threshold in enumerate(LEVEL_THRESHOLDS):
        if xp >= threshold:
            level = index
    return level


def _week_start(today: date) -> str:
    return (today - timedelta(days=today.weekday())).isoformat()


@dataclass
class NumberGuessSession:
    answer: int
    low: int = 1
    high: int = 100
    attempts: int = 0


class GamifyEngine:
    def __init__(self, state_path: str | None = None, rng: random.Random | None = None):
        self.state_path = state_path or self._default_state_path()
        self.rng = rng or random.Random()
        self.state = self._load_state()
        self.number_guess: NumberGuessSession | None = None
        self._ensure_quests()
        self._record_login()

    def _default_state_path(self) -> str:
        try:
            from core.resource_manager import ResourceManager

            return ResourceManager.get_writable_path("gamify_state.json")
        except Exception:
            return str(Path.home() / ".ari_runtime" / "gamify_state.json")

    def _load_state(self) -> dict[str, Any]:
        if not os.path.exists(self.state_path):
            return _default_state()
        try:
            with open(self.state_path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return _default_state()
        state = _default_state()
        state.update(loaded if isinstance(loaded, dict) else {})
        return state

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as handle:
            json.dump(self.state, handle, ensure_ascii=False, indent=2)

    def add_xp(self, amount: int, reason: str = "") -> bool:
        previous_level = int(self.state.get("level", 0))
        self.state["xp"] = max(0, int(self.state.get("xp", 0)) + int(amount))
        self.state["level"] = _level_for_xp(int(self.state["xp"]))
        self.save()
        return int(self.state["level"]) > previous_level

    def title(self) -> str:
        key = LEVEL_TITLES[min(int(self.state.get("level", 0)), len(LEVEL_TITLES) - 1)]
        return _(key)

    def _choose_daily(self, today: date) -> dict[str, Any]:
        quest = dict(self.rng.choice(DAILY_QUESTS))
        return {
            "date": today.isoformat(),
            "id": quest["id"],
            "description": quest["description"],
            "progress": 0,
            "goal": quest["goal"],
            "reward_xp": quest["reward_xp"],
            "completed": False,
        }

    def _choose_weekly(self, today: date) -> dict[str, Any]:
        quest = dict(self.rng.choice(WEEKLY_QUESTS))
        return {
            "week_start": _week_start(today),
            "id": quest["id"],
            "description": quest["description"],
            "progress": 0,
            "goal": quest["goal"],
            "reward_xp": quest["reward_xp"],
            "completed": False,
        }

    def _ensure_quests(self) -> None:
        today = date.today()
        daily = self.state.get("daily_quest") or {}
        if daily.get("date") != today.isoformat():
            self.state["daily_quest"] = self._choose_daily(today)
        weekly = self.state.get("weekly_quest") or {}
        if weekly.get("week_start") != _week_start(today):
            self.state["weekly_quest"] = self._choose_weekly(today)
        self.save()

    def _record_login(self) -> None:
        today = date.today()
        last_login = self.state.get("last_login_date")
        if last_login == today.isoformat():
            return
        if last_login == (today - timedelta(days=1)).isoformat():
            self.state["streak_days"] = int(self.state.get("streak_days", 0)) + 1
        else:
            self.state["streak_days"] = 1
        self.state["last_login_date"] = today.isoformat()
        self.add_xp(XP_TABLE["daily_login"], "daily_login")
        if int(self.state["streak_days"]) % 7 == 0:
            self.add_xp(XP_TABLE["streak_bonus"], "streak_bonus")
        self._unlock_streak_achievements()
        self._progress_weekly("streak_5")
        self.save()

    def handle_command(self, payload: dict[str, Any]) -> list[str]:
        if payload.get("success") is False:
            return []
        self.state["total_commands"] = int(self.state.get("total_commands", 0)) + 1
        leveled = self.add_xp(XP_TABLE["voice_command"], "voice_command")
        unlocked = self._unlock_time_achievements() + self._unlock(["first_command"])
        command_type = str(payload.get("command_type", ""))
        self._progress_daily("use_3_commands")
        if command_type == "weather":
            self._progress_daily("use_weather")
        if command_type == "timer":
            self._progress_daily("use_timer")
        self.save()
        return (["level_up"] if leveled else []) + unlocked

    def handle_agent_completed(self, payload: dict[str, Any]) -> list[str]:
        del payload
        self.state["total_agent_tasks"] = int(self.state.get("total_agent_tasks", 0)) + 1
        leveled = self.add_xp(XP_TABLE["agent_task_complete"], "agent_task_complete")
        unlocked = self._unlock(["agent_10"] if int(self.state["total_agent_tasks"]) >= 10 else [])
        self._progress_daily("agent_task")
        self._progress_weekly("agent_task_5")
        self.save()
        return (["level_up"] if leveled else []) + unlocked

    def on_game_mode_change(self, enabled: bool) -> list[str]:
        self.state["game_mode_enabled"] = bool(enabled)
        if enabled:
            self._progress_daily("agent_task")
        self.save()
        return []

    def _unlock_time_achievements(self) -> list[str]:
        hour = datetime.now().hour
        targets = []
        if 0 <= hour < 4:
            targets.append("night_owl")
        if 5 <= hour <= 7:
            targets.append("early_bird")
        return self._unlock(targets)

    def _unlock_streak_achievements(self) -> list[str]:
        streak = int(self.state.get("streak_days", 0))
        targets = []
        if streak >= 3:
            targets.append("streak_3")
        if streak >= 7:
            targets.append("streak_7")
        return self._unlock(targets)

    def _unlock(self, achievement_ids: list[str]) -> list[str]:
        achievements = set(self.state.get("achievements", []))
        unlocked = []
        for achievement_id in achievement_ids:
            if achievement_id and achievement_id not in achievements:
                achievements.add(achievement_id)
                unlocked.append(achievement_id)
                self.add_xp(XP_TABLE["achievement"], f"achievement:{achievement_id}")
        self.state["achievements"] = sorted(achievements)
        return unlocked

    def _progress_daily(self, quest_id: str) -> bool:
        return self._progress_quest("daily_quest", quest_id)

    def _progress_weekly(self, quest_id: str) -> bool:
        return self._progress_quest("weekly_quest", quest_id)

    def _progress_quest(self, key: str, quest_id: str) -> bool:
        quest = self.state.get(key) or {}
        if quest.get("id") != quest_id or quest.get("completed"):
            return False
        quest["progress"] = min(int(quest.get("goal", 1)), int(quest.get("progress", 0)) + 1)
        completed = int(quest["progress"]) >= int(quest.get("goal", 1))
        if completed:
            quest["completed"] = True
            self.add_xp(int(quest.get("reward_xp", 0)), f"quest:{quest_id}")
            if key == "daily_quest":
                self.state["daily_completed_count"] = int(self.state.get("daily_completed_count", 0)) + 1
                self._progress_weekly("all_daily_7")
        self.state[key] = quest
        return completed

    def start_number_guess(self, difficulty: str = "normal") -> str:
        high = {"easy": 50, "normal": 100, "hard": 500}.get(difficulty, 100)
        self.number_guess = NumberGuessSession(answer=self.rng.randint(1, high), high=high)
        return _("1부터 {high} 사이 숫자를 맞춰보세요!", high=high)

    def guess_number(self, guess: int) -> tuple[bool, str]:
        if self.number_guess is None:
            return False, _("진행 중인 숫자 게임이 없어요.")
        session = self.number_guess
        session.attempts += 1
        if guess == session.answer:
            stats = self.state["minigame_stats"]["number_guess"]
            stats["wins"] = int(stats.get("wins", 0)) + 1
            best = stats.get("best_attempts")
            if best is None or session.attempts < int(best):
                stats["best_attempts"] = session.attempts
            self.number_guess = None
            self.add_xp(XP_TABLE["minigame_win"], "minigame_win")
            self._progress_daily("play_minigame")
            self._unlock_minigame_achievement()
            self.save()
            return True, _("[기쁨]정답이에요! {attempts}번 만에 맞추셨어요. +30 XP!", attempts=session.attempts)
        if guess < session.answer:
            session.low = max(session.low, guess)
            return False, _("더 높아요! [힌트: {low}~{high}]", low=session.low, high=session.high)
        session.high = min(session.high, guess)
        return False, _("더 낮아요! [힌트: {low}~{high}]", low=session.low, high=session.high)

    def answer_trivia(self, answer: str) -> str:
        question, expected, explanation = self.rng.choice(TRIVIA)
        user_answer = answer.strip().upper() in {"O", "YES", "TRUE", "맞아", "맞음"}
        if user_answer == expected:
            stats = self.state["minigame_stats"]["trivia"]
            stats["wins"] = int(stats.get("wins", 0)) + 1
            stats["best_score"] = max(int(stats.get("best_score", 0)), 1)
            self.add_xp(10, "trivia")
            self._progress_daily("play_minigame")
            self._unlock_minigame_achievement()
            self.save()
            return _("[기쁨]정답! {explanation} +10 XP", explanation=explanation)
        return _(
            "아쉬워요. 문제: {question} 정답은 {answer}예요. {explanation}",
            question=question,
            answer="O" if expected else "X",
            explanation=explanation,
        )

    def _unlock_minigame_achievement(self) -> None:
        played = sum(1 for stats in self.state["minigame_stats"].values() if int(stats.get("wins", 0)) > 0)
        if played >= 3:
            self._unlock(["minigame_3"])

    def level_summary(self) -> str:
        xp = int(self.state.get("xp", 0))
        level = int(self.state.get("level", 0))
        next_threshold = LEVEL_THRESHOLDS[min(level + 1, len(LEVEL_THRESHOLDS) - 1)]
        return _(
            "현재 레벨 {level} ({title}), {xp}XP예요. 다음 목표는 {next_threshold}XP입니다.",
            level=level,
            title=self.title(),
            xp=xp,
            next_threshold=next_threshold,
        )

    def quest_summary(self) -> str:
        daily = self.state.get("daily_quest", {})
        weekly = self.state.get("weekly_quest", {})
        daily_desc = _(daily.get("description", "없음"))
        weekly_desc = _(weekly.get("description", "없음"))
        return _(
            "오늘의 퀘스트: {daily_desc} {progress}/{goal}. 주간 퀘스트: {weekly_desc} {weekly_progress}/{weekly_goal}.",
            daily_desc=daily_desc,
            progress=daily.get("progress", 0),
            goal=daily.get("goal", 0),
            weekly_desc=weekly_desc,
            weekly_progress=weekly.get("progress", 0),
            weekly_goal=weekly.get("goal", 0),
        )

    def achievements_summary(self) -> str:
        unlocked = [_(ACHIEVEMENTS.get(item, item)) for item in self.state.get("achievements", [])]
        if unlocked:
            return _("달성 업적: {list}", list=", ".join(unlocked))
        return _("달성 업적: 아직 없어요.")


class GamifyCommand(BaseCommand):
    priority = 20

    def __init__(self, engine: GamifyEngine, say):
        self.engine = engine
        self.say = say

    def matches(self, text: str) -> bool:
        normalized = (text or "").strip()
        if self.engine.number_guess and normalized.isdigit():
            return True
        if normalized.upper() in {"O", "X"}:
            return True
        keywords = (
            "퀘스트 확인",
            "오늘 미션",
            "내 레벨",
            "레벨 확인",
            "업적 목록",
            "게임 모드 켜",
            "게임 모드 꺼",
            "숫자 게임 시작",
            "퀴즈 게임",
        )
        return any(keyword in normalized for keyword in keywords)

    def execute(self, text: str) -> CommandResult:
        normalized = (text or "").strip()
        if self.engine.number_guess and normalized.isdigit():
            _, message = self.engine.guess_number(int(normalized))
            self.say(message)
            return CommandResult(True, message)
        if "숫자 게임 시작" in normalized:
            message = self.engine.start_number_guess("hard" if "어려" in normalized else "normal")
            self.say(message)
            return CommandResult(True, message)
        if "퀴즈 게임" in normalized:
            question, _, _ = self.engine.rng.choice(TRIVIA)
            message = _("문제입니다. '{question}' O 또는 X?", question=question)
            self.say(message)
            return CommandResult(True, message)
        if normalized.upper() in {"O", "X"}:
            message = self.engine.answer_trivia(normalized)
            self.say(message)
            return CommandResult(True, message)
        if "퀘스트 확인" in normalized or "오늘 미션" in normalized:
            message = self.engine.quest_summary()
            self.say(message)
            return CommandResult(True, message)
        if "업적 목록" in normalized:
            message = self.engine.achievements_summary()
            self.say(message)
            return CommandResult(True, message)
        if "게임 모드 켜" in normalized:
            from core.VoiceCommand import enable_game_mode

            enable_game_mode()
            message = _("[흥분]게임 모드 활성화! 오늘도 열심히 해봐요~ 🎮")
            self.say(message)
            return CommandResult(True, message)
        if "게임 모드 꺼" in normalized:
            from core.VoiceCommand import disable_game_mode

            disable_game_mode()
            message = _("게임 모드를 종료합니다. 현재 총 {xp}XP예요!", xp=self.engine.state.get("xp", 0))
            self.say(message)
            return CommandResult(True, message)
        message = self.engine.level_summary()
        self.say(message)
        return CommandResult(True, message)


def _notify(context, message: str) -> None:
    widget = getattr(context, "character_widget", None)
    if widget and hasattr(widget, "say"):
        widget.say(message, duration=4000)
    tray = getattr(context, "tray_icon", None)
    if tray and hasattr(tray, "showMessage"):
        try:
            tray.showMessage("Ari", message)
        except Exception:
            pass


def register(context):
    engine = GamifyEngine()

    def say(message: str) -> None:
        _notify(context, message)

    def on_command(payload: dict[str, Any]) -> None:
        events = engine.handle_command(payload)
        for event in events:
            if event == "level_up":
                say(_("[기쁨]레벨 업! 이제 {title}예요.", title=engine.title()))
            elif event in ACHIEVEMENTS:
                say(_("[기쁨]업적 달성! '{name}'", name=_(ACHIEVEMENTS[event])))
        if context.emit_event:
            context.emit_event("gamify.xp.updated", {"xp": engine.state.get("xp", 0), "level": engine.state.get("level", 0)})

    def on_agent(payload: dict[str, Any]) -> None:
        events = engine.handle_agent_completed(payload)
        for event in events:
            if event == "level_up":
                say(_("[기쁨]레벨 업! 이제 {title}예요.", title=engine.title()))
            elif event in ACHIEVEMENTS:
                say(_("[기쁨]업적 달성! '{name}'", name=_(ACHIEVEMENTS[event])))

    def on_game_mode_change(payload: dict[str, Any]) -> None:
        enabled = bool(payload.get("enabled", False))
        if hasattr(engine, "on_game_mode_change"):
            engine.on_game_mode_change(enabled)
        if enabled:
            say(_("[흥분]게임 모드가 켜졌어요. 퀘스트 진행을 기록할게요!"))

    if context.subscribe_event:
        context.subscribe_event("command.executed", on_command)
        context.subscribe_event("on_agent_complete", on_agent)
        context.subscribe_event("on_game_mode_change", on_game_mode_change)

    if context.register_command:
        context.register_command(GamifyCommand(engine, say))

    if context.register_menu_action:
        context.register_menu_action("📊 내 레벨 확인", lambda: say(engine.level_summary()))
        context.register_menu_action("📋 오늘의 퀘스트", lambda: say(engine.quest_summary()))
        context.register_menu_action("🏆 업적 목록", lambda: say(engine.achievements_summary()))

    return {"engine": engine}

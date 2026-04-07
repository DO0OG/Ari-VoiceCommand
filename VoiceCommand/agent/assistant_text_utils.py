"""에이전트 작업 목표·도구 응답 텍스트 정리 공통 유틸리티."""

from __future__ import annotations

import re

_GENERIC_AGENT_PHRASES = (
    "복합 작업으로 판단되어 단계별 실행으로 전환할게요",
    "복합 작업을 실행할게요",
    "진행할게요",
    "처리할게요",
    "작업을 진행합니다",
)

_SPECIFIC_GOAL_MARKERS = (
    "'",
    '"',
    ".md",
    ".txt",
    ".pdf",
    "summary.md",
    "report.md",
    "바탕화면",
    "desktop",
    "폴더",
    "folder",
    "창 제목",
    "열린 창",
)


def analyze_tool_request(user_message: str) -> dict:
    text = (user_message or "").strip()
    lowered = text.lower()
    multi_step = any(token in text for token in ("그리고", "해서", "한 뒤", "다음"))
    preferred = None
    intent = "conversation"
    force_tool = False

    if any(token in text for token in ("예약해줘", "예약", "스케줄 잡아", "알람", "타이머")):
        intent = "schedule"
        force_tool = True
        if "취소" in text:
            preferred = "cancel_timer" if "타이머" in text else "cancel_scheduled_task"
        elif "목록" in text or "뭐 있어" in text or "확인" in text:
            preferred = "list_scheduled_tasks"
        else:
            preferred = "set_timer" if "타이머" in text else "schedule_task"
    elif any(token in text for token in ("검색해줘", "찾아줘", "수집해줘")):
        intent = "web"
        force_tool = True
        preferred = "web_fetch" if "http://" in lowered or "https://" in lowered else "web_search"
    elif any(token in text for token in ("기억해", "기억나", "저번에", "지난번", "메모해", "저장해 둔")):
        intent = "memory"
    elif any(
        token in text
        for token in (
            "화면 상태",
            "화면 확인",
            "실행",
            "열어",
            "만들어줘",
            "삭제",
            "이동",
            "복사",
            "저장해줘",
            "재생해줘",
            "볼륨",
            "종료해줘",
            "보고서 만들",
        )
    ):
        intent = "automation"
        force_tool = True

    if multi_step:
        intent = "automation"
        force_tool = True
        preferred = "run_agent_task"

    return {
        "intent": intent,
        "force_tool": force_tool,
        "has_action": "해줘" in text or "실행" in text,
        "preferred_tool": preferred,
    }


def is_generic_agent_explanation(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not normalized:
        return True
    return any(phrase in normalized for phrase in _GENERIC_AGENT_PHRASES)


def contains_specific_goal_markers(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in _SPECIFIC_GOAL_MARKERS)


def resolve_agent_task_goal(goal: str, explanation: str) -> str:
    normalized_goal = (goal or "").strip()
    normalized_explanation = (explanation or "").strip()
    if not normalized_goal:
        return normalized_explanation
    if not normalized_explanation or normalized_explanation == normalized_goal:
        return normalized_goal
    if is_generic_agent_explanation(normalized_explanation):
        return normalized_goal

    goal_lower = normalized_goal.lower()
    explanation_lower = normalized_explanation.lower()
    if (
        len(normalized_explanation) >= len(normalized_goal) + 12
        or (
            contains_specific_goal_markers(normalized_explanation)
            and not contains_specific_goal_markers(normalized_goal)
        )
    ):
        return normalized_explanation

    looks_like_short_label = (
        len(normalized_goal) <= 40
        and len(normalized_explanation) >= len(normalized_goal) + 20
        and goal_lower not in explanation_lower
    )
    if looks_like_short_label:
        return normalized_explanation
    if len(normalized_explanation) > len(normalized_goal) and goal_lower in explanation_lower:
        return normalized_explanation
    return normalized_goal


def clean_tool_artifact_text(
    text: str,
    *,
    remove_memory_tags: bool = False,
    discard_short_text: bool = False,
) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""

    cleaned = re.sub(r"```.*?```", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"<function[^>]*>.*?</function>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<tool_call[^>]*>.*?</tool_call>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(
        r"\b(?:tool_call|tool_calls|function_call|tool_result)\b\s*[:=]\s*\[[^\n]*\]",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b(?:tool_call|tool_calls|function_call|tool_result)\b\s*[:=]\s*\{[^\n]*\}",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b(?:tool_call|tool_calls|function_call|tool_result)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?<=\s)[\]\}\)]+(?=\s|$)", "", cleaned)
    if remove_memory_tags:
        cleaned = re.sub(r"\[(FACT|BIO|PREF|CMD):[^\]]*\]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if discard_short_text and len(cleaned) <= 1:
        return ""
    return cleaned

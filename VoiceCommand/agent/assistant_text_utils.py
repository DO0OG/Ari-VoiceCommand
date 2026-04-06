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
    force_tool = any(
        token in text
        for token in (
            "화면 상태",
            "화면 확인",
            "예약해줘",
            "스케줄 잡아",
            "검색해줘",
            "찾아줘",
            "수집해줘",
            "보고서 만들",
            "저장해줘",
            "만들어줘",
        )
    )
    multi_step = any(token in text for token in ("그리고", "해서", "한 뒤", "다음"))
    preferred = "run_agent_task" if multi_step else None
    return {
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

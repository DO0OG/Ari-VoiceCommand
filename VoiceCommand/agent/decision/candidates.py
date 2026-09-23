from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


UNKNOWN = "unknown_or_complex"

DIRECT_ALLOWLIST = frozenset(
    {
        "get_current_time",
        "adjust_volume",
        "get_running_apps",
        "take_screenshot",
    }
)

PERMANENTLY_FORBIDDEN = frozenset(
    {
        "delete_file",
        "write_file",
        "edit_file",
        "send_email",
        "execute_shell_command",
        "execute_python_code",
        "shutdown_computer",
        "api_call",
        "mcp_call",
        "run_agent_task",
        "delegate_to_subagent",
    }
)

_PARSER_BY_NAME = {
    "get_current_time": "time",
    "get_weather": "weather",
    "adjust_volume": "volume",
    "set_timer": "timer",
    "cancel_timer": "cancel_timer",
    "launch_app": "app",
    "focus_window": "window",
    "get_running_apps": "running_apps",
    "play_youtube": "youtube",
    "take_screenshot": "screenshot",
}

_EXISTING_NAMES = frozenset(
    {
        "analyze_image_file",
        "analyze_screenshot",
        "api_call",
        "cancel_scheduled_task",
        "cancel_timer",
        "close_app",
        "create_calendar_event",
        "delegate_to_subagent",
        "delete_file",
        "edit_file",
        "execute_python_code",
        "execute_shell_command",
        "focus_window",
        "generate_image",
        "get_calendar_events",
        "get_clipboard",
        "get_current_time",
        "get_running_apps",
        "get_screen_status",
        "get_weather",
        "launch_app",
        "list_directory",
        "list_scheduled_tasks",
        "move_file",
        "read_emails",
        "read_file",
        "run_agent_task",
        "schedule_task",
        "search_in_files",
        "send_email",
        "set_clipboard",
        "set_timer",
        "take_screenshot",
        "web_fetch",
        "web_search",
        "write_file",
    }
)

_REGISTERED_NAMES = _EXISTING_NAMES | {
    "adjust_volume",
    "mcp_call",
    "play_youtube",
    "shutdown_computer",
    UNKNOWN,
}


@dataclass(frozen=True)
class DecisionCandidate:
    name: str
    risk: str
    classifiable: bool
    direct_capable: bool
    parser: str | None


def _build_candidate(name: str) -> DecisionCandidate:
    if name == UNKNOWN:
        return DecisionCandidate(name, "low", True, False, None)
    if name in PERMANENTLY_FORBIDDEN:
        return DecisionCandidate(name, "high", True, False, None)
    if name in DIRECT_ALLOWLIST:
        return DecisionCandidate(
            name,
            "low",
            True,
            True,
            _PARSER_BY_NAME[name],
        )
    return DecisionCandidate(name, "medium", True, False, None)


REGISTRY: Mapping[str, DecisionCandidate] = MappingProxyType(
    {name: _build_candidate(name) for name in sorted(_REGISTERED_NAMES)}
)


def candidate_names() -> tuple[str, ...]:
    names = tuple(
        candidate.name
        for candidate in REGISTRY.values()
        if candidate.classifiable and candidate.name != UNKNOWN
    )
    return names + (UNKNOWN,)


def get_candidate(name: str) -> DecisionCandidate | None:
    if not isinstance(name, str):
        return None
    return REGISTRY.get(name)


def is_direct_allowed(name: str, mode: str) -> bool:
    candidate = get_candidate(name)
    return bool(
        isinstance(mode, str)
        and mode in {"fast", "adaptive"}
        and name in DIRECT_ALLOWLIST
        and candidate is not None
        and candidate.classifiable
        and candidate.risk == "low"
        and candidate.direct_capable
        and name not in PERMANENTLY_FORBIDDEN
    )

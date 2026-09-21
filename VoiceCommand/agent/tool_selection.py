import logging
from agent.tool_schemas import CORE_TOOL_SCHEMAS


def _get_tool_instruction() -> str:
    try:
        from i18n.translator import get_language
        lang = get_language()
    except Exception as exc:
        logging.debug("[LLMProvider] 도구 지침 언어 조회 실패, ko 기본값 사용: %s", exc)
        lang = "ko"
    if lang == "en":
        return (
            "[Tool Usage Guidelines]\n"
            "- Always respond in English.\n"
            "- Use appropriate tools for PC control requests.\n"
            "- Do not damage URLs, code, or English names in responses."
        )
    if lang == "ja":
        return (
            "[ツール使用ガイドライン]\n"
            "- 常に日本語で回答してください。\n"
            "- PC操作の要求には適切なツールを使用してください。\n"
            "- URL・コード・英語の名称は変更しないでください。"
        )
    return (
        "[도구 사용 지침]\n"
        "- 사용자의 PC 동작 요청은 적절한 도구를 우선 호출하세요.\n"
        "- 위험하거나 파괴적인 작업은 명확한 의도를 확인하세요.\n"
        "- 답변은 한국어로 하되, URL/코드/영문 명칭은 손상시키지 마세요."
    )

_CORE_TOOL_NAMES = {
    tool["function"]["name"]
    for tool in CORE_TOOL_SCHEMAS
}
_TOOL_NAMES_BY_INTENT = {
    "conversation": {
        "get_weather",
        "get_current_time",
        "web_search",
        "web_fetch",
        "list_scheduled_tasks",
        "get_calendar_events",
        "read_emails",
    },
    "memory": {
        "get_weather",
        "get_current_time",
        "web_search",
        "web_fetch",
        "list_scheduled_tasks",
    },
    "web": {
        "web_search",
        "web_fetch",
    },
    "file": {
        "read_file",
        "write_file",
        "edit_file",
        "list_directory",
        "search_in_files",
        "move_file",
        "delete_file",
    },
    "vision": {
        "analyze_screenshot",
        "analyze_image_file",
        "launch_app",
        "close_app",
        "get_running_apps",
        "focus_window",
        "take_screenshot",
        "get_clipboard",
        "set_clipboard",
    },
    "automation": {
        "launch_app",
        "close_app",
        "get_running_apps",
        "focus_window",
        "get_screen_status",
        "execute_python_code",
        "execute_shell_command",
        "run_agent_task",
        "read_file",
        "write_file",
        "edit_file",
        "list_directory",
        "search_in_files",
        "move_file",
        "delete_file",
        "analyze_screenshot",
        "analyze_image_file",
        "delegate_to_subagent",
        "api_call",
        "get_calendar_events",
        "create_calendar_event",
        "send_email",
        "read_emails",
        "generate_image",
    },
    "schedule": {
        "set_timer",
        "cancel_timer",
        "schedule_task",
        "list_scheduled_tasks",
        "cancel_scheduled_task",
    },
}


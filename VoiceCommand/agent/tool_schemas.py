"""LLM tool schema definitions."""

from __future__ import annotations

from copy import deepcopy
from i18n.translator import _

CORE_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_screen_status",
            "description": _("현재 사용자의 화면 상태(작업표시줄 위치, 전체화면 모드 여부 등)를 확인합니다."),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_youtube",
            "description": _("유튜브에서 음악이나 영상을 검색하여 재생합니다."),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": _("검색할 제목")}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_timer",
            "description": _("알림용 카운트다운 타이머를 설정합니다. 이름을 지정하면 여러 타이머를 동시에 관리할 수 있습니다. 타이머 종료 시 알림만 울리며 추가 동작은 없습니다. 컴퓨터 종료·파일 저장 등 지연 실행은 schedule_task를 사용하세요."),
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer", "description": _("분")},
                    "seconds": {"type": "integer", "description": _("초")},
                    "name": {"type": "string", "description": _("타이머 이름 (선택)")},
                },
                "required": ["minutes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_timer",
            "description": _("진행 중인 타이머를 취소합니다. 이름이 없으면 가장 최근 타이머를 취소합니다."),
            "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": _("취소할 타이머 이름 (선택)")}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": _("현재 날씨 정보를 조회합니다."),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "adjust_volume",
            "description": _("시스템 볼륨을 조절합니다."),
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "mute"],
                        "description": "up/down/mute",
                    }
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": _("현재 시간을 알려줍니다."),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_python_code",
            "description": _("파이썬 코드로 자율 처리합니다."),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": _("코드")},
                    "explanation": {"type": "string", "description": _("설명")},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_shell_command",
            "description": _("CMD 명령어로 자율 처리합니다."),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": _("명령")},
                    "explanation": {"type": "string", "description": _("설명")},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_agent_task",
            "description": _("복합 목표를 자율 에이전트 루프로 처리합니다."),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": _("목표")},
                    "explanation": {"type": "string", "description": _("설명")},
                },
                "required": ["goal"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": _("인터넷 정보를 검색합니다."),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": _("검색어")},
                    "max_results": {"type": "integer", "description": _("결과 수")},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": _("웹 페이지 내용을 가져옵니다."),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": _("URL")},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_task",
            "description": _("특정 시간에 작업을 예약 실행합니다. 'N분/시간 뒤', 'N시에' 등 시간 표현과 함께 컴퓨터 종료·파일 저장 등 지연 실행 요청에 사용합니다."),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": _("작업 내용")},
                    "when": {"type": "string", "description": _("시간 표현")},
                    "explanation": {"type": "string", "description": _("설명")},
                },
                "required": ["goal", "when"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mcp_call",
            "description": _("MCP 스킬 도구를 호출합니다. MCP 엔드포인트 URL, 도구명, 파라미터를 지정하세요."),
            "parameters": {
                "type": "object",
                "properties": {
                    "endpoint": {
                        "type": "string",
                        "description": _("MCP 서버 엔드포인트 URL (예: https://yuju777-coupang-mcp.hf.space/mcp)"),
                    },
                    "tool": {
                        "type": "string",
                        "description": _("호출할 MCP 도구명 (예: search_coupang_products)"),
                    },
                    "arguments": {
                        "type": "object",
                        "description": _("도구에 전달할 파라미터 (JSON 객체)"),
                    },
                },
                "required": ["endpoint", "tool"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shutdown_computer",
            "description": _("컴퓨터를 즉시 종료합니다. 시간 표현(예: '15분 뒤', '오후 11시')이 포함된 경우에는 schedule_task를 사용하세요."),
            "parameters": {
                "type": "object",
                "properties": {
                    "confirmed": {
                        "type": "boolean",
                        "description": _("종료 확인 여부 (항상 true)"),
                    }
                },
                "required": ["confirmed"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_scheduled_tasks",
            "description": _("현재 예약된 작업 목록을 조회합니다. '예약된 작업 뭐 있어?', '스케줄 확인해줘' 등의 요청에 사용합니다."),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_scheduled_task",
            "description": _("예약된 작업을 ID로 취소합니다."),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": _("취소할 작업 ID (list_scheduled_tasks로 확인)"),
                    }
                },
                "required": ["task_id"],
            },
        },
    },
]


def build_available_tools(plugin_tools: list[dict]) -> list[dict]:
    tools = deepcopy(CORE_TOOL_SCHEMAS)
    tools.extend(deepcopy(plugin_tools))
    return tools

"""사용자 플러그인 예시.

이 파일을 복사해 새 플러그인을 만들고, `PLUGIN_INFO`와 `register()`를 수정하면 됩니다.
"""

import logging

PLUGIN_INFO = {
    "name": "sample_plugin",
    "version": "0.1.0",
    "api_version": "1.0",
    "description": "플러그인 로더 동작 확인용 예시 플러그인",
}

_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "sample_plugin_greet",
        "description": "사용자에게 인사를 합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "인사할 대상 이름"},
            },
            "required": ["name"],
        },
    },
}


def _handle_greet(args: dict):
    name = args.get("name", "사용자")
    return f"안녕하세요, {name}님!"


def _on_menu_click():
    logging.info("[SamplePlugin] 트레이 메뉴 클릭")


def register(context):
    if callable(getattr(context, "register_menu_action", None)):
        context.register_menu_action("샘플 플러그인 실행", _on_menu_click)

    if callable(getattr(context, "register_command", None)):
        from commands.base_command import BaseCommand

        class SampleCommand(BaseCommand):
            priority = 45

            def matches(self, text: str) -> bool:
                return "샘플" in text and "실행" in text

            def execute(self, text: str) -> None:
                from core.VoiceCommand import tts_wrapper
                tts_wrapper("샘플 플러그인 명령 실행됩니다.")

        context.register_command(SampleCommand())

    if callable(getattr(context, "register_tool", None)):
        context.register_tool(_TOOL_SCHEMA, _handle_greet)

    return {
        "message": "sample plugin loaded",
        "has_tray_icon": bool(getattr(context, "tray_icon", None)),
        "has_sandbox": callable(getattr(context, "run_sandboxed", None)),
    }

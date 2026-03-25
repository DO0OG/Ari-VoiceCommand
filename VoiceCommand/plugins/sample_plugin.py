"""사용자 플러그인 예시.

이 파일을 복사해 새 플러그인을 만들고, `PLUGIN_INFO`와 `register()`를 수정하면 됩니다.
"""

PLUGIN_INFO = {
    "name": "sample_plugin",
    "version": "0.1.0",
    "description": "플러그인 로더 동작 확인용 예시 플러그인",
}


def register(context):
    return {
        "message": "sample plugin loaded",
        "has_tray_icon": bool(getattr(context, "tray_icon", None)),
    }

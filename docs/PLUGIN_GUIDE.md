# 플러그인 가이드

이 문서는 Ari에서 사용자가 직접 플러그인을 만들 때 참고하는 기준으로, 런타임 확장 지점을 중심으로 플러그인 작성 방법을 정리합니다.

## 0. Agent Skills와의 차이

2026-04 기준 Ari에는 플러그인과 별도로 **Agent Skills (`SKILL.md`)** 시스템이 추가되었습니다.

| 구분 | 플러그인 | Agent Skills |
|------|----------|--------------|
| 배포 형식 | `.py`, `.zip` | `SKILL.md`, `scripts/`, 선택적 MCP 엔드포인트 |
| 실행 방식 | 앱 런타임에 직접 로드 | LLM 프롬프트 주입 + 내장 도구 호출 |
| 주 용도 | UI/명령/도구 훅 확장 | 작업 지식 재사용, MCP 스킬 연결 |
| 관리 위치 | `plugins/` | `skills/` |

새 기능이 **실제 Python 훅/메뉴/명령 등록**이면 플러그인을,
**LLM이 읽을 스킬 지침 + 선택적 MCP/스크립트 연동**이면 Agent Skills를 사용하는 것이 적절합니다.

## 1. 플러그인 위치

실행 방식에 따라 플러그인을 두는 위치가 달라집니다.

빌드된 EXE를 실행하면 사용자 플러그인 폴더가 아래 경로에 준비됩니다.

```text
빌드된 exe 기준 플러그인 경로:
%AppData%\Ari\plugins

소스 실행(`py Main.py`) 기준 플러그인 경로:
VoiceCommand\.ari_runtime\plugins
```

개발 환경에서는 기본 템플릿이 아래 경로에 있습니다.

```text
VoiceCommand/plugins
```

또한 저장소에 포함된 기본 플러그인은 소스 실행 시 `VoiceCommand/.ari_runtime/plugins`로 복사되며,
`build_exe.py`로 exe를 만들 때도 `plugins/` 디렉터리 전체가 번들에 포함됩니다.
즉, 코어에 함께 배포할 플러그인은 `VoiceCommand/plugins/`를 기준으로 관리하는 것이 가장 안전합니다.

## 2. 플러그인으로 할 수 있는 일

플러그인은 아래와 같은 런타임 훅을 통해 메뉴, 명령, 도구, UI 동작을 확장할 수 있습니다.

| 훅 | 설명 |
|----|------|
| `context.register_menu_action(label, callback)` | 트레이·캐릭터 우클릭 메뉴에 항목 추가 (공유 QMenu) |
| `context.register_command(BaseCommand 인스턴스)` | 음성 명령 동적 등록 |
| `context.register_tool(schema, handler)` | LLM tool calling 스키마·핸들러 확장 |
| `context.register_character_pack(name, directory, activate=False)` | 플러그인 ZIP/폴더 안의 캐릭터 이미지 세트 등록 |
| `context.run_sandboxed(code, timeout=15)` | 서브프로세스 격리 실행 |
| `context.set_character_menu_enabled(bool)` | 캐릭터 우클릭 메뉴 표시 여부 제어 (플러그인 언로드 시 자동 복원) |
| `context.app` | Qt 애플리케이션 인스턴스 참조 |
| `context.tray_icon` | 트레이 아이콘 객체 참조 |
| `context.character_widget` | 캐릭터 위젯 참조 |
| `context.text_interface` | 텍스트 채팅 UI 참조 |

Agent Skills는 위 훅을 직접 제공하지 않습니다.
메뉴 등록, 런타임 코드 확장, 명령 클래스 주입이 필요하다면 플러그인을 사용해야 합니다.

현재 코어에 포함된 예시로는 친밀도, 포커스 앱 반응, 시스템 모니터, 특별 날짜, 말풍선 히스토리처럼
캐릭터 위젯과 트레이 메뉴를 연결하는 기능들이 플러그인으로 분리되어 있습니다.

## 3. 로드 방식

플러그인은 앱 시작 시 자동으로 로드되며, 개발 중에는 핫 리로드도 지원합니다.

- 플러그인은 앱 시작 시 자동 로드됩니다.
- `plugins/` 폴더를 실시간 감시하여 파일 추가·수정·삭제 시 앱 재시작 없이 자동으로 로드·리로드·언로드됩니다 (핫 리로드).
- 로드 실패 시 앱 전체가 종료되지는 않고, 해당 플러그인만 실패로 기록됩니다.
- 설정창 `확장` 탭에서 플러그인 목록, api_version, 로드 상태, 오류 메시지를 확인할 수 있습니다.
- `_`로 시작하는 파일은 로드되지 않습니다.
- 플러그인 로더는 단일 `.py` 파일과 마켓플레이스용 `.zip` 패키지를 모두 지원합니다.

## 4. 시작 방법

1. `sample_plugin.py`를 복사합니다.
2. 파일 이름을 원하는 이름으로 바꿉니다.
3. `PLUGIN_INFO`의 이름, 버전, 설명을 수정합니다. **`api_version`은 `"1.0"`으로 유지합니다.**
4. `register(context)` 함수 안에서 필요한 초기화 코드를 작성합니다.
5. 빌드된 exe 실행 시에는 `%AppData%\Ari\plugins`, 소스 실행 시에는 `VoiceCommand\.ari_runtime\plugins`에 파일을 두면 앱이 자동으로 감지하여 로드합니다.
6. 마켓플레이스 패키지라면 `.zip` 파일을 그대로 같은 폴더에 두어도 됩니다.

## 5. 최소 구조

```python
PLUGIN_INFO = {
    "name": "my_plugin",
    "version": "0.1.0",
    "api_version": "1.0",          # 필수 — 이 값으로 호환성 검사
    "description": "내 플러그인 설명",
}


def register(context):
    return {
        "message": "plugin loaded",
    }
```

`api_version`이 현재 Ari가 지원하는 버전과 일치하지 않으면 로드가 거부됩니다. 현재 지원 버전은 `"1.0"`입니다.

## 5-1. 마켓플레이스 업로드 ZIP 규칙

마켓플레이스 업로드용 ZIP은 `main.py`가 고정이 아닙니다.

- ZIP 루트에 `plugin.json` 이 있어야 합니다.
- `plugin.json` 의 `entry` 값은 ZIP 루트의 Python 파일을 가리켜야 합니다.
- 예: `entry: "sit_toggle.py"` 또는 `entry: "main.py"`
- 업로드 검증은 `plugin.json + entry 파일 존재 여부`를 기준으로 동작합니다.

예시:

```text
my_plugin.zip
├── plugin.json
└── sit_toggle.py
```

## 6. 훅 사용법

### 6-1. 트레이 메뉴 항목 추가

```python
def _on_click():
    import logging
    logging.info("[MyPlugin] 메뉴 클릭")


def register(context):
    if callable(getattr(context, "register_menu_action", None)):
        context.register_menu_action("내 플러그인 실행", _on_click)
```

- 항목은 트레이 메뉴의 "설정" 바로 위에 삽입됩니다.
- `register()`는 Qt 메인 스레드에서 호출되므로 안전합니다.

### 6-2. 음성 명령 등록

```python
from commands.base_command import BaseCommand


class MyCommand(BaseCommand):
    priority = 45  # 낮을수록 먼저 매칭 (AICommand=100, SystemCommand=10)

    def matches(self, text: str) -> bool:
        return "내명령" in text

    def execute(self, text: str) -> None:
        from core.VoiceCommand import tts_wrapper
        tts_wrapper("내 플러그인 명령이 실행됩니다.")


def register(context):
    if callable(getattr(context, "register_command", None)):
        context.register_command(MyCommand())
```

- `priority` 정렬은 등록 시 자동으로 유지됩니다.
- 기존 내장 명령과 `matches()` 패턴이 겹치지 않도록 주의하세요.

### 6-3. LLM 도구(tool) 등록

LLM이 tool calling을 통해 플러그인 기능을 직접 호출할 수 있게 합니다.

```python
_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "my_plugin_greet",          # 전역 고유 이름 (충돌 시 등록 거부)
        "description": "사용자에게 인사합니다.",
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
    return f"안녕하세요, {name}님!"  # 반환 str은 TTS로 읽힙니다


def register(context):
    if callable(getattr(context, "register_tool", None)):
        context.register_tool(_TOOL_SCHEMA, _handle_greet)
```

- 핸들러 시그니처: `(args: dict) -> Optional[str]`
- `str`을 반환하면 TTS로 읽어줍니다. `None`을 반환하면 무시합니다.
- 내장 도구 이름(예: `play_youtube`, `set_timer` 등)과 충돌하면 등록이 거부됩니다.

### 6-4. 샌드박스 실행

무거운 연산이나 외부 의존성이 있는 코드를 메인 프로세스와 격리해 실행합니다.

```python
def register(context):
    if callable(getattr(context, "run_sandboxed", None)):
        result = context.run_sandboxed(
            "import math; print(math.factorial(20))",
            timeout=5,
        )
        if result["ok"]:
            print("결과:", result["output"].strip())
        else:
            print("오류:", result["error"])
```

반환값:

| 키 | 타입 | 설명 |
|----|------|------|
| `ok` | bool | 정상 완료 여부 |
| `output` | str | stdout 출력 (최대 4096자) |
| `error` | str | 오류 메시지 또는 traceback |

- 기본 타임아웃은 15초입니다.
- 타임아웃 초과 시 `ok=False`, `error="타임아웃 (N초) 초과"` 반환.
- 완전한 OS-레벨 격리가 아니므로 신뢰할 수 없는 코드 실행에는 적합하지 않습니다.
- 내부적으로 `multiprocessing` 기반 프로세스/IPC를 사용하므로, 일부 제한된 테스트 샌드박스·원격 실행 환경에서는 `Queue()` / `Pipe()` 권한 오류가 날 수 있습니다.
- 이런 환경에서는 앱 코드가 아니라 실행 컨테이너/권한 제약이 원인일 수 있으니, 실제 로컬 Windows 런타임에서 한 번 더 확인하는 것을 권장합니다.

### 6-5. 캐릭터 이미지 세트 등록

플러그인에서 캐릭터 위젯용 이미지 세트를 등록할 수 있습니다. 사용자는 플러그인 ZIP 안에 이미지 폴더를 같이 넣기만 하면 됩니다.

```text
my_character_pack.zip
├── plugin.json
├── my_character_pack.py
└── character_pack/
   ├── idle1.png
   ├── idle2.png
   ├── walk1.png
   ├── ...
```

```python
import os


def register(context):
    pack_dir = os.path.join(os.path.dirname(__file__), "character_pack")
    if callable(getattr(context, "register_character_pack", None)):
        context.register_character_pack("my_character_pack", pack_dir, activate=True)
    return {}
```

- 이미지 파일명 규칙은 기본 `images/` 폴더와 동일합니다.
- `activate=True`면 등록 직후 해당 세트가 활성화됩니다.
- 플러그인 언로드 시 등록한 이미지 세트는 자동 제거되고 기본 세트로 복원됩니다.

## 7. `register()` 반환값

`register()`는 선택적으로 `dict`를 반환할 수 있습니다. 이 값은 `exports`로 저장되며 로드 상태 확인과 디버깅에 사용됩니다.

```python
def register(context):
    ...
    return {
        "message": "my plugin loaded",
        "has_tray_icon": bool(getattr(context, "tray_icon", None)),
        "has_sandbox": callable(getattr(context, "run_sandboxed", None)),
    }
```

## 8. 전체 예시 (sample_plugin.py)

```python
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
    # 트레이 메뉴 등록
    if callable(getattr(context, "register_menu_action", None)):
        context.register_menu_action("샘플 플러그인 실행", _on_menu_click)

    # 음성 명령 등록
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

    # LLM 도구 등록
    if callable(getattr(context, "register_tool", None)):
        context.register_tool(_TOOL_SCHEMA, _handle_greet)

    return {
        "message": "sample plugin loaded",
        "has_tray_icon": bool(getattr(context, "tray_icon", None)),
        "has_sandbox": callable(getattr(context, "run_sandboxed", None)),
    }
```

## 9. 추천 패턴

### 9-1. 훅 존재 여부를 항상 확인하기

훅은 환경에 따라 `None`일 수 있습니다. `callable(getattr(..., None))` 패턴을 사용하세요.

```python
if callable(getattr(context, "register_command", None)):
    context.register_command(MyCommand())
```

### 9-2. 가벼운 초기화만 수행하기

`register()`는 앱 시작 시 메인 스레드에서 실행됩니다. 무거운 작업은 별도 스레드나 `run_sandboxed()`를 활용하세요.

### 9-3. 실패해도 앱을 망가뜨리지 않게 만들기

플러그인 내부에서도 예외 처리를 하는 편이 좋습니다. 로드 실패는 앱 전체가 아닌 해당 플러그인만 영향을 받습니다.

## 10. 현재 한계

- **마켓플레이스**: 웹 또는 앱 내 마켓플레이스에서 ZIP 패키지 기준으로 설치할 수 있습니다.
- **샌드박스 격리 수준**: 별도 Python 프로세스 기반 타임아웃·예외 격리이며, OS-레벨 보안 격리는 아닙니다.

## 11. 주의사항

- 파일명은 곧 기본 플러그인 이름이 되므로 알아보기 쉽게 작성하세요.
- LLM 도구 이름은 전역 고유해야 합니다. `myplugin_` 접두사 사용을 권장합니다.
- 플러그인 파일 하나에 여러 역할을 몰아넣기보다, 기능별로 나누는 편이 유지보수에 좋습니다.
- 코어 파일을 직접 수정해야 하는 구조라면 플러그인보다는 본체 기능으로 넣는 편이 낫습니다.

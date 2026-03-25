# 플러그인 가이드

이 문서는 Ari에서 사용자가 직접 플러그인을 만들 때 참고하는 기준입니다.

## 1. 플러그인 위치

빌드된 EXE를 실행하면 사용자 플러그인 폴더가 아래 경로에 준비됩니다.

```text
%AppData%\Ari\plugins
```

개발 환경에서는 기본 템플릿이 아래 경로에 있습니다.

```text
VoiceCommand/plugins
```

## 2. 플러그인으로 할 수 있는 일

현재 플러그인은 "앱 로드 시점에 Python 코드를 실행하고, Ari의 주요 UI 객체에 접근해 확장 기능을 붙이는 방식"입니다.

예를 들어 아래 같은 확장이 가능합니다.

- 텍스트 UI가 열릴 때 추가 패널이나 상태 표시를 붙이기
- 시스템 트레이 메뉴와 연동되는 보조 동작 추가
- 캐릭터 위젯 상태를 읽어 별도 반응 로직 붙이기
- 앱 시작 시 사용자 환경 점검, 로그 기록, 외부 설정 로드
- 내부 도구나 외부 스크립트와 연결되는 작은 사용자 확장 작성

현재 구조에서 적합한 용도는 아래 쪽입니다.

- UI 보조 기능
- 사용자별 개인화 로직
- 시작 시 초기화 훅
- 로컬 파일 기반 확장

반대로 아래는 플러그인에서 직접 크게 벌리기보다 코어 기능으로 넣는 편이 낫습니다.

- 음성 인식 핵심 파이프라인 전체 교체
- TTS 엔진 내부 구현 수정
- 에이전트 플래너/실행기 핵심 아키텍처 변경
- 장시간 블로킹 작업을 앱 시작 시 바로 수행하는 구조

## 3. 로드 방식

- 플러그인은 앱 시작 시 자동 로드됩니다.
- 설정창의 `확장` 탭을 다시 적용하면 플러그인도 재로드됩니다.
- 로드 실패 시 앱 전체가 종료되지는 않고, 해당 플러그인만 실패로 기록됩니다.
- 설정창 `확장` 탭에서 플러그인 폴더 경로와 현재 감지된 플러그인 목록을 확인할 수 있습니다.

## 4. 시작 방법

1. `sample_plugin.py`를 복사합니다.
2. 파일 이름을 원하는 이름으로 바꿉니다.
3. `PLUGIN_INFO`의 이름, 버전, 설명을 수정합니다.
4. `register(context)` 함수 안에서 필요한 초기화 코드를 작성합니다.
5. 파일을 `%AppData%\Ari\plugins`에 두고 앱을 다시 열거나 설정창에서 다시 적용합니다.

## 5. 최소 구조

```python
PLUGIN_INFO = {
    "name": "my_plugin",
    "version": "0.1.0",
    "description": "내 플러그인 설명",
}


def register(context):
    return {
        "message": "plugin loaded",
    }
```

## 6. `register(context)`에서 받는 값

`context`는 Ari가 현재 실행 중인 주요 객체를 담고 있습니다.

### `context.app`

- 현재 Qt 애플리케이션 인스턴스
- 전역 이벤트 처리나 앱 단위 상태 조회에 활용 가능

### `context.tray_icon`

- 시스템 트레이 아이콘 객체
- 현재 메뉴 상태 확인이나 트레이 기반 확장에 활용 가능

### `context.character_widget`

- 캐릭터 위젯 객체
- 캐릭터 표시 상태 확인, 말풍선/캐릭터 반응 연동에 활용 가능

### `context.text_interface`

- 텍스트 채팅 UI 객체
- 텍스트 UI 상태 확인, 보조 패널/기능 연동에 활용 가능

플러그인은 이 객체들을 읽거나, 안전한 범위에서 연결만 하는 식으로 쓰는 편이 좋습니다.

## 7. `register()` 반환값

`register()`는 선택적으로 `dict`를 반환할 수 있습니다.

이 값은 플러그인 로더 내부에서 `exports`로 저장됩니다. 현재는 주로 상태 확인과 디버깅 용도이며, 아래처럼 간단한 메타데이터를 반환하는 방식이 적합합니다.

```python
def register(context):
    return {
        "message": "my plugin loaded",
        "has_text_interface": bool(getattr(context, "text_interface", None)),
    }
```

## 8. 추천 패턴

### 8-1. UI 존재 여부를 먼저 확인하기

```python
def register(context):
    if context.text_interface is None:
        return {"message": "text interface not ready"}
    return {"message": "text interface ready"}
```

### 8-2. 가벼운 초기화만 수행하기

- 파일 읽기
- 설정값 체크
- UI 연결
- 작은 상태 표시

앱 시작 시 오래 걸리는 네트워크 호출이나 무거운 연산은 피하는 편이 안전합니다.

### 8-3. 실패해도 앱 전체를 망가뜨리지 않게 만들기

- 예외 처리를 플러그인 안에서도 하는 편이 좋습니다.
- 파일 경로, UI 객체 존재 여부, 외부 프로그램 의존성을 먼저 확인하세요.

## 9. 샘플 확장 아이디어

### 예시 1. 텍스트 UI 존재 여부 기록

```python
PLUGIN_INFO = {
    "name": "ui_probe",
    "version": "0.1.0",
    "description": "텍스트 UI 연결 여부를 기록하는 예시",
}


def register(context):
    return {
        "text_interface_ready": bool(getattr(context, "text_interface", None)),
    }
```

### 예시 2. 캐릭터 위젯 사용 가능 여부 확인

```python
PLUGIN_INFO = {
    "name": "character_probe",
    "version": "0.1.0",
    "description": "캐릭터 위젯 연결 여부 확인",
}


def register(context):
    widget = getattr(context, "character_widget", None)
    return {
        "character_visible": bool(widget and widget.isVisible()),
    }
```

## 10. 현재 한계

현재 플러그인 시스템은 "사용자 Python 확장 로더"에 가깝습니다.

아직 기본 제공되지 않는 것은 아래와 같습니다.

- 전용 플러그인 API 버전 협상
- 메뉴 액션 자동 등록 규약
- 음성 명령/도구 자동 등록 규약
- 샌드박스 실행
- 마켓플레이스 형태의 배포/설치 시스템

즉, 지금은 자유도가 높은 대신, 플러그인 작성자가 Python 코드를 직접 관리해야 합니다.

## 11. 주의사항

- `_`로 시작하는 파일과 비 `.py` 파일은 로드되지 않습니다.
- 파일명은 곧 기본 플러그인 이름이 되므로 알아보기 쉽게 작성하세요.
- 플러그인 파일 하나에 여러 역할을 몰아넣기보다, 기능별로 나누는 편이 유지보수에 좋습니다.
- 앱 시작 시점에 너무 무거운 작업을 하면 시작 체감이 나빠질 수 있습니다.
- 코어 파일을 직접 수정해야 하는 구조라면 플러그인보다는 본체 기능으로 넣는 편이 낫습니다.

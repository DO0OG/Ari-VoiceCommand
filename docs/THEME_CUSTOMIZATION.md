# 테마 커스터마이징 가이드

이 문서는 Ari의 UI 테마를 바꾸는 방법을 설명합니다.
현재 테마 변경은 설정창, 텍스트 채팅 UI, 스킬 관리 창까지 함께 반영됩니다.

> 2026-04 기준 테마 변경은 설정창, 텍스트 채팅 UI뿐 아니라 새로 추가된 **스킬 관리 창(SkillsDialog)** 에도 함께 반영됩니다.

## 방법 1: 설정창 팔레트 에디터 (권장)

가장 간단한 방법은 설정창의 팔레트 에디터를 사용하는 것입니다.

설정창 → **장치/UI** 탭 → **🎨 팔레트 직접 편집** 버튼을 클릭하면 별도 창이 열립니다.

- 색상 스워치 옆 텍스트 입력란에 `#RRGGBB` 값을 직접 입력하거나 **선택** 버튼으로 색상 피커를 사용합니다.
- 변경 내용이 설정창 미리보기에 실시간으로 반영됩니다.
- **테마로 저장** 버튼으로 커스텀 테마 파일을 생성합니다. 이후 프리셋 목록에서 선택할 수 있습니다.
- **프리셋 초기화** 버튼으로 현재 선택된 프리셋 색상으로 되돌립니다.
- 하단 **JSON 직접 편집** 패널에서 전체 팔레트를 JSON 텍스트로 일괄 편집할 수도 있습니다.

## 방법 2: JSON 파일 직접 편집

세부 색상 값을 직접 관리하려면 JSON 파일을 편집할 수 있습니다.

### 테마 파일 위치

빌드된 EXE를 한 번 실행하면 기본 테마 JSON이 아래 위치에 준비됩니다.

```text
빌드된 exe 기준 테마 경로:
%AppData%\Ari\theme

소스 실행(`py Main.py`) 기준 테마 경로:
VoiceCommand\.ari_runtime\theme
```

개발 환경에서는 기본 파일이 아래 폴더에 있습니다.

```text
VoiceCommand/theme
```

### 수정 방법

1. 빌드된 exe 실행이면 `%AppData%\Ari\theme`, 소스 실행이면 `VoiceCommand\.ari_runtime\theme` 폴더를 엽니다.
2. `default.json`을 복사해서 새 이름(예: `my_theme.json`)으로 저장합니다.
3. JSON 파일을 텍스트 편집기로 열어 수정합니다.
4. 설정창에서 해당 테마를 선택하면 UI가 즉시 갱신되며, 스킬 관리 창을 포함한 열린 패널에도 반영됩니다.

### JSON 색상 키 목록

```json
{
  "name": "My Theme",
  "font_family": "DNFBitBitv2",
  "font_scale": 1.0,
  "colors": {
    "primary":        "#4a90e2",
    "primary_dark":   "#357abd",
    "accent":         "#ff7b54",
    "success":        "#27ae60",
    "warning":        "#f39c12",
    "danger":         "#e74c3c",
    "muted":          "#95a5a6",
    "text_primary":   "#ecf0f1",
    "text_secondary": "#bdc3c7",
    "text_panel":     "#a0a0a0",
    "bg_main":        "#1a1a2e",
    "bg_panel":       "#16213e",
    "bg_white":       "#0f3460",
    "bg_input":       "#1e2a45",
    "bg_chat_user":   "#2c3e50",
    "bg_chat_aari":   "#1a252f",
    "border_light":   "#2c3e50",
    "border_div":     "#34495e",
    "border_input":   "#3d5166",
    "border_card":    "#2c3e50",
    "titlebar":       "#0d1117",
    "bg_suggestion":  "#1e2a45",
    "bg_chip_primary":"#2c3e50",
    "bg_chip_warn":   "#3d2c1e"
  }
}
```

## 주의사항

- JSON 문법이 깨지면 해당 테마는 로드되지 않고 기본 테마가 적용됩니다.
- 색상은 `#RRGGBB` 형식을 사용하세요. `rgba()` 형식은 일부 위젯에서 적용되지 않을 수 있습니다.
- 테마 변경은 UI에만 영향이 있고, TTS 워커나 음성 엔진은 재시작되지 않습니다.
- 실시간 반영이 안 보이면 설정창에서 테마를 다시 선택해 즉시 갱신할 수 있습니다.

# 테마 커스터마이징 가이드

Ari의 UI 테마를 바꾸는 방법을 정리한 문서입니다.
테마를 바꾸면 설정창, 텍스트 채팅 UI, 그리고 2026-04에 추가된 **스킬 관리 창(SkillsDialog)** 까지 함께 바뀝니다.

## 방법 1: 설정창 팔레트 에디터 (권장)

가장 간단한 방법은 설정창의 팔레트 에디터를 쓰는 것입니다.

설정창 → **장치/UI** 탭 → **🎨 팔레트 직접 편집** 버튼을 누르면 별도 창이 열립니다.

- 색상 스워치 옆 입력란에 `#RRGGBB` 값을 직접 넣거나, **선택** 버튼으로 색상 피커를 띄웁니다.
- 바꾼 내용은 설정창 미리보기에 바로 반영됩니다.
- **테마로 저장** 버튼을 누르면 커스텀 테마 파일이 만들어지고, 이후 프리셋 목록에서 고를 수 있습니다.
- **프리셋 초기화** 버튼은 지금 선택된 프리셋 색상으로 되돌립니다.
- 아래쪽 **JSON 직접 편집** 패널에서 팔레트 전체를 JSON 텍스트로 한 번에 손볼 수도 있습니다.

## 방법 2: JSON 파일 직접 편집

색상 값을 세세하게 관리하고 싶다면 JSON 파일을 직접 편집하면 됩니다.

### 폰트 출처

- 예시 테마에서 쓰는 `DNFBitBitv2` 폰트의 공식 출처:
  <https://df.nexon.com/data/font/dnfbitbitv2>
- 테마를 배포하거나 공유할 때는 이 폰트의 이용 조건도 같이 확인해 주세요.

### 테마 파일 위치

빌드된 EXE를 한 번 실행하면 기본 테마 JSON이 아래 위치에 만들어집니다.

```text
빌드된 exe 기준 테마 경로:
%AppData%\Ari\theme

소스 실행(`VoiceCommand\.venv\Scripts\python.exe VoiceCommand\Main.py`) 기준 테마 경로:
VoiceCommand\.ari_runtime\theme
```

개발 환경에서는 기본 파일이 아래 폴더에 있습니다.

```text
VoiceCommand/theme
```

### 수정 방법

1. 빌드된 exe라면 `%AppData%\Ari\theme`, 소스 실행이라면 `VoiceCommand\.ari_runtime\theme` 폴더를 엽니다.
2. `default.json`을 복사해 새 이름(예: `my_theme.json`)으로 저장합니다.
3. JSON 파일을 텍스트 편집기로 열어 고칩니다.
4. 설정창에서 그 테마를 고르면 UI가 바로 바뀌고, 스킬 관리 창처럼 이미 열려 있는 패널에도 반영됩니다.

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

- JSON 문법이 깨지면 그 테마는 로드되지 않고 기본 테마가 적용됩니다.
- 색상은 `#RRGGBB` 형식으로 쓰세요. `rgba()` 형식은 일부 위젯에서 먹지 않을 수 있습니다.
- 테마 변경은 UI에만 영향을 주며, TTS 워커나 음성 엔진은 재시작되지 않습니다.
- 바뀐 색이 바로 보이지 않으면 설정창에서 테마를 다시 선택해 보세요.

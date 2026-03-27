# 프로그램 사용 가이드

## 1. 실행

```bash
py -3.11 -m pip install -r VoiceCommand/requirements.txt
cd VoiceCommand
py -3.11 Main.py
```

권장 검증:

```bash
py -3.11 validate_repo.py
```

### 선택 의존성 설치

기본 의존성만 설치해도 앱이 실행되지만, 아래 기능은 추가 패키지가 필요합니다.

```bash
# OCR 기반 화면 텍스트 검증 (비전 검증 기능)
pip install "easyocr>=1.7.0"          # 권장, 한국어 지원
# pip install "pytesseract>=0.3.10"   # 경량 대안 (Tesseract 별도 설치 필요)

# 의미 기반 전략 기억 검색
pip install sentence-transformers torch

# Edge TTS (무료 클라우드 TTS)
pip install edge-tts

# ElevenLabs TTS
pip install elevenlabs
```

> **주의**: easyocr는 NumPy를 업그레이드할 수 있습니다. `numpy<2` 제약이 `requirements.txt`에 명시되어 있으므로 설치 순서와 관계없이 `numpy 1.x`가 유지됩니다.

## 2. 기본 사용 흐름

1. 앱을 실행합니다.
2. 트레이 아이콘 우클릭으로 설정창을 엽니다.
3. AI 모델, TTS, UI 테마를 원하는 값으로 조정합니다.
4. 웨이크워드(`아리야`) 또는 트레이 메뉴 → `💬 텍스트 대화`로 명령합니다.

## 3. 텍스트 채팅 UI

- 음성 없이도 대화와 작업 실행이 가능합니다.
- 상단 `기억 상태` 패널에서 최근 주제, 추천 명령, 선호 요약을 확인할 수 있습니다.
- 스마트 어시스턴트 모드에서는 대화형 요청도 도구 실행으로 이어질 수 있습니다.

## 4. 시스템 제어 명령

### 종료 / 재시작 / 취소

| 예시 | 동작 |
|------|------|
| `컴퓨터 꺼줘` | 10초 후 종료 |
| `5분 뒤에 컴퓨터 꺼줘` | `shutdown /s /t 300` 예약 |
| `1시간 30분 뒤에 꺼줘` | `shutdown /s /t 5400` 예약 (복합 표현 지원) |
| `오후 11시에 컴퓨터 꺼줘` | 현재 시각 기준 남은 초 계산해 예약 |
| `컴퓨터 재시작해줘` / `재부팅해줘` | `shutdown /r /t 10` 실행 |
| `종료 취소해줘` | `shutdown /a` 실행, 예약 없으면 안내 |

### 타이머 / 알람

| 예시 | 동작 |
|------|------|
| `10분 타이머` / `10분 알람 맞춰줘` | 10분 타이머 설정 |
| `1분 30초 타이머` | 90초 타이머 설정 (복합 표현 지원) |
| `타이머 취소` | 진행 중인 타이머 취소 |
| `타이머 얼마 남았어?` | 잔여 시간 TTS 응답 |

## 5. 시간 예약 예시

- `5분 뒤에 알림 줘`
- `11시에 메모장 열어줘`
- `11시 30분에 보고서 정리해줘`
- `매일 오전 9시에 날씨 알려줘`
- `예약된 작업 뭐 있어?` — 스케줄 목록 조회
- `예약 취소해줘` — 작업 ID로 취소

## 6. 자주 쓰는 자동화 예시

- `바탕화면에 sample 폴더 만들어줘`
- `크롬으로 https://example.com 열어줘`
- `CSV 분석해서 저장해줘`
- `로그 리포트 만들어줘`

## 7. 로컬 TTS (CosyVoice3) 사용 시

- `CosyVoice3`는 초기 로드가 백그라운드에서 진행됩니다.
- 모델 워커는 재사용되므로 첫 실행 후 반복 호출이 더 안정적입니다.
- 짧은 응답(15자 이하)은 ODE 3스텝으로 자동 전환되어 약 200ms 더 빠릅니다.
- TTS 품질/지연을 바꾸려면 엔진 설정을 조정하고, 테마 변경과는 별개로 보시면 됩니다.

### CosyVoice3 설치

```bash
# 대화형 설치 (기본 경로: %USERPROFILE%\CosyVoice)
py -3.11 install_cosyvoice.py

# 경로 직접 지정
py -3.11 install_cosyvoice.py --dir "D:\MyApps\CosyVoice"
```

설치 후 설정창 → **AI & TTS → TTS 모드 → 로컬 (CosyVoice3)** 선택,
**CosyVoice 경로**란에 설치 경로를 입력하거나 자동 감지 버튼을 클릭합니다.

## 8. NVIDIA NIM 사용 시

1. `https://build.nvidia.com` 에서 `nvapi-...` 형식의 API 키를 발급받으세요.
2. 설정창 → AI&TTS 탭 → 제공자를 **NVIDIA NIM** 으로 변경합니다.
3. API 키를 입력하고 저장합니다.
4. 모델 이름은 비워두면 `meta/llama-3.3-70b-instruct` 가 기본값입니다.
   다른 모델을 사용하려면 NIM 카탈로그에서 모델 ID를 복사해 직접 입력하세요.

## 9. 플러그인 확장

사용자 플러그인은 `%AppData%\Ari\plugins` 폴더에 Python 파일로 추가합니다.
앱 시작 시 자동 로드되며, 설정창 `확장` 탭에서 목록과 로드 상태를 확인할 수 있습니다.

플러그인에서 사용할 수 있는 훅:

| 훅 | 설명 |
|----|------|
| `context.register_menu_action(label, callback)` | 트레이 메뉴 항목 추가 |
| `context.register_command(BaseCommand)` | 음성 명령 동적 등록 |
| `context.register_tool(schema, handler)` | LLM tool calling 확장 |
| `context.run_sandboxed(code, timeout=15)` | 서브프로세스 격리 실행 |

`PLUGIN_INFO`에 `"api_version": "1.0"` 선언이 필수입니다.
자세한 작성 방법은 [플러그인 가이드](./PLUGIN_GUIDE.md)를 참고하세요.

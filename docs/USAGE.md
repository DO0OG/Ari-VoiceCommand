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
3. 필요한 경우 `AI & TTS` 탭 상단 `로컬 설치` 섹션에서 Ollama 또는 CosyVoice3를 먼저 설치합니다.
4. AI 모델, TTS, UI 테마를 원하는 값으로 조정합니다.
5. 웨이크워드(`아리야`) 또는 트레이 메뉴 → `💬 텍스트 대화`로 명령합니다.
6. 개발 모드에서 생성되는 설정/메모리/예약 상태는 `VoiceCommand/.ari_runtime/` 아래에 저장됩니다.

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

## 6-1. 자율 실행과 복구 동작

- 최근 자율 실행 엔진은 단계별 상태 변화(active window, URL, 새 창, 새 파일)를 기록합니다.
- 비슷한 목표를 여러 번 수행하면 과거 성공/실패 에피소드와 실행 정책이 다음 계획에 반영됩니다.
- 기존 문서를 덮어써야 하는 작업은 저장 전에 자동 백업을 남깁니다.
- 실패 후 플래너는 복구 가능한 파일과 최근 유사 실패 에피소드를 참고해 다시 계획할 수 있습니다.
- 실행 중 누락 패키지(`ModuleNotFoundError`) 발생 시 자동으로 `pip install`을 시도합니다.
  - pandas, numpy, Pillow 등 **안전 패키지**는 TTS 알림과 함께 자동 설치합니다.
  - 미확인 패키지는 **사용자 확인 다이얼로그**(15초 타임아웃)를 통해 동의 후 설치합니다.

### 자가학습 진행도 빠른 가이드

- **0~50회 실행**: 아직 탐색 단계라 같은 앱/사이트에서도 재계획이 잦을 수 있습니다. 파일/앱 제어는 비교적 빨리 안정화되지만, 브라우저 GUI 작업은 성공률 편차가 큽니다.
- **50~200회 실행**: `PlannerFeedback`, `GoalPredictor`, `EpisodeMemory`가 누적되면서 같은 실패를 덜 반복합니다. 반복 작업은 스킬화와 컴파일 이점이 체감되기 시작합니다.
- **200회+ 실행**: 검증된 전략 재사용 비중이 커지고, `LearningMetrics`와 `RegressionGuard`를 통해 어떤 학습 요소가 실제 성능 향상에 기여하는지 모니터링할 수 있습니다.
- 더 자세한 성공률 가이드는 루트 [README](../README.md)를 참고하세요.

## 6-2. 고강도 자율성 점검 명령 예시

아래처럼 조건이 많은 명령으로 템플릿/복구 동작을 한 번에 점검할 수 있습니다.

```text
바탕화면에 "Ari autonomy final audit" 폴더를 만들고, 현재 열린 창 제목들을 수집해서
브라우저 관련 창과 일반 앱 창으로 분류한 markdown 보고서를 summary.md로 저장해줘.
브라우저 창은 서비스 기준으로 묶고 탭 수를 추정해서 같이 적어줘.
같은 이름 파일이 이미 있으면 자동 백업하고 안전하게 덮어써줘.
끝나면 어떤 전략을 선택했고 무엇을 검증했는지도 5줄 이내로 짧게 써줘.
```

검증 포인트:
- 폴더 생성 여부 (`Desktop/Ari autonomy final audit`)
- 보고서 파일 생성 여부 (`summary.md`)
- 보고서 섹션: 브라우저 분류 / 일반 앱 분류 / 탭 추정 / 백업 및 덮어쓰기
- 같은 파일명 재실행 시 백업 이력 증가 여부

## 7. 로컬 TTS (CosyVoice3) 사용 시

- `CosyVoice3`는 초기 로드가 백그라운드에서 진행됩니다.
- 모델 워커는 재사용되므로 첫 실행 후 반복 호출이 더 안정적입니다.
- 짧은 응답(15자 이하)은 ODE 3스텝으로 자동 전환되어 약 200ms 더 빠릅니다.
- TTS 품질/지연을 바꾸려면 엔진 설정을 조정하고, 테마 변경과는 별개로 보시면 됩니다.
- 텍스트 채팅 UI에서는 스트리밍 응답 중 문장 경계가 감지되면 전체 응답 완료 전에도 TTS가 먼저 시작될 수 있습니다.

### CosyVoice3 설치

```bash
# 대화형 설치 (기본 경로: %USERPROFILE%\CosyVoice)
py -3.11 install_cosyvoice.py

# 경로 직접 지정
py -3.11 install_cosyvoice.py --dir "D:\MyApps\CosyVoice"
```

설정창에서 더 간단하게 진행하려면 **AI & TTS → 로컬 설치 → CosyVoice 설치** 버튼을 사용하면 됩니다.

설치 후 설정창 → **AI & TTS → TTS 모드 → 로컬 (CosyVoice3)** 선택,
**CosyVoice 경로**란에 설치 경로를 입력하거나 자동 감지 버튼을 클릭합니다.

## 8. Ollama 로컬 LLM 사용 시

인터넷 없이, API 비용 없이 로컬에서 LLM을 실행합니다.

1. 설정창 → **AI & TTS → 로컬 설치 → Ollama 설치/모델 받기** 버튼으로 설치하거나,
   [https://ollama.com](https://ollama.com) 에서 직접 설치합니다.
2. 설정창 설치 버튼을 쓰지 않았다면 터미널에서 모델을 다운로드합니다.

   ```bash
   ollama pull llama3.2      # 4GB, 범용
   ollama pull qwen2.5       # 5GB, 한국어 강함 (권장)
   ```

3. 설정창 → **AI & TTS → LLM 제공자 → "Ollama (로컬 LLM)"** 선택합니다.
4. 모델명을 입력하고 저장합니다 (예: `qwen2.5`).
5. Ollama 서버 주소는 기본값 `http://localhost:11434/v1` 을 유지하거나 변경합니다.

스크립트로 설치하려면:

```bash
py -3.11 install_ollama.py
py -3.11 install_ollama.py --models llama3.2:3b qwen3:4b
```

권장 사양: RAM 8GB+, GPU VRAM 4GB+(선택).

## 9. NVIDIA NIM 사용 시

1. `https://build.nvidia.com` 에서 `nvapi-...` 형식의 API 키를 발급받으세요.
2. 설정창 → AI&TTS 탭 → 제공자를 **NVIDIA NIM** 으로 변경합니다.
3. API 키를 입력하고 저장합니다.
4. 모델 이름은 비워두면 `meta/llama-3.3-70b-instruct` 가 기본값입니다.
   다른 모델을 사용하려면 NIM 카탈로그에서 모델 ID를 복사해 직접 입력하세요.

## 10. 음성 메모리 명령

학습된 패턴·기억을 음성으로 조회하거나 관리합니다.

| 예시 | 동작 |
|------|------|
| `내가 자주 하는 작업 뭐야?` | 자주 요청하는 작업 유형 TTS 출력 |
| `저번에 내가 뭐라고 했어?` | 대화 기록 FTS 검색 결과 TTS |
| `내 스킬 목록 보여줘` | 자동 추출된 스킬 목록 TTS |
| `이 스킬 삭제해줘` | 첫 번째 스킬 비활성화 |
| `메모리 정리해줘` | 저신뢰 FACT 제거·대화 압축·전략 정리 즉시 실행 |
| `나에 대해 뭐 알아?` | 사용자 프로파일 + 주요 사실 요약 TTS |

## 11. 플러그인 확장

사용자 플러그인은 `%AppData%\Ari\plugins` 폴더에 단일 Python 파일 또는 ZIP 패키지로 추가합니다.
앱 시작 시 자동 로드되며, 설정창 `확장` 탭에서 목록과 로드 상태를 확인할 수 있습니다.
같은 탭의 마켓플레이스 섹션에서 플러그인을 검색하고 바로 설치할 수도 있습니다.

플러그인에서 사용할 수 있는 훅:

| 훅 | 설명 |
|----|------|
| `context.register_menu_action(label, callback)` | 트레이·캐릭터 우클릭 메뉴 항목 추가 |
| `context.register_command(BaseCommand)` | 음성 명령 동적 등록 |
| `context.register_tool(schema, handler)` | LLM tool calling 확장 |
| `context.run_sandboxed(code, timeout=15)` | 별도 Python 프로세스 격리 실행 |
| `context.set_character_menu_enabled(bool)` | 캐릭터 우클릭 메뉴 표시 여부 제어 |

`PLUGIN_INFO`에 `"api_version": "1.0"` 선언이 필수입니다.
자세한 작성 방법은 [플러그인 가이드](./PLUGIN_GUIDE.md)를 참고하세요.

# 프로그램 사용 가이드

이 문서는 Ari의 실행 방법, 기본 사용 흐름, 로컬 AI 설정, 자동화 기능, 확장 방법을 안내합니다.
README가 프로젝트 개요를 설명한다면, 이 문서는 실제 사용과 설정 절차에 초점을 둡니다.

## 1. 실행

먼저 기본 의존성을 설치한 뒤 앱을 실행합니다.

```bash
py -3.11 -m pip install -r VoiceCommand/requirements.txt
cd VoiceCommand
py -3.11 Main.py
```

설치 후에는 아래 검증 명령 실행을 권장합니다.

```bash
py -3.11 validate_repo.py
```

### 선택 의존성 설치

기본 의존성만으로도 앱은 실행되지만, 아래 기능은 추가 패키지가 필요합니다.

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

처음 실행했다면 아래 순서로 설정을 마치는 것을 권장합니다.

1. 앱을 실행합니다.
2. 트레이 아이콘 우클릭으로 설정창을 엽니다.
3. 필요한 경우 `AI & TTS` 탭 상단 `로컬 설치` 섹션에서 Ollama 또는 CosyVoice3를 먼저 설치합니다.
4. AI 모델, TTS, UI 테마를 원하는 값으로 조정합니다.
5. 웨이크워드(`아리야`) 또는 트레이 메뉴 → `💬 텍스트 대화`로 명령합니다.
6. 소스에서 `py Main.py`로 실행하면 설정/메모리/예약 상태는 `VoiceCommand/.ari_runtime/` 아래에 저장됩니다.
7. `build_exe.py`로 빌드한 exe를 실행하면 같은 상태 파일은 `%AppData%/Ari/` 아래에 저장됩니다.
8. CosyVoice용 `reference.wav`도 같은 규칙을 따릅니다. 소스/테스트 실행 시 `VoiceCommand/.ari_runtime/reference.wav`를 먼저 찾고, 없으면 `VoiceCommand/reference.wav`를 사용합니다. 빌드된 exe 실행 시에는 `%AppData%/Ari/reference.wav`를 먼저 찾고, 없으면 번들된 `reference.wav`를 사용합니다.

### 2-1. 캐릭터 위젯 신규 반응 기능

최근 버전에서는 캐릭터 위젯이 단순 장식이 아니라 상태를 반영하는 상호작용 UI로 확장되었습니다.

- **친밀도 확인:** 트레이 메뉴 `💝 친밀도 확인`
- **포커스 앱 반응 토글:** 트레이 메뉴 `🖥️ 앱 전환 반응`
- **시스템 모니터 토글:** 트레이 메뉴 `💻 시스템 모니터`
- **생일 등록:** 트레이 메뉴 `🎂 생일 등록`
- **말풍선 히스토리 / 커스텀 메시지:** 트레이 메뉴 `📜 최근 말풍선 히스토리`, `✏️ 커스텀 메시지 관리`

기능 요약:

- 클릭, 쓰다듬기, 대화, 일일 첫 실행이 **친밀도 포인트**에 반영됩니다.
- 캐릭터 위에서 마우스를 천천히 움직이면 **쓰다듬기**로 인식됩니다.
- 전면 앱 종류(코딩, 브라우저, 영상, 메신저, 오피스, 게임)에 따라 **감정과 말풍선**이 달라집니다.
- 밤 시간대에는 **졸린 모드**가 적용되어 하품과 느린 idle/sleep 반응이 늘어납니다.
- CPU/RAM/배터리 상태에 따라 **시스템 경고 반응**이 출력됩니다.
- 최근 말풍선 50개를 저장하고, 사용자가 직접 **커스텀 idle 메시지**를 추가할 수 있습니다.

## 3. 텍스트 채팅 UI

텍스트 채팅 UI를 통해 음성 입력 없이도 대부분의 기능을 사용할 수 있습니다.

- 음성 없이도 대화와 작업 실행이 가능합니다.
- 상단 `기억 상태` 패널에서 최근 주제, 추천 명령, 선호 요약을 확인할 수 있습니다.
- 스마트 어시스턴트 모드를 켜면 복합 요청이 도구 실행이나 `run_agent_task`로 더 적극적으로 이어질 수 있습니다.
- 다만 이 모드는 자율실행 엔진 자체의 ON/OFF가 아닙니다. 모드가 꺼져 있어도 명시적인 다단계 요청이나 LLM의 직접 tool call로 에이전트 실행이 일어날 수 있습니다.
- 긴 답변도 채팅 패널 너비를 넘지 않도록 말풍선 폭이 자동으로 제한되며, 텍스트는 패널 안에서 줄바꿈됩니다.

## 3-1. 예약 작업 UI

- 예약 작업 관리 창과 사이드 패널은 긴 작업명·설명·스케줄 문자열을 자동 줄바꿈해 보여줍니다.
- 최근 실행 결과가 길어도 가로 스크롤 없이 패널 안에서 읽을 수 있도록 구성되어 있습니다.

## 4. 에이전트 스킬 (Skills) / MCP

Agent Skills와 MCP는 Ari의 에이전트 작업 범위를 확장하는 주요 수단입니다.

### 4-1. 어디서 관리하나요?

- 트레이 메뉴의 `🧩 스킬 관리`
- 설정창 `확장` 탭 아래 `Agent Skills` 섹션

위 두 경로에서 같은 스킬 목록을 관리합니다.

### 4-2. 어떤 형식을 지원하나요?

- **로컬 경로:** `...\my-skill\SKILL.md`
- **GitHub 경로:** `NomaDamas/k-skill/tree/main/coupang-product-search`
- **HTTPS URL:** `SKILL.md` 직접 URL 또는 GitHub ZIP 다운로드 경로

스킬을 설치하면 런타임 기준 `skills/` 디렉터리에 저장되며, 스킬 설명, 원본, 활성화 상태를 함께 관리합니다.

### 4-3. MCP 스킬은 어떻게 동작하나요?

- `SKILL.md` 안에 HTTPS `/mcp` 엔드포인트가 있으면 MCP 스킬로 인식합니다.
- 사용자 요청이 해당 스킬 키워드와 맞으면 LLM 시스템 프롬프트에 스킬 내용과 MCP 안내가 자동으로 주입됩니다.
- 실제 실행은 내장 도구 `mcp_call(endpoint, tool, arguments)`를 통해 처리됩니다.
- 현재 MCP 호출은 **HTTPS 엔드포인트만 허용**합니다.

### 4-4. 스킬 메타데이터와 i18n은 어떻게 쓰나요?

스킬 라우팅 품질을 높이려면 `SKILL.md` frontmatter에 아래 필드를 넣는 것을 권장합니다.

- `skill_type`: `prompt_only` / `search` / `script` / `mcp`
- `triggers_ko`, `triggers_en`, `triggers_ja`: 언어별 매칭 키워드
- `description_ko`, `description_en`, `description_ja`: 언어별 스킬 설명
- `search_query_template_ko`, `search_query_template_en`, `search_query_template_ja`: 실시간 검색형 스킬의 언어별 검색 템플릿

예시:

```yaml
skill_type: search
triggers_ko:
  - 경기 결과
  - 순위
triggers_en:
  - match results
  - standings
triggers_ja:
  - 試合結果
  - 順位
description_ko: 특정 리그 경기 결과와 순위를 조회한다.
description_en: Retrieve match results and standings for a league.
description_ja: リーグの試合結果と順位を取得する。
search_query_template_ko: LCK {date} 경기 결과
search_query_template_en: LCK {date} match results
search_query_template_ja: LCK {date} 試合結果
```

추가 참고:

- 새 스킬이 위 필드를 모두 제공하지 않아도 Ari는 스킬 이름/설명 기반으로 **기본 키워드 fallback** 을 시도합니다.
- 다만 다국어 사용자 경험을 안정적으로 보장하려면 `triggers_*` / `description_*` 를 명시하는 편이 가장 안전합니다.
- `search` 타입 스킬은 실시간 데이터 질의에서 `web_search` 우선 경로로 라우팅됩니다.
- `script` 타입 스킬은 필요 시 `run_agent_task` 경로로 승격됩니다.

### 4-5. UI에서 무엇을 할 수 있나요?

- 설치된 스킬 목록 확인
- `SKILL.md` 본문 미리보기
- MCP 스킬 `[MCP]` 배지 확인
- 활성화 / 비활성화 전환
- 설치 원본이 있을 경우 업데이트
- 스킬 삭제

### 4-6. 플러그인과 무엇이 다른가요?

- **플러그인:** Python 코드/ZIP을 앱에 로드해 기능을 직접 확장
- **Agent Skills:** `SKILL.md` 지침과 선택적 `scripts/`, MCP 엔드포인트를 통해 LLM 도구 사용 흐름을 확장

즉, 플러그인은 런타임 기능 확장이고, Agent Skills는 에이전트 작업 지식과 도구 연결 확장에 가깝습니다.

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

아래 예시는 예약 작업 기능이 처리할 수 있는 대표적인 요청 형태입니다.

- `5분 뒤에 알림 줘`
- `11시에 메모장 열어줘`
- `11시 30분에 보고서 정리해줘`
- `매일 오전 9시에 날씨 알려줘`
- `예약된 작업 뭐 있어?` — 스케줄 목록 조회
- `예약 취소해줘` — 작업 ID로 취소

## 6. 자주 쓰는 자동화 예시

아래 예시는 자율 실행 엔진이나 도구 호출로 자주 처리하는 자동화 요청입니다.

- `바탕화면에 sample 폴더 만들어줘`
- `크롬으로 https://example.com 열어줘`
- `CSV 분석해서 저장해줘`
- `로그 리포트 만들어줘`

## 6-1. 자율 실행과 복구 동작

최근 자율 실행 엔진은 실행 중 상태 기록, 실패 복구, 반복 작업 최적화를 함께 다룹니다.

- 최근 자율 실행 엔진은 단계별 상태 변화(active window, URL, 새 창, 새 파일)를 기록합니다.
- 비슷한 목표를 여러 번 수행하면 과거 성공/실패 에피소드와 실행 정책이 다음 계획에 반영됩니다.
- 실패 후에는 ReflectionEngine이 lesson과 avoid pattern을 만들고, lesson이 충분하면 같은 실행 안에서 1회 재시도 컨텍스트로 즉시 재주입됩니다.
- 기존 문서를 덮어써야 하는 작업은 저장 전에 자동 백업을 남깁니다.
- 실패 후 플래너는 복구 가능한 파일과 최근 유사 실패 에피소드를 참고해 다시 계획할 수 있습니다.
- 실행 중 누락 패키지(`ModuleNotFoundError`) 발생 시 자동으로 `pip install`을 시도합니다.
  - pandas, numpy, Pillow 등 **안전 패키지**는 TTS 알림과 함께 자동 설치합니다.
  - 미확인 패키지는 **사용자 확인 다이얼로그**(15초 타임아웃)를 통해 동의 후 설치합니다.

### 자가학습 진행도 빠른 가이드

- **0~50회 실행**: 아직 탐색 단계라 같은 앱/사이트에서도 재계획이 잦을 수 있습니다. 파일/앱 제어는 비교적 빨리 안정화되지만, 브라우저 GUI 작업은 성공률 편차가 큽니다.
- **50~200회 실행**: `PlannerFeedback`, `GoalPredictor`, `EpisodeMemory`가 누적되면서 같은 실패를 덜 반복합니다. 반복 작업은 스킬화와 컴파일 이점이 체감되기 시작합니다.
- **200회+ 실행**: 검증된 전략 재사용 비중이 커지고, `LearningMetrics`와 `RegressionGuard`를 통해 어떤 학습 요소가 실제 성능 향상에 기여하는지 모니터링할 수 있습니다.
- 더 자세한 성공률 가이드는 한국어 [README](../README.ko.md)를 참고하세요.

## 6-3. 자기개선 루프 관찰 포인트

최근 버전에서는 자기개선 루프를 아래 관점에서 직접 확인할 수 있습니다.

- **Reflection 재시도**
  - 첫 실행 실패 후 lesson이 생성되면 같은 실행 안에서 1회 재시도가 일어날 수 있습니다.
  - 이때 planner context에는 `reflection_insight`, `avoid_patterns`가 함께 주입됩니다.
- **Background reflection**
  - 첫 실행이 성공하면 reflection은 백그라운드에서 예약될 수 있어 응답 완료를 막지 않습니다.
  - lesson은 이후 `StrategyMemory`에 반영되어 다음 유사 목표에서 활용됩니다.
- **스킬 매칭 품질**
  - 스킬 조회는 trigger pattern / context tag뿐 아니라 goal embedding 유사도도 함께 사용합니다.
  - 비슷한 표현(예: “크롬 열어줘” / “크롬 브라우저 실행”)도 더 잘 재사용됩니다.
- **컴파일 실패 추적**
  - Python 컴파일이 실패한 스킬은 실패 플래그를 남기고, 같은 임계 조건에서 무한 재시도하지 않습니다.

## 6-4. 주간 자기개선 리포트에서 볼 수 있는 항목

주간 리포트에는 기존 성공률/반복 실패 패턴 외에 자기개선 루프 자체의 활동 정보도 포함됩니다.

- 학습 컴포넌트별 활성화 횟수
- 해당 컴포넌트가 활성화된 실행의 최근 성공률
- 최근 기간 신규 스킬 생성 수
- 최근 기간 Python 컴파일 완료 수
- 자기개선 루프 LLM 호출의 추정 토큰 사용량

이 정보는 반복 작업 자동화가 실제로 학습되고 있는지, 혹은 reflection/skill optimization 비용이 과도하지 않은지 빠르게 확인할 때 유용합니다.

## 6-2. 고강도 자율성 점검 명령 예시

아래처럼 조건이 많은 명령으로 템플릿 처리와 복구 동작을 한 번에 점검할 수 있습니다.

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

CosyVoice3를 사용하면 로컬 환경에서 비교적 안정적인 TTS 파이프라인을 구성할 수 있습니다.

- `CosyVoice3`는 초기 로드가 백그라운드에서 진행됩니다.
- 모델 워커는 재사용되므로 첫 실행 후 반복 호출이 더 안정적입니다.
- 짧은 응답(15자 이하)은 ODE 3스텝으로 자동 전환되어 약 200ms 더 빠릅니다.
- TTS 품질/지연을 바꾸려면 엔진 설정을 조정하고, 테마 변경과는 별개로 보시면 됩니다.
- 텍스트 채팅 UI에서는 스트리밍 응답 중 문장 경계가 감지되면 전체 응답 완료 전에도 TTS가 먼저 시작될 수 있습니다.
- 너무 짧은 앞문장은 바로 따로 읽지 않고, 인접한 다음 문장과 한 번에 묶어 재생해 불필요한 합성 호출 수를 줄입니다.
- 웨이크워드 대기는 TTS 재생 중뿐 아니라 재생 직후 짧은 보호 구간에도 잠시 멈춰, 스피커 에코를 호출어로 오인식하는 문제를 줄입니다.
- `reference.wav` 경로 우선순위는 다음과 같습니다.
  소스/테스트 실행: `VoiceCommand/.ari_runtime/reference.wav` → `VoiceCommand/reference.wav`
  빌드된 exe 실행: `%AppData%/Ari/reference.wav` → 번들된 `reference.wav`

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

Ollama를 사용하면 인터넷 연결이나 API 비용 없이 로컬에서 LLM을 실행할 수 있습니다.

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

권장 사양은 RAM 8GB+, GPU VRAM 4GB+(선택)입니다.

## 9. NVIDIA NIM 사용 시

1. `https://build.nvidia.com` 에서 `nvapi-...` 형식의 API 키를 발급받으세요.
2. 설정창 → AI&TTS 탭 → 제공자를 **NVIDIA NIM** 으로 변경합니다.
3. API 키를 입력하고 저장합니다.
4. 모델 이름은 비워두면 `meta/llama-3.3-70b-instruct` 가 기본값입니다.
   다른 모델을 사용하려면 NIM 카탈로그에서 모델 ID를 복사해 직접 입력하세요.

## 10. 음성 메모리 명령

학습된 패턴과 기억은 음성 명령으로 조회하거나 관리할 수 있습니다.

| 예시 | 동작 |
|------|------|
| `내가 자주 하는 작업 뭐야?` | 자주 요청하는 작업 유형 TTS 출력 |
| `저번에 내가 뭐라고 했어?` | 대화 기록 FTS 검색 결과 TTS |
| `내 스킬 목록 보여줘` | 자동 추출된 스킬 목록 TTS |
| `이 스킬 삭제해줘` | 첫 번째 스킬 비활성화 |
| `메모리 정리해줘` | 저신뢰 FACT 제거·대화 압축·전략 정리 즉시 실행 |
| `나에 대해 뭐 알아?` | 사용자 프로파일 + 주요 사실 요약 TTS |

## 11. 언어 및 국제화 (i18n)

Ari는 한국어 외에도 **영어(English)**와 **일본어(日本語)**를 지원합니다.

1. 설정창 → **장치 설정** 탭 하단 → **언어 설정** 섹션에서 원하는 언어를 선택하세요.
2. **저장** 버튼을 누르면 설정이 반영되며, 다음 시작 시 선택한 언어로 인터페이스와 음성이 전환됩니다.
3. 언어 변경 시 효과:
   - UI 텍스트(메뉴, 설정, 채팅창) 번역 적용
   - LLM 지시문(System Prompt)이 해당 언어에 맞춰 최적화
   - Edge TTS 사용 시 해당 언어의 기본 음성으로 자동 매핑
   - 플래너 프롬프트(실행 계획 생성) 최적화

### i18n 유지보수 메모

개발 중 사용자 표시 문자열을 추가하거나 수정했다면 아래 절차를 권장합니다.

1. 사용자 표시 문자열은 함수/메서드 내부에서 `_()` 로 감쌉니다.
2. `VoiceCommand/i18n/locales/ko|en|ja/LC_MESSAGES/ari.po` 3개 파일을 함께 갱신합니다.
3. 필요하면 `VoiceCommand/scripts/extract_strings.py` 로 누락 문자열을 점검합니다.
4. 마지막으로 `VoiceCommand/scripts/compile_po.py` 를 실행해 `.mo` 파일을 재생성합니다.

## 12. 플러그인 확장

사용자 플러그인을 통해 앱 동작을 직접 확장할 수 있습니다.

사용자 플러그인은 `%AppData%\Ari\plugins` 폴더에 단일 Python 파일 또는 ZIP 패키지로 추가합니다.
앱 시작 시 자동 로드되며, 설정창 `확장` 탭에서 목록과 로드 상태를 확인할 수 있습니다.
같은 탭의 마켓플레이스 섹션에서 플러그인을 검색하고 바로 설치할 수도 있습니다.
소스 저장소의 `VoiceCommand/plugins/`에 포함된 기본 플러그인은 소스 실행 시 `.ari_runtime/plugins/`로 복사되며, `build_exe.py` 빌드 시에도 `plugins/` 디렉터리 전체가 번들에 포함됩니다.

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

# 프로그램 사용 가이드

Ari를 어떻게 실행하고, 어떤 흐름으로 쓰고, 로컬 AI와 자동화를 어떻게 설정하는지 정리한 문서입니다.
README가 프로젝트 전체를 소개한다면, 이 문서는 실제로 쓰고 설정하는 절차에 초점을 둡니다.

## 1. 실행

먼저 기본 의존성을 설치한 뒤 앱을 실행합니다.

```bash
cd VoiceCommand
setup.bat
Ari.vbs
```

명령줄에서 설치하려면 `setup.bat` 대신
`py -3.11 install_dependencies.py`를 실행해 주세요.

일반 실행에는 콘솔 창을 띄우지 않는 `Ari.vbs`를 사용해 주세요. 시작 오류를
콘솔에서 직접 확인할 때만 진단용 `Ari.bat`를 사용해 주세요. `Ari.vbs` 실행이
실패하면 `VoiceCommand/.ari_runtime/launcher_error.log`의 마지막 부분을 담은
메시지 상자가 표시됩니다.

설치를 마쳤다면 아래 검증 명령을 한 번 돌려 보시길 권합니다.

```bash
.venv\Scripts\python.exe validate_repo.py
```

### 선택 의존성 설치

기본 의존성만 있어도 앱은 돌아가지만, 아래 기능을 쓰려면 패키지를 더 설치해야 합니다.

```bash
# OCR 기반 화면 텍스트 검증 (비전 검증 기능)
.venv\Scripts\python.exe -m pip install "easyocr>=1.7.0"          # 권장, 한국어 지원
# .venv\Scripts\python.exe -m pip install "pytesseract>=0.3.10"   # 경량 대안 (Tesseract 별도 설치 필요)

# 의미 기반 전략 기억 검색
.venv\Scripts\python.exe -m pip install sentence-transformers torch

# Edge TTS (무료 클라우드 TTS)
.venv\Scripts\python.exe -m pip install edge-tts

# ElevenLabs TTS
.venv\Scripts\python.exe -m pip install elevenlabs
```

> **주의**: easyocr가 NumPy를 올려 버릴 수 있습니다. 다만 `requirements.txt`에 `numpy<2` 제약이 걸려 있어 설치 순서와 상관없이 `numpy 1.x`가 유지됩니다.

### 프로젝트 가상환경 구조

- `.venv`에는 메인 앱과 일반 선택 의존성을 설치합니다.
- `.venv-tts`에는 CosyVoice3의 CUDA torch와 TTS 의존성만 설치합니다.

CosyVoice3의 CUDA torch와 메인 앱의 `sentence-transformers`가 쓰는 CPU torch를
한 환경에 같이 넣으면 서로 덮어쓸 수 있어서, 가상환경을 둘로 나눠 두었습니다.
CosyVoice3까지 준비하려면 `setup.bat --with-tts`를 실행해 주세요.

## 2. 기본 사용 흐름

처음 실행했다면 아래 순서대로 설정을 마치시면 됩니다.

1. 앱을 실행합니다.
2. 트레이 아이콘 우클릭으로 설정창을 엽니다.
3. 필요한 경우 `AI & TTS` 탭 상단 `로컬 설치` 섹션에서 Ollama 또는 CosyVoice3를 먼저 설치합니다.
4. AI 모델, TTS, UI 테마를 원하는 값으로 조정합니다.
5. 웨이크워드(`아리야`) 또는 트레이 메뉴 → `💬 텍스트 대화`로 명령합니다.
6. 소스에서 `.venv\Scripts\python.exe Main.py`로 실행하면 설정/메모리/예약 상태는 `VoiceCommand/.ari_runtime/` 아래에 저장됩니다.
7. `build_exe.py`로 빌드한 exe를 실행하면 같은 상태 파일은 `%AppData%/Ari/` 아래에 저장됩니다.
8. CosyVoice용 `reference.wav`도 같은 규칙을 따릅니다. 소스/테스트 실행 시 `VoiceCommand/.ari_runtime/reference.wav`를 먼저 찾고, 없으면 `VoiceCommand/reference.wav`를 사용합니다. 빌드된 exe 실행 시에는 `%AppData%/Ari/reference.wav`를 먼저 찾고, 없으면 번들된 `reference.wav`를 사용합니다.

### 2-1. 캐릭터 위젯 플러그인 확장

캐릭터 위젯은 마켓플레이스 플러그인으로 상태에 반응하는 UI까지 확장할 수 있습니다.

예를 들면 이런 기능을 플러그인으로 붙일 수 있습니다.

- 친밀도 확인 오버레이
- 포그라운드 앱 반응
- 시스템 모니터 오버레이
- 특별 날짜 / 생일 이벤트
- 말풍선 히스토리 / 커스텀 메시지 관리

참고할 점:

- 메인 저장소에는 이런 기본 플러그인 구현을 넣지 않습니다.
- 필요한 기능은 마켓플레이스 ZIP을 내려받아 `%AppData%\Ari\plugins` 또는 `VoiceCommand\.ari_runtime\plugins`에 넣어 쓰면 됩니다.
- 플러그인을 설치하면 트레이 메뉴, 캐릭터 메뉴, 명령 체계에 해당 기능이 자동으로 등록될 수 있습니다.

## 3. 텍스트 채팅 UI

텍스트 채팅 UI만 써도 음성 입력 없이 대부분의 기능을 쓸 수 있습니다.

- 목소리를 내지 않고도 대화하고 작업을 시킬 수 있습니다.
- 상단 `기억 상태` 패널에서 최근 주제, 추천 명령, 선호 요약을 볼 수 있습니다.
- 스마트 어시스턴트 모드를 켜면 복합 요청이 도구 실행이나 `run_agent_task`로 더 적극적으로 이어집니다.
- 다만 이 모드는 자율 실행 엔진을 켜고 끄는 스위치가 아닙니다. 모드가 꺼져 있어도 다단계 요청을 명시하거나 LLM이 직접 tool call을 하면 에이전트가 움직일 수 있습니다.
- 답변이 길어도 말풍선 폭이 채팅 패널 너비를 넘지 않게 제한되고, 텍스트는 패널 안에서 줄바꿈됩니다.

## 3-1. 예약 작업 UI

- 예약 작업 관리 창과 사이드 패널은 긴 작업명·설명·스케줄 문자열을 알아서 줄바꿈해 보여줍니다.
- 최근 실행 결과가 길어도 가로 스크롤 없이 패널 안에서 읽을 수 있습니다.

## 4. 에이전트 스킬 (Skills) / MCP

Agent Skills와 MCP는 Ari가 다룰 수 있는 작업 범위를 넓히는 핵심 수단입니다.

### 4-1. 어디서 관리하나요?

- 트레이 메뉴의 `🧩 스킬 관리`
- 설정창 `확장` 탭 아래 `Agent Skills` 섹션

두 경로 모두 같은 스킬 목록으로 이어집니다.

### 4-2. 어떤 형식을 지원하나요?

- **로컬 경로:** `...\my-skill\SKILL.md`
- **GitHub 경로:** `NomaDamas/k-skill/tree/main/coupang-product-search`
- **HTTPS URL:** `SKILL.md` 직접 URL 또는 GitHub ZIP 다운로드 경로

설치한 스킬은 런타임 기준 `skills/` 디렉터리에 저장되고, 설명·원본·활성화 상태도 함께 관리됩니다.

### 4-3. MCP 스킬은 어떻게 동작하나요?

- `SKILL.md` 안에 HTTPS `/mcp` 엔드포인트가 적혀 있으면 MCP 스킬로 인식합니다.
- 사용자 요청이 그 스킬의 키워드와 맞으면 LLM 시스템 프롬프트에 스킬 내용과 MCP 안내가 자동으로 들어갑니다.
- 실제 실행은 내장 도구 `mcp_call(endpoint, tool, arguments)`이 맡습니다.
- MCP 호출은 **HTTPS 엔드포인트만 허용**합니다.

### 4-4. 스킬 메타데이터와 i18n은 어떻게 쓰나요?

스킬 라우팅 품질을 높이려면 `SKILL.md` frontmatter에 아래 필드를 넣어 두시길 권합니다.

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

덧붙이면:

- 위 필드를 다 채우지 않아도 Ari는 스킬 이름과 설명으로 **기본 키워드 fallback** 을 시도합니다.
- 다만 다국어 사용자 경험을 안정적으로 맞추려면 `triggers_*` 와 `description_*` 를 적어 두는 편이 가장 안전합니다.
- `search` 타입 스킬은 실시간 데이터 질의에서 `web_search` 우선 경로를 탑니다.
- `script` 타입 스킬은 필요하면 `run_agent_task` 경로로 승격됩니다.

### 4-5. UI에서 무엇을 할 수 있나요?

- 설치된 스킬 목록 확인
- `SKILL.md` 본문 미리보기
- MCP 스킬 `[MCP]` 배지 확인
- 활성화 / 비활성화 전환
- 설치 원본이 있을 경우 업데이트
- 스킬 삭제

### 4-6. 플러그인과 무엇이 다른가요?

- **플러그인:** Python 코드나 ZIP을 앱에 로드해 기능 자체를 늘립니다.
- **Agent Skills:** `SKILL.md` 지침에 필요하면 `scripts/`와 MCP 엔드포인트를 곁들여 LLM의 도구 사용 흐름을 넓힙니다.

정리하면 플러그인은 런타임 기능을 늘리는 쪽이고, Agent Skills는 에이전트가 가진 작업 지식과 도구 연결을 넓히는 쪽입니다.

## 5. 시스템 제어 명령

### 종료 / 재시작 / 취소

| 예시 | 동작 |
|------|------|
| `컴퓨터 꺼줘` | 10초 후 종료 |
| `5분 뒤에 컴퓨터 꺼줘` | `shutdown /s /t 300` 예약 |
| `1시간 30분 뒤에 꺼줘` | `shutdown /s /t 5400` 예약 (복합 표현 지원) |
| `오후 11시에 컴퓨터 꺼줘` | 현재 시각 기준 남은 초 계산해 예약 |
| `컴퓨터 재시작해줘` / `재부팅해줘` | `shutdown /r /t 10` 실행 |
| `종료 취소해줘` | `shutdown /a` 실행, 예약 없으면 안내 |

`재부팅하지 마`, `컴퓨터 종료 방법 알려줘`처럼 부정하거나 다른 뜻이 섞인 말은 전원 명령으로 실행하지 않고 대화로 답합니다.
대화 모델의 응답에 종료가 언급되더라도, 사용자가 직접 종료를 요청하지 않았다면 컴퓨터를 끄지 않습니다.

### 타이머 / 알람

| 예시 | 동작 |
|------|------|
| `10분 타이머` / `10분 알람 맞춰줘` | 10분 타이머 설정 |
| `1분 30초 타이머` | 90초 타이머 설정 (복합 표현 지원) |
| `set timer for 1 hour 2 minutes` | 영어 시간 단위 지원 (hour/min/sec) |
| `1時間 5分 タイマー` | 일본어 시간 단위 지원 (時間/分/秒) |
| `타이머 취소` | 진행 중인 타이머 취소 |
| `타이머 얼마 남았어?` | 잔여 시간 TTS 응답 |

타이머 명령은 한국어·영어·일본어 시간 단위를 모두 알아듣습니다. 언어 설정과 상관없이 세 언어를 섞어 말해도 파싱됩니다.

## 6. 시간 예약 예시

예약 작업 기능이 처리할 수 있는 대표적인 요청 형태입니다.

- `5분 뒤에 알림 줘`
- `11시에 메모장 열어줘`
- `11시 30분에 보고서 정리해줘`
- `매일 오전 9시에 날씨 알려줘`
- `예약된 작업 뭐 있어?` — 스케줄 목록 조회
- `예약 취소해줘` — 작업 ID로 취소

## 7. 자주 쓰는 자동화 예시

자율 실행 엔진이나 도구 호출로 자주 처리하는 자동화 요청들입니다.

- `바탕화면에 sample 폴더 만들어줘`
- `크롬으로 https://example.com 열어줘`
- `CSV 분석해서 저장해줘`
- `로그 리포트 만들어줘`

## 7-1. 자율 실행과 복구 동작

자율 실행 엔진은 실행 중 상태 기록, 실패 복구, 반복 작업 최적화를 함께 다룹니다.

- 단계마다 상태 변화(활성 창, URL, 새 창, 새 파일)를 기록합니다.
- 비슷한 목표를 여러 번 수행하면 과거의 성공·실패 에피소드와 실행 정책이 다음 계획에 반영됩니다.
- 실패한 뒤에는 ReflectionEngine이 lesson과 avoid pattern을 만들고, lesson이 충분히 모이면 같은 실행 안에서 1회 재시도 컨텍스트로 바로 다시 넣습니다.
- 기존 문서를 덮어써야 하는 작업은 저장하기 전에 자동으로 백업을 남깁니다.
- 실패한 뒤 플래너는 복구할 수 있는 파일과 최근의 비슷한 실패 에피소드를 참고해 다시 계획을 세울 수 있습니다.
- 실행 도중 패키지가 없어 `ModuleNotFoundError`가 나면 자동으로 `pip install`을 시도합니다.
  - pandas, numpy, Pillow 같은 **안전 패키지**는 TTS로 알려 주면서 바로 설치합니다.
  - 확인되지 않은 패키지는 **사용자 확인 다이얼로그**(15초 타임아웃)에서 동의를 받은 뒤 설치합니다.
- 파일 삭제, 레지스트리 변경, 포맷 같은 **위험 작업**이 감지되면 `SafetyChecker`가 위험 등급을 매기고, 등급에 따라 **위험 작업 확인 다이얼로그**(15초 뒤 자동 취소)를 띄웁니다. 다이얼로그에는 감지된 위험 패턴 목록과 요약이 함께 나옵니다.
- 오래 걸리는 자율 작업은 `AgentTaskQueue`가 백그라운드에서 우선순위대로 처리합니다. 우선순위가 높은 작업이 큐에서 먼저 나가고, 작업 하나씩 따로 취소 신호를 보낼 수 있습니다.

### 자가학습 진행도 빠른 가이드

- **0~50회 실행**: 아직 탐색 단계라 같은 앱이나 사이트에서도 재계획이 잦습니다. 파일·앱 제어는 비교적 빨리 안정되지만, 브라우저 GUI 작업은 성공률 편차가 큽니다.
- **50~200회 실행**: `PlannerFeedback`, `GoalPredictor`, `EpisodeMemory`가 쌓이면서 같은 실패를 덜 반복합니다. 반복 작업에서는 스킬화와 컴파일의 이점이 슬슬 체감됩니다.
- **200회+ 실행**: 검증된 전략을 재사용하는 비중이 커지고, `LearningMetrics`와 `RegressionGuard`로 어떤 학습 요소가 실제 성능에 기여하는지 들여다볼 수 있습니다.
- 성공률에 대한 더 자세한 내용은 한국어 [README](../README.ko.md)를 참고하세요.

## 7-2. 자기개선 루프 관찰 포인트

자기개선 루프는 아래 지점에서 직접 눈으로 확인할 수 있습니다.

- **Reflection 재시도**
  - 첫 실행이 실패하고 lesson이 만들어지면, 같은 실행 안에서 한 번 더 시도할 수 있습니다.
  - 이때 planner context에는 `reflection_insight`와 `avoid_patterns`가 같이 들어갑니다.
- **Background reflection**
  - 첫 실행이 성공하면 reflection을 백그라운드로 미뤄 두기 때문에 응답이 늦어지지 않습니다.
  - 여기서 나온 lesson은 `StrategyMemory`에 반영되어 다음번 비슷한 목표에 쓰입니다.
- **스킬 매칭 품질**
  - 스킬을 찾을 때 trigger pattern과 context tag뿐 아니라 goal embedding 유사도까지 봅니다.
  - 덕분에 “크롬 열어줘”와 “크롬 브라우저 실행”처럼 표현만 다른 요청도 같은 스킬로 이어집니다.
- **컴파일 실패 추적**
  - Python 컴파일에 실패한 스킬은 실패 플래그를 남겨 두고, 같은 조건에서 무한정 다시 시도하지 않습니다.

## 7-3. 주간 자기개선 리포트에서 볼 수 있는 항목

주간 리포트에는 성공률과 반복 실패 패턴 외에 자기개선 루프 자체의 활동도 담깁니다.

- 학습 컴포넌트별 활성화 횟수
- 해당 컴포넌트가 활성화된 실행의 최근 성공률
- 최근 기간 신규 스킬 생성 수
- 최근 기간 Python 컴파일 완료 수
- 자기개선 루프 LLM 호출의 추정 토큰 사용량

반복 작업 자동화가 실제로 학습되고 있는지, reflection이나 skill optimization 비용이 과하지는 않은지 빠르게 가늠할 때 유용합니다.

## 7-4. 고강도 자율성 점검 명령 예시

조건을 잔뜩 붙인 아래 같은 명령 하나로 템플릿 처리와 복구 동작을 한꺼번에 점검할 수 있습니다.

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

## 8. 로컬 TTS (CosyVoice3) 사용 시

CosyVoice3를 쓰면 로컬에서 꽤 안정적인 TTS 파이프라인을 꾸릴 수 있습니다.

- `CosyVoice3`의 초기 로드는 백그라운드에서 진행됩니다.
- 모델 워커를 재사용하기 때문에 첫 실행 이후의 반복 호출이 더 안정적입니다.
- 15자 이하의 짧은 응답은 ODE 3스텝으로 자동 전환되어 약 200ms 빨라집니다.
- TTS 품질이나 지연을 조절하려면 엔진 설정을 손보면 됩니다. 테마 변경과는 별개입니다.
- 텍스트 채팅 UI에서는 스트리밍 도중 문장 경계가 잡히면, 응답이 다 끝나기 전에도 TTS가 먼저 시작될 수 있습니다.
- 앞 문장이 너무 짧으면 따로 읽지 않고 다음 문장과 묶어서 재생해, 불필요한 합성 호출을 줄입니다.
- 웨이크워드 대기는 TTS가 재생되는 동안은 물론 재생 직후 짧은 보호 구간에도 잠시 멈춥니다. 스피커에서 나온 소리를 호출어로 잘못 듣는 일을 줄이기 위해서입니다.
- `reference.wav` 경로 우선순위는 다음과 같습니다.
  소스/테스트 실행: `VoiceCommand/.ari_runtime/reference.wav` → `VoiceCommand/reference.wav`
  빌드된 exe 실행: `%AppData%/Ari/reference.wav` → 번들된 `reference.wav`

### CosyVoice3 설치

```bash
# 대화형 설치 (기본 경로: %USERPROFILE%\CosyVoice)
.venv\Scripts\python.exe install_cosyvoice.py

# 경로 직접 지정
.venv\Scripts\python.exe install_cosyvoice.py --dir "D:\MyApps\CosyVoice"
```

설치 스크립트가 CosyVoice 의존성을 `.venv-tts`에 알아서 설치합니다.

더 간단하게 하려면 설정창의 **AI & TTS → 로컬 설치 → CosyVoice 설치** 버튼을 쓰면 됩니다.

설치를 마쳤다면 설정창 → **AI & TTS → TTS 모드 → 로컬 (CosyVoice3)** 을 고르고,
**CosyVoice 경로**란에 설치 경로를 적거나 자동 감지 버튼을 누르세요.

## 9. Ollama 로컬 LLM 사용 시

Ollama를 쓰면 인터넷 연결이나 API 비용 없이 로컬에서 LLM을 돌릴 수 있습니다.

1. 설정창 → **AI & TTS → 로컬 설치 → Ollama 설치/모델 받기** 버튼으로 설치하거나,
   [https://ollama.com](https://ollama.com) 에서 직접 설치합니다.
2. 설정창 설치 버튼을 쓰지 않았다면 터미널에서 모델을 다운로드합니다.

   ```bash
   ollama pull llama3.2      # 4GB, 범용
   ollama pull qwen2.5       # 5GB, 한국어 강함 (권장)
   ```

3. 설정창 → **AI 설정 → LLM 제공자 → "Ollama (로컬 LLM)"** 을 선택합니다.
4. 모델명을 입력하고 저장합니다 (예: `qwen2.5`).
5. Ollama 서버 주소는 기본값 `http://localhost:11434/v1` 을 유지하거나 변경합니다.

스크립트로 설치하려면:

```bash
.venv\Scripts\python.exe install_ollama.py
.venv\Scripts\python.exe install_ollama.py --models llama3.2:3b qwen3:4b
```

권장 사양은 RAM 8GB+, GPU VRAM 4GB+(선택)입니다.

## 10. NVIDIA NIM 사용 시

1. `https://build.nvidia.com` 에서 `nvapi-...` 형식의 API 키를 발급받습니다.
2. 설정창 → **AI 설정** 탭에서 제공자를 **NVIDIA NIM** 으로 바꿉니다.
3. API 키를 넣고 저장합니다.
4. 모델 이름을 비워 두면 `meta/llama-3.3-70b-instruct` 가 기본값으로 쓰입니다.
   다른 모델을 쓰려면 NIM 카탈로그에서 모델 ID를 복사해 직접 넣으세요.
5. Nemotron 3 계열처럼 추론 과정을 출력하는 모델은 Ari가 추론 모드를 꺼서 요청합니다.
   추론 문장이 답변이나 음성에 섞여 나오지 않습니다.

## 10-1. OpenAI 호환 제공자 직접 추가

LM Studio, vLLM, 사내 게이트웨이처럼 OpenAI 호환 API를 제공하는 서버라면 목록에 없어도 제공자로 쓸 수 있습니다.

1. 설정창 → **AI 설정** 탭의 **사용자 지정 OpenAI 호환 제공자**에서 **제공자 추가**를 누릅니다.
2. 표시 이름과 기본 URL(예: `http://localhost:1234/v1`)을 입력하고 저장합니다.
   기본 URL은 `http://` 또는 `https://`로 시작해야 하며, 주소 안에 계정 정보나 `?`, `#`을 넣을 수 없습니다.
3. 제공자별 설정 목록에 새 항목이 생기면 기본 모델과 API 키를 넣고 **검증**으로 연결을 확인합니다. 키가 필요 없는 로컬 서버는 키 칸을 비워 둬도 됩니다.
4. 추가한 제공자는 기본 제공자와 계획·실행 역할 제공자 목록에 함께 나타납니다.

키는 설정 파일이 아니라 암호화 저장소에 보관됩니다(`docs/CREDENTIALS.md` 참고).
제공자를 삭제하면 저장된 키도 함께 지워지고, 그 제공자를 쓰던 선택은 기본 제공자는 Groq로, 계획·실행 역할은 "기본 제공자와 동일"로 돌아갑니다.

## 11. 음성 메모리 명령

학습한 패턴과 기억은 음성 명령으로 들여다보거나 정리할 수 있습니다.

| 예시 | 동작 |
|------|------|
| `내가 자주 하는 작업 뭐야?` | 자주 요청하는 작업 유형 TTS 출력 |
| `저번에 내가 뭐라고 했어?` | 대화 기록 FTS 검색 결과 TTS |
| `내 스킬 목록 보여줘` | 자동 추출된 스킬 목록 TTS |
| `이 스킬 삭제해줘` | 첫 번째 스킬 비활성화 |
| `메모리 정리해줘` | 저신뢰 FACT 제거·대화 압축·전략 정리 즉시 실행 |
| `나에 대해 뭐 알아?` | 사용자 프로파일 + 주요 사실 요약 TTS |

## 12. 언어 및 국제화 (i18n)

Ari는 한국어 외에도 **영어(English)**와 **일본어(日本語)**를 지원합니다.

1. 설정창 → **장치 설정** 탭 아래쪽 **언어 설정** 섹션에서 원하는 언어를 고릅니다.
2. **저장** 버튼을 누르면 설정이 반영되고, 다음 시작부터 인터페이스와 음성이 그 언어로 바뀝니다.
3. 언어를 바꾸면 이런 점이 달라집니다.
   - UI 텍스트(메뉴, 설정, 채팅창)에 번역이 적용됩니다.
   - LLM 지시문(System Prompt)이 해당 언어에 맞게 조정됩니다.
   - Edge TTS를 쓸 때 그 언어의 기본 음성으로 자동 매핑됩니다.
   - 플래너 프롬프트(실행 계획 생성)도 함께 조정됩니다.

### i18n 유지보수 메모

개발하면서 사용자에게 보이는 문자열을 넣거나 고쳤다면 아래 순서를 따르시면 됩니다.

1. 사용자에게 보이는 문자열은 함수나 메서드 안에서 `_()` 로 감쌉니다.
2. `VoiceCommand/i18n/locales/ko|en|ja/LC_MESSAGES/ari.po` 세 파일을 함께 갱신합니다.
3. 필요하면 `VoiceCommand/scripts/extract_strings.py` 로 빠진 문자열이 없는지 봅니다.
4. 마지막으로 `VoiceCommand/scripts/compile_po.py` 를 실행해 `.mo` 파일을 다시 만듭니다.

## 13. 플러그인 확장

플러그인을 쓰면 앱 동작을 직접 늘릴 수 있습니다.

사용자 플러그인은 `%AppData%\Ari\plugins` 폴더에 단일 Python 파일이나 ZIP 패키지로 넣습니다.
앱을 시작할 때 자동으로 로드되고, 설정창 `확장` 탭에서 목록과 로드 상태를 볼 수 있습니다.
같은 탭의 마켓플레이스 섹션에서 플러그인을 검색해 바로 설치할 수도 있습니다.
메인 저장소는 기본 플러그인을 함께 담지 않습니다. 플러그인은 마켓플레이스 ZIP으로 따로 배포하고, 사용자가 런타임 플러그인 폴더에 직접 넣는 방식이 기준입니다.

플러그인에서 쓸 수 있는 훅:

| 훅 | 설명 |
|----|------|
| `context.register_menu_action(label, callback)` | 트레이·캐릭터 우클릭 메뉴 항목 추가 |
| `context.register_command(BaseCommand)` | 음성 명령 동적 등록 |
| `context.register_tool(schema, handler)` | LLM tool calling 확장 |
| `context.run_sandboxed(code, timeout=15)` | 별도 Python 프로세스 격리 실행 |
| `context.set_character_menu_enabled(bool)` | 캐릭터 우클릭 메뉴 표시 여부 제어 |

`PLUGIN_INFO`에 `"api_version": "1.0"` 선언은 빠뜨리면 안 됩니다.
자세한 작성 방법은 [플러그인 가이드](./PLUGIN_GUIDE.md)를 참고하세요.

## 14. 고급 설정 키 (`ari_settings.json`)

아래 키는 소스 실행이라면 `VoiceCommand/.ari_runtime/ari_settings.json`, 빌드된 exe라면 `%AppData%\Ari\ari_settings.json`에서 직접 고칠 수 있습니다. 초기값은 `VoiceCommand/ari_settings.template.json`을 참고하세요.

> API 키와 봇 토큰 같은 인증값은 이 파일에 저장되지 않습니다. 같은 폴더의 암호화 저장소에 따로 보관하며, 설정 창이나 환경변수로 넣습니다. `ari_settings.json`에 직접 적어도 저장 시점에 지워집니다. 자세한 내용은 [API 키 보관](./CREDENTIALS.md)을 참고하세요.

### LLM 응답 캐시

| 키 | 기본값 | 설명 |
|----|--------|------|
| `agent_response_cache_ttl` | `600` | 응답 캐시 유효 시간(초). 같은 요청이면 이 시간 안에는 이전 LLM 호출 결과를 재사용합니다. |
| `agent_response_cache_max_size` | `50` | 캐시에 담을 최대 항목 수. 넘치면 가장 오래된 항목부터 밀려납니다. |

TTL을 `0` 이하로 두면 기본값인 600초가 적용됩니다. 캐시를 사실상 끄고 싶다면 `agent_response_cache_ttl`을 아주 낮게(예: `1`) 잡으세요.

### Telegram 원격 명령

아래 값을 채우면 허용된 Telegram 채팅에서 Ari에게 명령을 보낼 수 있습니다. 기본값은 비활성화이고, 허용 목록에 없는 `chat_id`는 처리하지 않고 로그만 남깁니다.

`telegram_bot_token`은 인증값이라 `ari_settings.json`이 아니라 암호화 저장소에 보관합니다. 설정 창에서 입력하거나 `ARI_TELEGRAM_BOT_TOKEN` 환경변수로 넣으세요. 나머지 키는 `ari_settings.json`에서 직접 고칠 수 있습니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `telegram_enabled` | `false` | Telegram long-polling 브리지 활성화 여부 |
| `telegram_bot_token` | `""` | BotFather에서 발급한 봇 토큰. 암호화 저장소 또는 `ARI_TELEGRAM_BOT_TOKEN`에 보관 |
| `telegram_allowed_chat_ids` | `[]` | 명령을 허용할 chat_id 목록. 문자열과 숫자 모두 가능 |
| `telegram_poll_timeout_seconds` | `25` | getUpdates long-polling timeout |

받은 명령은 로컬 텍스트 UI와 똑같은 흐름을 탑니다. 그래서 기존의 도구 실행, 안전 확인, 메모리 기록, 스트리밍 콜백이 그대로 쓰입니다.

사진은 그 요청에서 스크린샷·이미지 생성 도구가 실제로 만들어 낸 파일만 전송합니다. 응답 본문에 로컬 이미지 경로가 적혀 있어도 그것만으로는 전송하지 않습니다.

Telegram 메시지 한 건의 상한은 4096자입니다. 최종 응답이 이보다 길면 잘리지 않고 4096자 단위로 나뉘어 순서대로 전달됩니다.

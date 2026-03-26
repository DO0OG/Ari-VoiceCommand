# Ari (아리) — AI 음성 어시스턴트

> 한국어 음성 인식 기반 데스크탑 AI 어시스턴트.
> Shimeji 스타일 캐릭터 위젯 + 다중 LLM / TTS 제공자 선택 지원.

- 캐릭터 모델 제작 : [자라탕](https://www.pixiv.net/users/78194943)

![preview](https://github.com/user-attachments/assets/fc8de4b7-57ca-4c22-812c-e5dcc7b45cdd)

---

## 개발 현황

### 최근 업데이트 (2026-03-26)

- **캐릭터 드래그 버그 수정**: 벽/천장 타기 도중 드래그 시 중력이 적용되지 않던 문제 수정. (`mousePressEvent`에서 `is_climbing` 리셋)
- **팔레트 편집 별도 창**: 설정창 내 인라인 팔레트 편집기를 독립 창(`ThemeEditorDialog`)으로 분리.
- **플러그인 API 버전 협상**: `PLUGIN_INFO["api_version"]` 선언 → 비호환 버전 로드 자동 거부.
- **트레이 메뉴 동적 등록**: `context.register_menu_action(label, callback)` 으로 트레이 메뉴에 플러그인 항목 삽입.
- **음성 명령 동적 등록**: `context.register_command(BaseCommand)` 으로 런타임에 명령 추가 (priority 정렬 유지).
- **LLM 도구 동적 등록**: `context.register_tool(schema, handler)` 으로 tool calling 스키마·핸들러 확장 (내장 이름 충돌 시 거부).
- **플러그인 샌드박스**: `context.run_sandboxed(code, timeout)` — 서브프로세스 격리 실행, 타임아웃·예외 안전.

<details>
<summary>이전 업데이트 (2026-03-26 초기 ~ 2026-03-23)</summary>

**2026-03-26 (초기)**
- 역할별 LLM 분리 (기본/플래너/실행 제공자 분리, API 키 검증 UI)
- NVIDIA NIM 지원
- 비전 검증 4단계 파이프라인 (휴리스틱→OCR→코드→LLM)
- 브라우저 DOM 재계획 (`dom_analyser` 계층)
- DAG 기반 병렬 실행 (리소스 충돌 분석, Kahn 알고리즘)
- 전략 기억 임베딩 검색 + cross-encoder 재랭킹
- 기억 신뢰도 엔진 (출처 가중치·충돌·decay)
- 테마 팔레트 에디터 (색상 피커·JSON 직접 편집)
- CosyVoice 설치 경로 UI + `--dir` CLI 인자

**2026-03-25**
- 자율 실행 엔진 고도화 (Plan → Execute+Self-Fix → Verify, adaptive/resilient workflow)
- 파일 작업군 확장 (이름 변경, 병합, 폴더 정리, CSV/JSON 분석, 로그 리포트, 일괄 이름 변경)
- GUI/브라우저 자동화 강화 (페이지별 셀렉터 전략 축적, 다운로드 대기, 로그인 후 작업 재사용)
- 기억/전략 계층 강화 (FACT 충돌 이력, 해시 기반 유사 전략 검색, 주제 기반 선제 제안)
- 테마/플러그인 확장 (`%AppData%\Ari\theme` JSON 테마, hot-swap, 플러그인 로더)
- TTS 안정화 (CosyVoice3 cudnn.benchmark, 동적 ODE 스텝, 스트리밍 출력)

**2026-03-23**
- FACT 신뢰도 기초 (TTL, 충돌 이력, BIO/주제/명령 크기 제한)
- 선택적 병렬 실행 (read-only 단계 제한)
- 실패 분류형 전략 기억 + 의미 유사 전략 검색
- 실제 검증 강화 (경로/URL 아티팩트 우선 확인)
- 텍스트 UI `기억 상태` 패널, 에이전트-캐릭터 감정 연동

</details>

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| **웨이크워드** | "아리야" 호출 → 음성 입력 대기 |
| **음성 인식** | Google STT (기본) |
| **AI 대화** | Groq · OpenAI · Anthropic · Mistral · Gemini · OpenRouter · NVIDIA NIM |
| **역할별 LLM** | 기본 대화 / 플래너 / 실행·수정 모델을 제공자별로 분리 설정 |
| **감정 표현** | `(기쁨)` 등 AI 태그 기반 캐릭터 애니메이션 |
| **TTS** | Fish Audio · CosyVoice3(로컬) · OpenAI TTS · ElevenLabs · Edge TTS |
| **캐릭터 위젯** | Shimeji 스타일 드래그·물리 애니메이션 |
| **스마트 모드** | LLM tool calling으로 타이머·날씨·유튜브 자동 실행 |
| **자율 실행** | Python/Shell 코드 생성·실행 + LLM 자동 수정(Self-Fix) + DAG 병렬 실행 |
| **에이전트 루프** | Plan → Execute → Verify 3레이어 (최대 4회 재계획) |
| **작업 템플릿** | 폴더 생성, 검색·요약·저장, 시스템 보고서, 파일 이름 변경, 배치 작업 등 |
| **비전 검증** | OCR 화면 텍스트 인식 + 휴리스틱/코드/LLM 4단계 검증 |
| **DOM 재계획** | 브라우저 로그인 후 DOM 분석 → 다음 액션 자동 제안 |
| **기억 시스템** | FACT/BIO/PREF 장기 기억 + 출처별 신뢰도 decay + 대화 주제 자동 추출 |
| **전략 검색** | 임베딩(sentence-transformers)/재랭킹 + 해시 폴백 유사 전략 검색 |
| **테마 편집** | 설정창 내 팔레트 피커 + JSON 직접 편집 + 저장 |
| **안전 검사** | 위험 수준 3단계 분류 + 확인 다이얼로그 (15초 카운트다운) |
| **플러그인 확장** | API 버전 협상·메뉴/명령/도구 동적 등록·서브프로세스 샌드박스 |
| **빌드 시스템** | Nuitka 기반 EXE (단일 파일 · 폴더 선택) |

---

## 문서

- [문서 모음](docs/README.md)
- [프로그램 사용 가이드](docs/USAGE.md)
- [테마 커스터마이징 가이드](docs/THEME_CUSTOMIZATION.md)
- [플러그인 가이드](docs/PLUGIN_GUIDE.md)
- [캐릭터 이미지 가이드](docs/CHARACTER_IMAGES.md)

## 빠른 시작

### 요구 사항

| 항목 | 최소 | 권장 |
|------|------|------|
| Python | 3.11 | 3.11 |
| OS | Windows 10 | Windows 11 |
| RAM | 4 GB | 8 GB |
| GPU (로컬 TTS) | — | CUDA 12.x, VRAM 4 GB+ |

### 설치

```bash
# 1. 저장소 클론
git clone https://github.com/DO0OG/AI-Assistant.git
cd AI-Assistant

# 2. 가상환경 생성 (권장)
py -3.11 -m venv .venv
.venv\Scripts\activate

# 3. 의존성 설치
pip install -r VoiceCommand/requirements.txt

# 4. 실행
cd VoiceCommand
py -3.11 Main.py

# 5. 검증 (선택)
py -3.11 validate_repo.py
```

### 선택 의존성

OCR 기반 화면 검증이나 임베딩 기반 전략 검색을 사용하려면 별도 설치합니다.

```bash
# OCR (화면 텍스트 인식)
pip install easyocr          # 권장, 한국어 지원
# pip install pytesseract    # 경량, Tesseract 별도 설치 필요

# 임베딩 기반 전략 검색 (미설치 시 해시 폴백 자동 사용)
pip install sentence-transformers torch
```

### CosyVoice3 로컬 TTS 설치 (선택)

```bash
# 대화형 경로 입력 (실행 후 설치 경로를 직접 입력, 기본값: %USERPROFILE%\CosyVoice)
py -3.11 VoiceCommand/install_cosyvoice.py

# 경로 직접 지정
py -3.11 VoiceCommand/install_cosyvoice.py --dir "D:\MyApps\CosyVoice"
```

설치 후:
1. 설정 → **AI & TTS → TTS 모드 → 로컬 (CosyVoice3)** 선택
2. 설정 → **CosyVoice 경로** 에 설치 경로 입력 (또는 자동 감지 버튼 클릭)

---

## 설정

트레이 아이콘 우클릭 → **설정** 에서 4개의 탭으로 관리합니다.

1. **RP 설정**: 캐릭터 성격·시나리오·시스템 프롬프트·기억 지침
2. **AI & TTS 설정**: 기본/플래너/실행 모델 및 제공자, API 키 검증, TTS 엔진
3. **장치/UI 설정**: 마이크, 테마 프리셋, 글꼴 배율, **팔레트 직접 편집**
4. **확장 설정**: 플러그인 목록 확인 (api_version·로드 상태·오류 표시)

### 주요 사용 패턴

- 예약 명령: `5분 뒤`, `11시에`, `11시 30분에`
- 자주 쓰는 폴더: `다운로드 폴더 정리해줘`, `바탕화면 파일 세트 확인해줘`
- 브라우저 작업: `https://example.com 링크 목록 수집해줘`
- 시스템 점검: `내 PC 상태 보고서 저장해줘`

### 테마 커스터마이징

설정창 **장치/UI 탭 → 팔레트 직접 편집**에서 색상을 바꾸고 커스텀 테마로 저장할 수 있습니다.
`%AppData%\Ari\theme` 폴더의 JSON 파일을 직접 편집하는 방법도 지원합니다.
자세한 내용은 [테마 커스터마이징 가이드](docs/THEME_CUSTOMIZATION.md)를 확인하세요.

### 사용자 플러그인

`%AppData%\Ari\plugins` 폴더에 Python 파일을 추가하면 앱 시작 시 자동 로드됩니다.
플러그인에서 사용할 수 있는 훅:

| 훅 | 설명 |
|----|------|
| `context.register_menu_action(label, callback)` | 트레이 메뉴에 항목 추가 |
| `context.register_command(BaseCommand)` | 음성 명령 동적 등록 |
| `context.register_tool(schema, handler)` | LLM tool calling 확장 |
| `context.run_sandboxed(code, timeout=15)` | 서브프로세스 격리 실행 |

`PLUGIN_INFO["api_version"] = "1.0"` 선언 필수. 자세한 내용은 [플러그인 가이드](docs/PLUGIN_GUIDE.md)를 확인하세요.

---

## 아키텍처

```
Main.py                     ← Qt 앱 진입점
│
├── commands/               ← 커맨드 패턴 기반 도구 (BaseCommand 구현체)
│   └── ai_command.py       ← LLM 대화 · Tool Calling · 에이전트 루프 진입점
│
├── core/                   ← 앱 런타임 핵심 로직
│   ├── VoiceCommand.py     ← 음성 인식-판단-실행 오케스트레이션
│   ├── config_manager.py   ← 설정 로드/저장
│   ├── plugin_loader.py    ← 플러그인 로더 (API 버전·훅 등록)
│   ├── plugin_sandbox.py   ← 서브프로세스 샌드박스 실행기
│   └── resource_manager.py ← 리소스 경로 관리
│
├── agent/                  ← 자율 실행 핵심 구현
│   ├── agent_orchestrator.py  ← Plan → Execute+Self-Fix → Verify 루프
│   ├── agent_planner.py       ← 목표 분해 · 템플릿 계획 · DAG 주석
│   ├── dag_builder.py         ← 리소스 충돌 기반 의존성 DAG + 병렬 그룹
│   ├── autonomous_executor.py ← Python/Shell 실행기
│   ├── real_verifier.py       ← 휴리스틱→OCR→코드→LLM 4단계 검증
│   ├── ocr_helper.py          ← easyocr/pytesseract 화면 텍스트 추출
│   ├── embedder.py            ← sentence-transformers / API / 해시 임베딩
│   ├── strategy_memory.py     ← 전략 기억 저장·3단계 유사도 검색
│   ├── llm_provider.py        ← 다중 LLM 제공자 (역할별 클라이언트 분리)
│   ├── safety_checker.py      ← 코드/명령 위험 수준 분류
│   └── automation_helpers.py  ← GUI / 브라우저 / 앱 자동화 헬퍼
│
├── services/               ← 외부 서비스 연동
│   ├── web_tools.py        ← 웹 검색 · fetch · SmartBrowser (DOM 재계획 포함)
│   └── dom_analyser.py     ← Selenium DOM 상태 분석 · 다음 액션 제안
│
├── memory/                 ← 대화 이력 및 사용자 기억
│   ├── user_context.py     ← FACT/BIO/PREF 저장 (출처별 신뢰도 decay)
│   ├── trust_engine.py     ← FACT 신뢰도 업데이트 엔진
│   └── memory_manager.py   ← 기억 추출 · 태그 파싱
│
├── ui/                     ← PySide6 UI
│   ├── settings_dialog.py  ← 4탭 설정창
│   ├── theme_editor.py     ← 팔레트 색상 피커 · JSON 편집 위젯
│   ├── theme.py            ← 테마 프리셋 로더
│   └── character_widget.py ← 캐릭터 위젯/애니메이션
│
└── tts/                    ← TTS 제공자
    ├── cosyvoice_tts.py    ← CosyVoice3 로컬 TTS
    └── ...
```

### 자율 실행 흐름

```
사용자 요청
     │
     ▼
 LLM (chat_with_tools)
     │
     ├── 단순 도구 호출 (타이머, 날씨 등) ──────────────────────► 즉시 실행
     │
     └── run_agent_task (다단계 목표)
              │
              ▼
         AgentOrchestrator.run()
              │
              ├── [1] AgentPlanner.decompose()
              │       └── DAG 분석 → 병렬 그룹 계산
              ├── [2] 각 단계 실행 (같은 그룹은 ThreadPool 병렬)
              │       └── 실패 시 LLM 자동 수정 후 재시도
              └── [3] RealVerifier.verify()
                      └── 휴리스틱 → OCR → 코드 → LLM
```

### 개발용 검증

```bash
py -3.11 VoiceCommand/validate_repo.py
py -3.11 VoiceCommand/validate_repo.py --compile-only
py -3 -m unittest discover -s VoiceCommand/tests -p "test_*.py"
```

---

## 캐릭터 커스터마이징

`VoiceCommand/images/` 폴더의 PNG 파일을 교체하여 커스터마이징할 수 있습니다.

- **형식**: 배경이 투명한 PNG
- **파일명**: `동작이름번호.png` (예: `idle1.png`, `walk1.png`)
- **동작 종류**: `idle`, `walk`, `drag`, `fall`, `sit`, `surprised`, `sleep`, `climb` 등

> 상세 제작 가이드: [캐릭터 이미지 가이드](docs/CHARACTER_IMAGES.md)

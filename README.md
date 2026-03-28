# Ari (아리) — AI 음성 어시스턴트

> 한국어 음성 인식 기반 데스크탑 AI 어시스턴트.
> Shimeji 스타일 캐릭터 위젯 + 다중 LLM / TTS 제공자 선택 지원.

- 캐릭터 모델 제작 : [자라탕](https://www.pixiv.net/users/78194943)

![preview](https://github.com/user-attachments/assets/fc8de4b7-57ca-4c22-812c-e5dcc7b45cdd)

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| **웨이크워드** | 호출어 음성 입력 대기 — 설정에서 키워드 자유 변경 가능 |
| **음성 인식** | Google STT (온라인) · faster-whisper (오프라인, 설정에서 전환) |
| **AI 대화** | Groq · OpenAI · Anthropic · Mistral · Gemini · OpenRouter · NVIDIA NIM |
| **역할별 LLM** | 기본 대화 / 플래너 / 실행·수정 모델을 제공자별로 분리 설정 |
| **감정 표현** | `(기쁨)` 등 AI 태그 기반 캐릭터 애니메이션 |
| **TTS** | Fish Audio · CosyVoice3(로컬) · OpenAI TTS · ElevenLabs · Edge TTS · 초기화 실패 시 자동 폴백 |
| **캐릭터 위젯** | Shimeji 스타일 드래그·물리 애니메이션 · 우클릭 시 트레이와 동일 메뉴 표시 |
| **스마트 모드** | LLM tool calling으로 타이머·알람·날씨·유튜브·시스템 제어 자동 실행 |
| **복수 타이머** | 이름 붙은 타이머 최대 10개 동시 관리 ("30분 타이머", "파스타 타이머" 등) |
| **예약 작업 UI** | 트레이 메뉴 → 예약 작업 관리 창에서 목록 확인·취소 |
| **자율 실행** | Python/Shell 코드 생성·실행 + LLM 자동 수정(Self-Fix) + DAG 병렬 실행 |
| **에이전트 루프** | Plan → Execute → Verify 3레이어 (최대 4회 재계획) |
| **작업 템플릿** | 폴더 생성, 검색·요약·저장, 시스템 보고서, 파일 이름 변경, 배치 작업 등 |
| **비전 검증** | OCR 화면 텍스트 인식 + 휴리스틱/코드/LLM 4단계 검증 |
| **DOM 재계획** | 브라우저 로그인 후 DOM 분석 → 다음 액션 자동 제안 |
| **기억 시스템** | FACT/BIO/PREF 장기 기억 + 출처별 신뢰도 decay + 대화 주제 자동 추출 |
| **전략 검색** | 임베딩(sentence-transformers)/재랭킹 + 해시 폴백 유사 전략 검색 |
| **테마 편집** | 설정창 내 팔레트 피커 + JSON 직접 편집 + 저장 |
| **안전 검사** | 위험 수준 3단계 분류 + 확인 다이얼로그 (15초 카운트다운) |
| **플러그인 확장** | API 버전 협상·메뉴/명령/도구 동적 등록·핫 리로드·우클릭 메뉴 표시 제어·샌드박스 |
| **빌드 시스템** | Nuitka 기반 EXE (단일 파일 · 폴더 선택) |

---

## 개선 예정

- [x] **음성 인식 오프라인화** — faster-whisper 기반 로컬 STT 옵션 추가 (설정에서 `google` ↔ `whisper` 전환)
- [x] **웨이크워드 커스터마이징** — `wake_words` 설정으로 호출어 자유 변경
- [x] **타이머 복수 지원** — 이름 붙은 타이머 최대 10개 동시 관리
- [x] **예약 작업 UI** — 트레이 메뉴 → "예약 작업 관리" 창 (5초 자동 갱신·취소)
- [x] **플러그인 핫 리로드** — `plugins/` 폴더 변경 감지 시 재시작 없이 자동 적용
- [x] **`_extract_schedule_phrase` 개선** — "반 시간 뒤", "두 시간 뒤" 등 한국어 수사 패턴 추가
- [x] **음성 인식 오류율 개선** — 최소 길이 필터 + 반복 오인식 자동 무시
- [x] **게임 모드 안정화** — Fish Audio 초기화 실패 시 `tts_fallback_provider`로 자동 복원
- [ ] **플러그인 마켓플레이스** — 파일 수동 복사 방식 → 설치·업데이트 시스템

---

## 개발 현황

### 최근 업데이트 (2026-03-29)

- **음성 인식 설정 분리**: 장치 탭에서 STT 관련 설정(엔진, Whisper 옵션, 마이크 감도, 웨이크워드)을 별도 창(`STTSettingsDialog`)으로 분리. Whisper 선택 시 해당 섹션 즉시 표시 + `adjustSize()` 자동 호출.
- **Whisper STT 서브프로세스 격리**: CTranslate2(MKL)와 torch/numpy(MKL)의 DLL 충돌 문제를 `_whisper_worker.py` 별도 프로세스 + stdin/stdout base64 IPC로 해결. `KMP_DUPLICATE_LIB_OK=TRUE` 시작 시 자동 설정.
- **Whisper 워커 중복 생성 방지**: 웨이크워드 감지(`SimpleWakeWord`)와 명령 인식(`VoiceRecognitionThread`) 간 STT 인스턴스 공유로 설정 변경 시 워커가 두 번 생성되는 문제 수정.
- **설정 저장 시 플러그인 중복 로드 제거**: 설정 저장마다 발생하던 플러그인 재로드 및 "중복 도구 등록 거부" 경고 제거.

### 최근 업데이트 (2026-03-28)

- **캐릭터 우클릭 메뉴 통합**: 캐릭터 위젯 우클릭 시 트레이 메뉴와 동일한 메뉴 표시 (플러그인 등록 항목 포함).
- **플러그인 API 확장 — 우클릭 메뉴 제어**: `context.set_character_menu_enabled(False)`로 캐릭터 우클릭 메뉴 억제 가능. 플러그인 언로드 시 자동 복원.
- **오프라인 STT (faster-whisper)**: 설정에서 `stt_provider: "whisper"` 선택 시 로컬 faster-whisper 모델 사용. `tiny` / `small` / `medium` 모델 선택 가능.
- **웨이크워드 커스터마이징**: `wake_words` 설정 키로 호출어 변경 가능 (기본값 `["아리야", "시작"]`).
- **복수 타이머**: 이름 붙은 타이머 최대 10개 동시 관리. "파스타 타이머 10분", "알람 30분" 등 이름 지정 지원.
- **예약 작업 관리 UI**: 트레이 메뉴 → "예약 작업 관리" 창으로 예약된 작업 목록 확인·취소.
- **플러그인 핫 리로드**: `plugins/` 폴더 파일 변경 시 앱 재시작 없이 자동 반영.
- **TTS 초기화 폴백**: 기본 TTS 초기화 실패 시 `tts_fallback_provider` 설정으로 자동 전환.
- **코드 품질 개선**: 스케줄 패턴 정규식 사전 컴파일, STT 반복 오인식 필터 버그 수정, 8비트 오디오 변환 처리 추가.

### 최근 업데이트 (2026-03-27)

- **컴퓨터 재시작 / 종료취소 명령 추가**: "컴퓨터 재시작해줘", "재부팅해줘", "종료 취소해줘" 음성 명령 지원.
- **예약 종료·재시작 직접 라우팅**: LLM이 `schedule_task(goal="컴퓨터 종료")`를 호출할 때 에이전트 루프 대신 `SystemCommand`로 직접 처리.
- **복합 상대시간 파싱 수정**: "1시간 30분 뒤", "2일 6시간 후" 등 복합 표현을 단위별 누산 방식으로 정확히 파싱.
- **타이머 잔여시간 조회**: "타이머 얼마 남았어?", "타이머 확인" 등 남은 시간 TTS 응답 지원.
- **타이머 알람 키워드 추가**: "30분 알람 맞춰줘" 등 "알람" 표현도 직접 처리.
- **타이머 성능 개선**: 1초 폴링 루프 → 단일 `threading.Timer` 방식으로 변경.
- **타이머 복합 시간 지원**: "1분 30초 타이머", "2시간 30분 타이머" 등 복합 표현 정확 파싱.
- **LLM 도구 스키마 완성**: `shutdown_computer` · `list_scheduled_tasks` · `cancel_scheduled_task` 스키마 추가.
- **시간 포맷 자연어화**: "오후 9시 05분" → "오후 9시 5분", "03월 27일" → "3월 27일" 등 한국어 자연스러운 형식으로 통일.
- **자정 시간 표시 수정**: `get_current_time` 도구에서 자정(0시)을 "오전 12시"로 올바르게 표시.
- **종료취소 응답 정확화**: `shutdown /a` 실행 결과 확인 후 TTS 출력.

<details>
<summary>이전 업데이트 보기 (2026-03-23 ~ 2026-03-26)</summary>

**2026-03-26**
- **캐릭터 드래그 버그 수정**: 벽/천장 타기 도중 드래그 시 중력이 적용되지 않던 문제 수정.
- **팔레트 편집 별도 창**: 설정창 내 인라인 팔레트 편집기를 독립 창(`ThemeEditorDialog`)으로 분리.
- **플러그인 API 버전 협상**: `PLUGIN_INFO["api_version"]` 선언 → 비호환 버전 로드 자동 거부.
- **트레이 메뉴 동적 등록**: `context.register_menu_action(label, callback)` 으로 트레이 메뉴에 플러그인 항목 삽입.
- **음성 명령 동적 등록**: `context.register_command(BaseCommand)` 으로 런타임에 명령 추가.
- **LLM 도구 동적 등록**: `context.register_tool(schema, handler)` 으로 tool calling 스키마·핸들러 확장.
- **플러그인 샌드박스**: `context.run_sandboxed(code, timeout)` — 서브프로세스 격리 실행.
- **역할별 LLM 분리**: 기본/플래너/실행 제공자 분리, API 키 검증 UI, NVIDIA NIM 지원.
- **비전 검증 4단계**: 휴리스틱→OCR→코드→LLM 파이프라인.
- **DAG 기반 병렬 실행**: 리소스 충돌 분석, Kahn 알고리즘.
- **전략 기억 임베딩 검색**: cross-encoder 재랭킹, 기억 신뢰도 엔진.

**2026-03-25**
- 자율 실행 엔진 고도화 (Plan → Execute+Self-Fix → Verify, adaptive/resilient workflow)
- 파일 작업군 확장 (이름 변경, 병합, 폴더 정리, CSV/JSON 분석, 로그 리포트)
- GUI/브라우저 자동화 강화 (페이지별 셀렉터 전략 축적, 다운로드 대기)
- 기억/전략 계층 강화 (FACT 충돌 이력, 해시 기반 유사 전략 검색, 주제 기반 선제 제안)
- 테마/플러그인 확장 (`%AppData%\Ari\theme` JSON 테마, hot-swap)
- TTS 안정화 (CosyVoice3 cudnn.benchmark, 동적 ODE 스텝)

**2026-03-23**
- FACT 신뢰도 기초 (TTL, 충돌 이력, BIO/주제/명령 크기 제한)
- 선택적 병렬 실행 (read-only 단계 제한)
- 실패 분류형 전략 기억 + 의미 유사 전략 검색
- 텍스트 UI `기억 상태` 패널, 에이전트-캐릭터 감정 연동

</details>

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
git clone https://github.com/DO0OG/Ari-VoiceCommand.git
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

```bash
# 오프라인 STT (설정에서 stt_provider: "whisper" 선택 시 필요)
pip install faster-whisper

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

트레이 아이콘 우클릭(또는 캐릭터 우클릭) → **설정** 에서 4개의 탭으로 관리합니다.

1. **RP 설정**: 캐릭터 성격·시나리오·시스템 프롬프트·기억 지침
2. **AI & TTS 설정**: 기본/플래너/실행 모델 및 제공자, API 키 검증, TTS 엔진
3. **장치/UI 설정**: 마이크 선택, **음성 인식 설정** (별도 창 — STT 엔진 전환, Whisper 모델, 마이크 감도, 웨이크워드), 테마 프리셋, 글꼴 배율, **팔레트 직접 편집**
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
| `context.register_menu_action(label, callback)` | 트레이·캐릭터 우클릭 메뉴에 항목 추가 |
| `context.register_command(BaseCommand)` | 음성 명령 동적 등록 |
| `context.register_tool(schema, handler)` | LLM tool calling 확장 |
| `context.run_sandboxed(code, timeout=15)` | 서브프로세스 격리 실행 |
| `context.set_character_menu_enabled(bool)` | 캐릭터 우클릭 메뉴 표시 여부 제어 |
| `context.character_widget` | 캐릭터 위젯 직접 접근 (`.say()`, `.set_emotion()`) |

`PLUGIN_INFO["api_version"] = "1.0"` 선언 필수. 플러그인 변경 사항은 앱 재시작 없이 자동 반영됩니다. 자세한 내용은 [플러그인 가이드](docs/PLUGIN_GUIDE.md)를 확인하세요.

---

## 캐릭터 커스터마이징

`VoiceCommand/images/` 폴더의 PNG 파일을 교체하여 커스터마이징할 수 있습니다.

- **형식**: 배경이 투명한 PNG
- **파일명**: `동작이름번호.png` (예: `idle1.png`, `walk1.png`)
- **동작 종류**: `idle`, `walk`, `drag`, `fall`, `sit`, `surprised`, `sleep`, `climb` 등

> 상세 제작 가이드: [캐릭터 이미지 가이드](docs/CHARACTER_IMAGES.md)


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
│   ├── stt_provider.py     ← STT 백엔드 추상화 (Google / faster-whisper)
│   ├── plugin_loader.py    ← 플러그인 로더 (API 버전·훅 등록·핫 리로드)
│   ├── plugin_watcher.py   ← plugins/ 폴더 감시 → 자동 핫 리로드
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
│   ├── dom_analyser.py     ← Selenium DOM 상태 분석 · 다음 액션 제안
│   └── timer_manager.py    ← 복수 타이머 관리 (이름 지정·최대 10개)
│
├── memory/                 ← 대화 이력 및 사용자 기억
│   ├── user_context.py     ← FACT/BIO/PREF 저장 (출처별 신뢰도 decay)
│   ├── trust_engine.py     ← FACT 신뢰도 업데이트 엔진
│   └── memory_manager.py   ← 기억 추출 · 태그 파싱
│
├── ui/                     ← PySide6 UI
│   ├── settings_dialog.py       ← 4탭 설정창
│   ├── stt_settings_dialog.py   ← 음성 인식 설정 별도 창 (STT 엔진·Whisper·감도·웨이크워드)
│   ├── theme_editor.py          ← 팔레트 색상 피커 · JSON 편집 위젯
│   ├── theme.py                 ← 테마 프리셋 로더
│   ├── character_widget.py      ← 캐릭터 위젯/애니메이션 (우클릭 = 트레이 메뉴 공유)
│   └── scheduled_tasks_dialog.py ← 예약 작업 목록·취소 UI
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
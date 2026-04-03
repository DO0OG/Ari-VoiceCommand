# Ari (아리) — AI 음성 어시스턴트

> 한국어 음성 인식 기반 데스크탑 AI 어시스턴트.
> Shimeji 스타일 캐릭터 위젯 + 다중 LLM / TTS 제공자 선택 지원.
> 사용할수록 사용자 패턴을 학습하고 스스로 개선하는 자기개선 루프 탑재.

- 캐릭터 모델 제작 : [자라탕](https://www.pixiv.net/users/78194943)

![preview](https://github.com/user-attachments/assets/fc8de4b7-57ca-4c22-812c-e5dcc7b45cdd)

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| **웨이크워드** | 호출어 음성 입력 대기 — 설정에서 키워드 자유 변경 가능 |
| **음성 인식** | Google STT (온라인) · faster-whisper (오프라인, 설정에서 전환) |
| **AI 대화** | Groq · OpenAI · Anthropic · Mistral · Gemini · OpenRouter · NVIDIA NIM · **Ollama (로컬 LLM)** |
| **역할별 LLM** | 기본 대화 / 플래너 / 실행·수정 모델을 제공자별로 분리 설정 |
| **LLM 자동 라우팅** | 작업 유형(코드/계획/분석/채팅)에 따라 최적 모델 자동 선택 |
| **감정 표현** | `(기쁨)` 등 AI 태그 기반 캐릭터 애니메이션 |
| **TTS** | Fish Audio · CosyVoice3(로컬) · OpenAI TTS · ElevenLabs · Edge TTS · 초기화 실패 시 자동 폴백 |
| **로컬 설치 UI** | 설정창 `AI & TTS` 탭 상단 `로컬 설치` 섹션에서 Ollama / CosyVoice3 설치와 초기 모델 다운로드 지원 |
| **스트리밍 응답** | 문장 단위 청크 → TTS 즉시 시작, 체감 응답속도 대폭 개선 |
| **캐릭터 위젯** | Shimeji 스타일 드래그·물리 애니메이션 · 우클릭 시 트레이와 동일 메뉴 표시 |
| **스마트 모드** | LLM tool calling으로 타이머·알람·날씨·유튜브·시스템 제어 자동 실행 |
| **복수 타이머** | 이름 붙은 타이머 최대 10개 동시 관리 ("30분 타이머", "파스타 타이머" 등) |
| **예약 작업** | 자연어 스케줄 표현으로 반복 작업 등록 · UI 패널에서 관리 · 놓친 작업 자동 보충 실행 |
| **자율 실행** | Python/Shell 코드 생성·실행 + LLM 자동 수정(Self-Fix) + DAG 병렬 실행 + 패키지 자동 설치 |
| **워크스페이스 감사** | 열린 창 제목을 브라우저/일반 앱으로 분류해 markdown 리포트 생성, 기존 보고서 자동 백업 덮어쓰기 |
| **에이전트 루프** | Plan → Execute → Verify 3레이어 (최대 4회 재계획) |
| **실행 정책 엔진** | 현재 상태·학습 전략·창/도메인 일치도를 점수화해 adaptive/learned/fallback 플랜 추천 |
| **스킬 라이브러리** | 동일 유형 3회 성공 → 스킬 자동 추출 · 재사용 (LLM 계획 없이 즉시 실행) |
| **스킬 자기수정** | 실패 시 LLM이 스텝 재작성(D1) · 5회 성공 시 Python 함수로 컴파일(D2) · 컴파일 코드 실패 시 LLM 자동 수정 |
| **패키지 자동 설치** | 실행 중 ModuleNotFoundError → 안전 패키지 자동 pip install · 미확인 패키지는 사용자 동의 후 설치 |
| **자기반성** | 실패 시 9가지 근본 원인(timeout/permission/missing_module 등)별 차별화된 회피 패턴·수정 제안 자동 분석 |
| **Few-shot 주입** | 성공 사례를 플래너 프롬프트에 자동 삽입 → 정확도 향상 |
| **비전 검증** | OCR 화면 텍스트 인식 + 휴리스틱/코드/LLM 4단계 검증 |
| **DOM 재계획** | 브라우저 로그인 후 DOM 분석 → 다음 액션 자동 제안 |
| **상태 전이 추적** | 단계별 상태 전후 비교(active window / URL / 새 파일 / 새 창) 기록 |
| **복구 가이드** | 저장 덮어쓰기 시 자동 백업 · 복구 후보 탐색 · 최근 유사 실패 에피소드 기반 복구 힌트 |
| **사용자 프로파일** | 전문 분야·응답 선호·활동 시간대 자동 학습 → 시스템 프롬프트 자동 반영 |
| **기억 시스템** | FACT/BIO/PREF 장기 기억 + 출처별 신뢰도 decay + SQLite FTS5 전문 검색 |
| **대화 요약** | 20턴 초과 시 오래된 대화 자동 압축 요약 (슬라이딩 윈도우) |
| **응답 캐싱** | 동일 질문 반복 시 API 호출 없이 캐시 응답 (TTL 10분) |
| **오프라인 폴백** | API 연결 실패 시 오프라인 응답 + 기본 명령 계속 사용 가능 |
| **메모리 정리** | 저신뢰 FACT 자동 제거 · 오래된 대화 요약 압축 · 중복 전략 병합 |
| **주간 리포트** | 매주 월요일 자동 성공률·신규 스킬·자주 실패한 작업 리포트 (선택) |
| **학습 계측** | `LearningMetrics` lift 분석 + `RegressionGuard` 주간 성공률 하락 경고 |
| **음성 메모리 명령** | "내 스킬 목록 보여줘", "저번에 내가 뭐라고 했어?" 등 6종 |
| **전략 검색** | 임베딩(sentence-transformers)/재랭킹 + 해시 폴백 유사 전략 검색 |
| **테마 편집** | 설정창 내 팔레트 피커 + JSON 직접 편집 + 저장 |
| **안전 검사** | 위험 수준 3단계 분류 + 확인 다이얼로그 (15초 카운트다운) |
| **플러그인 확장** | API 버전 협상·메뉴/명령/도구 동적 등록·핫 리로드·우클릭 메뉴 표시 제어·샌드박스 |
| **마켓플레이스** | 플러그인 업로드·심사·다운로드 웹 마켓플레이스 |
| **빌드 시스템** | Nuitka 기반 EXE (단일 파일 · 폴더 선택) |

---

## 개발 현황

- 현재 기준 핵심 변화: Codacy/보안 경고 정리, 플러그인 샌드박스 `multiprocessing` 격리, `validate_repo.py` 표준 라이브러리 검증 루프, `SkillOptimizer` 기반 스킬 자기수정/컴파일, `ddgs` 우선 검색 클라이언트 반영.
- 런타임 상태는 개발 모드에서 `VoiceCommand/.ari_runtime/`, 배포 모드에서 `%AppData%/Ari/`로 분리되어 저장됩니다. 루트 `ari_settings.json`과 `scheduled_tasks.json`은 템플릿 기준선만 유지합니다.
- `validate_repo.py`는 이제 compile + unittest 외에 `clean environment runtime`, `marketplace sha256 contract` smoke까지 함께 확인합니다.
- `workspace audit` 템플릿은 열린 창 제목을 브라우저 서비스/일반 앱 유형으로 분류하고, 브라우저 판별 규칙(브라우저명 경계 매칭)과 탭 추정 규칙(`외/및 N개 탭` + 프로세스 단서)을 함께 사용하도록 보강되었습니다.
- 마켓플레이스 함수는 `market/supabase/functions/*`를 실제 수정했을 때만 `supabase functions deploy ...` 재배포가 필요합니다.

## 자율실행 성공률과 자가학습 진행도

아래 표는 **검증기(`RealVerifier`)를 통과해 목표 달성으로 판정된 비율**을 기준으로 한 운영 가이드입니다. 절대값 보장표가 아니라, 같은 PC 환경에서 반복 가능한 데스크톱/브라우저 작업을 누적 실행했을 때 기대할 수 있는 **대략적인 구간**으로 봐 주세요.

- 단순 파일/앱 제어는 상단 범위에 가깝게 수렴합니다.
- 로그인, CAPTCHA, 동적 DOM, 사이트 정책 변화가 큰 웹 자동화는 하단 범위로 흔들릴 수 있습니다.
- 성공률보다 더 중요한 지표는 “같은 실패를 반복하지 않는가”, “더 빨라지고 있는가”, “컴파일 스킬이 늘고 있는가”입니다.

| 누적 실행 수 | 예상 성공률(반복 가능한 작업 기준) | 학습 상태 |
|------|------|------|
| **0~50회** | 파일/앱 제어 `55~75%`, 브라우저/GUI `35~60%` | 아직 탐색 단계입니다. `StrategyMemory`와 `EpisodeMemory` 샘플이 적어서 `GoalPredictor`는 조용한 편이고, `PlannerFeedback` 힌트도 약합니다. 대신 실패 원인 분류(`ReflectionEngine`)와 상태 전이 기록이 빠르게 쌓이기 시작합니다. |
| **50~200회** | 파일/앱 제어 `70~88%`, 안정된 브라우저 흐름 `50~75%` | 같은 유형의 성공 패턴이 누적되면서 `FewShotInjector`, `PlannerFeedbackLoop`, `GoalPredictor`가 의미 있게 작동하기 시작합니다. 검증된 반복 작업은 스킬로 추출되고, 5회 이상 검증된 스킬은 Python 함수로 컴파일되어 LLM 계획 없이 바로 실행될 수 있습니다. 이 시점부터 주간 리포트와 회귀 경고의 신뢰도도 올라갑니다. |
| **200회+** | 파일/앱 제어 `85~95%`, 혼합 GUI/브라우저 `65~85%` | 반복성이 높은 작업은 “계획 생성”보다 “학습된 전략 재사용” 비중이 커집니다. `SkillLibrary`와 컴파일 스킬, 유사 실패 회피 패턴, 예약 작업 학습 연결이 누적되어 복구 속도도 빨라집니다. 장기적으로는 `LearningMetrics`의 lift와 `RegressionGuard` 경고를 함께 보면서 성능 하락을 잡는 운영 단계에 들어갑니다. |

### 단계별로 실제로 달라지는 것

1. **초반 0~50회**
핵심 목표는 “정답을 빨리 내는 것”보다 “실패를 구조화해서 남기는 것”입니다. 이 구간에서는 계획이 다소 길고 보수적일 수 있으며, 새 사이트나 새 앱에서는 재계획 횟수가 늘어나는 편입니다.

2. **중반 50~200회**
비슷한 목표를 다시 받을 때 플래너가 더 짧고 정확한 계획을 내기 시작합니다. `GoalPredictor`가 반복 실패 작업을 미리 경고하고, `PlannerFeedbackLoop`가 step type별 성공률을 힌트로 넣어 줍니다. 같은 실패를 덜 반복하는 구간입니다.

3. **장기 200회+**
운영 관점의 개선이 더 크게 느껴집니다. 즉, 단순히 성공률이 오르는 것뿐 아니라 첫 성공까지 걸리는 시간, 실패 후 복구 시간, 같은 목표 재실행 시 지연이 줄어듭니다. 이때는 `WeeklyReport`, `LearningMetrics`, `RegressionGuard`를 같이 보면서 어떤 학습 요소가 실제로 이득을 주는지 판단할 수 있습니다.

### 성공률을 높이는 조건

- 같은 앱/사이트/파일 구조를 반복적으로 다루면 학습 속도가 가장 빠릅니다.
- 저장/이동/보고서/반복 웹 작업처럼 패턴이 있는 목표가 스킬화에 유리합니다.
- 설정창에서 플래너/실행 모델을 분리하고, 브라우저 자동화에는 안정적인 모델을 쓰면 중반 이후 상승 폭이 더 커집니다.
- 주기적으로 `메모리 정리`, `주간 리포트`, 예약 작업 학습 연결을 유지하면 장기 구간에서 회귀가 줄어듭니다.

### 최근 자율 저장소 작업 안정화 메모 (2026-04-02)

- 저장소 개발 목표는 사용자가 설정한 기본/플래너/실행 3개 모델 범위 안에서만 라우팅하며, `429`/출력 잘림이 발생하면 같은 선택 범위 안에서 재시도·이어받기·대체 모델 폴백을 시도합니다.
- 저장소 작업 보고서는 실행 사용자 기준 Desktop `Ari Reports`에 저장하고, CI 전용/특정 사용자 절대 경로에 의존하지 않도록 정리했습니다.
- 개발 플래너/오케스트레이터는 `VoiceCommand/{agent,core,ui,plugins,tests}` + `docs` 범위 밖 경로 선택, `py_compile`만으로 끝내는 약한 검증, `tests/` 루트 경로, 가짜 성공/OCR 기반 성공 판정을 거부하도록 강화했습니다.
- `validate_repo.py --compile-only`는 `__pycache__` 대신 임시 위치로 컴파일해 로컬 환경 락/권한 문제에도 더 안정적으로 동작합니다.
- **핵심 버그 수정**: `_execute_plan`에서 step 출력을 300자로 자르던 문제를 개발 목표 시 2000자로 확장. 이로 인해 bootstrap의 repo scan(~1900자)·테스트 목록(~800자) JSON이 잘려 LLM이 저장소 구조를 파악하지 못하던 근본 원인 해결. 현재 전체 테스트는 268개 기준으로 유지 중입니다.
- **영향 테스트 자동 선별**: `_infer_relevant_tests`가 goal에서 `.py` 파일명을 추출해 관련 테스트를 `relevant=` 항목으로 LLM에게 우선 제시. 테스트 목록도 첫 5개 샘플 대신 전체 목록(`all=`) 표시로 전환.
- **에피소드 메모리 정리**: `prune_old_failures(max_age_days=30)`으로 30일 이상 된 실패 에피소드를 실행 후 자동 정리. `.gitignore`에 런타임 산출물(`ari_memory.db`, `episode_memory.json` 등)과 개발용 `.ari_runtime/` 디렉터리를 추가.

<details>
<summary>최근 업데이트 자세히 보기 (2026-03-29 ~ 2026-03-31)</summary>

### 최근 업데이트 (2026-03-31) — 품질/보안 정리 + 스킬 코드 자기수정

- **Codacy 대응 정리**: React 비동기 핸들러/nullable 경고 정리, non-null assertion 제거, 불필요 optional chaining 제거.
- **보안 강화**: 마켓플레이스 클라이언트 URL 검증 강화, 플러그인 샌드박스 `multiprocessing` 격리 전환, 검증 스크립트의 subprocess 제거, GitHub Action 릴리스 단계 SHA pin 적용.
- **설정창 로컬 설치 UI**: `AI & TTS` 탭 상단에 `로컬 설치` 섹션 추가. Ollama 설치/모델 다운로드, CosyVoice3 설치를 설정창에서 바로 진행 가능.
- **설정창 마켓플레이스 연동**: `확장` 탭에서 플러그인 검색·설치가 가능해졌고, 설치 후 로컬 플러그인 목록과 연동됩니다.
- **ZIP 플러그인 설치/로드 전환**: 마켓플레이스 플러그인을 `.py` 추출 대신 ZIP 그대로 설치하고, 로더가 `plugin.json`의 `entry`를 읽어 `.py`/`.zip` 모두 핫리로드하도록 변경. 재로드 시 메뉴/도구 중복 등록도 정리.
- **의존성 업데이트**: `Pillow>=12.1.1`, `requests>=2.33.0`, `certifi>=2024.7.4`, `ddgs>=8.0.0`.
- **마켓플레이스 함수 변경**: `upload-plugin`, `notify-developer` 함수 검증 로직 및 스캐너 친화적 패턴으로 정리. 함수 코드 변경 시 `supabase functions deploy` 재실행 필요.
- **스킬 Step 재작성 (Direction 1)**: `SkillOptimizer.optimize_steps()` — 스킬 실패 2회 시 LLM이 실패 에러를 분석해 JSON 스텝 시퀀스를 자동 수정. `condense_steps()` — 8회 성공 후 불필요 스텝 제거·압축.
- **Python 코드 컴파일 (Direction 2)**: `SkillOptimizer.compile_to_python()` — 5회 성공한 검증된 스킬을 단일 `run_skill()` Python 함수로 컴파일, `compiled_skills/` 저장. 이후 실행 시 LLM 계획 없이 Python 직접 호출.
- **컴파일 코드 자동 수정**: 컴파일 스킬 실패 시 `repair_python()` — LLM이 코드를 읽고 수정해 덮어씀.
- **실행 우선순위**: 컴파일 스킬 → JSON 스텝 스킬 → 전체 에이전트 루프 순으로 폴백.
- **안전 검사**: `safety_checker.check_python()` 통과한 코드만 저장·실행. AST 파싱 검증 포함.
- **비동기 처리**: 모든 자기수정은 daemon 스레드 백그라운드 실행 (메인 루프 블로킹 없음).
- **자율성 10점 단계 보강**: 상태 전이 기록(`state_delta_summary`), 실행 정책 점수화(`execution_policy`), 목표 에피소드 기억(`episode_memory`), 문서 덮어쓰기 자동 백업/복구 후보 추천(`restore_last_backup`, `get_recovery_guidance`)을 추가해 재계획·검증·복구 루프를 통합.

### 최근 업데이트 (2026-03-30) — AI 자기개선 루프 완성

- **대화 품질 개선**: `_filter_korean_text` 버그 수정 → `_clean_response` 교체. `include_context=True` 기본값 변경. 모델 하드코딩 제거 (설정 연동).
- **스트리밍 응답**: `stream=True` + 문장 단위 청크 → TTS 즉시 시작. 체감 응답속도 대폭 개선.
- **응답 캐싱**: `ResponseCache` (TTL 10분, 최근 50개) — 동일 질문 반복 시 API 호출 0회.
- **오프라인 폴백**: API 연결 실패 시 `_offline_response` 반환. 기본 명령(타이머·볼륨 등) 계속 사용 가능.
- **대화 슬라이딩 요약**: 20턴 초과 시 오래된 5개 대화를 LLM 요약 압축. 최대 5개 요약 보관. 컨텍스트 품질 유지.
- **캐릭터 감정 자동 생성**: RPGenerator `build_system_prompt()` 실제 구현 — LLM이 `(기쁨)`, `(걱정)` 등 감정 태그 자동 생성 → 기존 캐릭터 애니메이션 파이프라인 자동 연동.
- **사용자 프로파일 엔진**: `UserProfileEngine` — 전문 분야 점수(신뢰도 기반), 활동 시간대, 응답 선호 스타일 추론. 시스템 프롬프트 자동 반영.
- **SQLite FTS5 메모리 검색**: `MemoryIndex` — "저번에 내가 말한 거 기억해?" 같은 자연어 검색 지원. BM25 스코어링.
- **신뢰도 엔진 확장**: `batch_decay()` (앱 시작 시 전체 fact 일괄 감쇠), `update_source_weight()` (잘못된 출처 자동 가중치 하향).
- **Ollama 로컬 LLM**: `agent/llm_provider.py` + 설정 UI — 인터넷 불필요, API 비용 없음. `ollama pull llama3.2` 후 설정에서 선택.
- **LLM 자동 라우팅**: `LLMRouter` — 코드/복잡한 계획/긴 분석/단순 채팅 4종 자동 분류 → 최적 모델 선택.
- **Few-shot 주입**: `FewShotInjector` — StrategyMemory 성공 사례 → 플래너 프롬프트 자동 삽입. 사용할수록 정확도 향상.
- **플래너 피드백 루프**: `PlannerFeedbackLoop` — step_type별 성공률 통계 → 플래너 힌트 자동 주입.
- **스킬 라이브러리**: `SkillLibrary` — 동일 태그 3회 성공·5단계 이하 → 스킬 자동 추출. 재사용 시 LLM 계획 없이 즉시 실행. 연속 실패 2회 자동 비활성화.
- **구조화된 자기반성**: `ReflectionEngine` — 실패 시 L1(오류 분류)→L2(구조적 원인)→L3(LLM 교훈·수정 제안)→L4(반복 실수 감지) 4레이어 분석.
- **메모리 통합 정리**: `MemoryConsolidator` — 저신뢰 FACT 제거, 14일+ 대화 요약 압축, 성공 패턴 스킬 승격. 프로세스 블로킹 없이 별도 스레드 실행.
- **놓친 작업 자동 보충**: `check_missed_tasks_on_startup()` — PC 꺼져 있던 시간에 예약된 반복 작업 앱 시작 시 자동 보충 실행.
- **주간 자기개선 리포트**: `WeeklyReport` — 성공률·신규 스킬·자주 실패한 작업 종합. `ProactiveScheduler`에 매주 월요일 9시 자동 등록 (선택).
- **음성 메모리 명령**: `MemoryCommand` — 6종 음성 명령 ("내 스킬 목록 보여줘", "메모리 정리해줘" 등).
- **스케줄러 통합**: `AriScheduler`(구) + `ProactiveScheduler` 통합. 단일 스케줄러로 UI 패널·LLM 도구·놓친 작업 보충 모두 처리.

### 최근 업데이트 (2026-03-29)

- **음성 인식 설정 분리**: 장치 탭에서 STT 관련 설정을 별도 창(`STTSettingsDialog`)으로 분리.
- **Whisper STT 서브프로세스 격리**: CTranslate2(MKL)와 torch/numpy(MKL) DLL 충돌 해결.
- **Whisper 워커 중복 생성 방지**: 웨이크워드 감지·명령 인식 간 STT 인스턴스 공유.
- **설정 저장 시 플러그인 중복 로드 제거**.

</details>

<details>
<summary>이전 업데이트 보기 (2026-03-23 ~ 2026-03-28)</summary>

**2026-03-28**
- 캐릭터 우클릭 메뉴 통합, 플러그인 API 확장(우클릭 메뉴 제어), 오프라인 STT(faster-whisper), 웨이크워드 커스터마이징, 복수 타이머, 예약 작업 관리 UI, 플러그인 핫 리로드, TTS 초기화 폴백.

**2026-03-27**
- 컴퓨터 재시작/종료취소 명령, 예약 종료 직접 라우팅, 복합 상대시간 파싱, 타이머 잔여시간 조회, LLM 도구 스키마 완성.

**2026-03-26**
- 캐릭터 드래그 버그 수정, 팔레트 편집 별도 창, 플러그인 API 버전 협상, 역할별 LLM 분리, 비전 검증 4단계, DAG 기반 병렬 실행.

**2026-03-25**
- 자율 실행 엔진 고도화, 파일 작업군 확장, 기억/전략 계층 강화, 테마/플러그인 확장.

**2026-03-23**
- FACT 신뢰도 기초, 선택적 병렬 실행, 실패 분류형 전략 기억, 텍스트 UI 기억 패널.

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
| RAM | 4 GB | 8 GB+ |
| GPU (로컬 TTS / Ollama) | — | CUDA 12.x, VRAM 4 GB+ |

### 설치

```bash
# 1. 저장소 클론
git clone https://github.com/DO0OG/Ari-VoiceCommand.git
cd Ari-VoiceCommand

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

# 빠른 문법 검사만
py -3.11 validate_repo.py --compile-only
```

개발 모드에서 생성되는 설정/메모리/스케줄 상태는 `VoiceCommand/.ari_runtime/`에 저장됩니다.

### 선택 의존성

```bash
# 오프라인 STT (설정에서 stt_provider: "whisper" 선택 시 필요)
pip install faster-whisper

# OCR (화면 텍스트 인식 — 에이전트 비전 검증)
pip install easyocr          # 권장, 한국어 지원
# pip install pytesseract    # 경량, Tesseract 별도 설치 필요

# 의미 기반 전략 검색 + Few-shot 임베딩 (미설치 시 해시 폴백 자동 사용)
pip install sentence-transformers torch

# Edge TTS (무료 TTS, 인터넷 필요)
pip install edge-tts

# ElevenLabs TTS
pip install elevenlabs
```

### Ollama 로컬 LLM 설치 (선택)

인터넷 없이, API 비용 없이 로컬에서 LLM 실행:

```bash
# 1. 설정창 → AI & TTS → 로컬 설치 → "Ollama 설치/모델 받기"
#    또는 https://ollama.com 에서 Ollama 직접 설치

# 2. 원하는 모델 다운로드
ollama pull llama3.2        # 4GB, 범용
ollama pull qwen2.5         # 5GB, 한국어 강함 (권장)
ollama pull gemma3          # 5GB, 경량
ollama pull qwen2.5:14b     # 9GB, 고성능

# 3. Ari 설정 → AI & TTS → LLM 제공자 → "Ollama (로컬 LLM)" 선택
# 4. 모델명 입력 (예: qwen2.5)
# 5. 연결 테스트
```

권장 사양: RAM 8GB+, 모델에 따라 VRAM 필요.

스크립트로 설치하려면:

```bash
py -3.11 VoiceCommand/install_ollama.py
py -3.11 VoiceCommand/install_ollama.py --models llama3.2:3b qwen3:4b
```

### 마켓플레이스 함수 재배포가 필요한 경우

- `market/supabase/functions/*` 내부 파일을 수정했을 때
- Edge Function용 shared helper 또는 secret 의존 구성이 바뀌었을 때

예시:

```bash
cd market
supabase functions deploy upload-plugin --project-ref <프로젝트ID> --no-verify-jwt
supabase functions deploy notify-developer --project-ref <프로젝트ID> --no-verify-jwt
```

### CosyVoice3 로컬 TTS 설치 (선택)

```bash
# 설정창 → AI & TTS → 로컬 설치 → "CosyVoice 설치"

# 대화형 경로 입력
py -3.11 VoiceCommand/install_cosyvoice.py

# 경로 직접 지정
py -3.11 VoiceCommand/install_cosyvoice.py --dir "D:\MyApps\CosyVoice"
```

설치 후: 설정 → **AI & TTS → TTS 모드 → 로컬 (CosyVoice3)** 선택.

---

## 설정

트레이 아이콘 우클릭(또는 캐릭터 우클릭) → **설정** 에서 4개의 탭으로 관리합니다.

1. **RP 설정**: 캐릭터 성격·시나리오·시스템 프롬프트·기억 지침
2. **AI & TTS 설정**: 상단 `로컬 설치` 섹션(Ollama / CosyVoice3 설치), 기본/플래너/실행 모델 및 제공자, API 키 검증, TTS 엔진. Ollama 선택 시 API 키 란 숨김 + 서버 주소 안내.
3. **장치/UI 설정**: 마이크 선택, **음성 인식 설정** (별도 창 — STT 엔진 전환, Whisper 모델, 마이크 감도, 웨이크워드), 테마 프리셋, 팔레트 직접 편집
4. **확장 설정**: 로컬 플러그인 목록 확인 (api_version·로드 상태·오류 표시), 설정창 내 마켓플레이스 검색·설치

### 음성 메모리 명령

| 명령 | 동작 |
|------|------|
| "내가 자주 하는 작업 뭐야?" | 자주 요청하는 작업 유형 TTS 출력 |
| "저번에 내가 뭐라고 했어?" | 대화 기록 FTS 검색 결과 TTS |
| "내 스킬 목록 보여줘" | 자동 추출된 스킬 목록 TTS |
| "이 스킬 삭제해줘" | 첫 번째 스킬 비활성화 |
| "메모리 정리해줘" | MemoryConsolidator 즉시 실행 |
| "나에 대해 뭐 알아?" | 사용자 프로파일 + facts 요약 TTS |

### 사용자 플러그인

`%AppData%\Ari\plugins` 폴더에 Python 파일을 추가하면 앱 시작 시 자동 로드됩니다.

| 훅 | 설명 |
|----|------|
| `context.register_menu_action(label, callback)` | 트레이·캐릭터 우클릭 메뉴에 항목 추가 |
| `context.register_command(BaseCommand)` | 음성 명령 동적 등록 |
| `context.register_tool(schema, handler)` | LLM tool calling 확장 |
| `context.run_sandboxed(code, timeout=15)` | 별도 Python 프로세스 격리 실행 |
| `context.set_character_menu_enabled(bool)` | 캐릭터 우클릭 메뉴 표시 여부 제어 |

`PLUGIN_INFO["api_version"] = "1.0"` 선언 필수. 자세한 내용은 [플러그인 가이드](docs/PLUGIN_GUIDE.md) 참고.

---

## 아키텍처

```
Main.py                     ← Qt 앱 진입점
│
├── commands/               ← 커맨드 패턴 기반 도구 (BaseCommand 구현체)
│   ├── ai_command.py       ← LLM 대화 · Tool Calling · 에이전트 루프 진입점
│   └── memory_command.py   ← 음성 메모리 명령 6종
│
├── core/                   ← 앱 런타임 핵심 로직
│   ├── VoiceCommand.py     ← 음성 인식-판단-실행 오케스트레이션
│   ├── config_manager.py   ← 설정 로드/저장 (RLock + double-checked cache)
│   ├── rp_generator.py     ← 캐릭터 성격·감정 태그 시스템 프롬프트 생성
│   ├── stt_provider.py     ← STT 백엔드 추상화 (Google / faster-whisper)
│   ├── plugin_loader.py    ← 플러그인 로더 (API 버전·훅 등록·핫 리로드)
│   ├── plugin_watcher.py   ← plugins/ 폴더 감시 → 자동 핫 리로드
│   └── plugin_sandbox.py   ← multiprocessing 기반 샌드박스 실행기
│
├── agent/                  ← 자율 실행 + AI 고도화
│   ├── llm_provider.py        ← 다중 LLM 제공자 (Groq/OpenAI/Anthropic/Mistral/Gemini/OpenRouter/NIM/Ollama)
│   ├── llm_router.py          ← 작업 유형별 최적 모델 자동 라우팅
│   ├── agent_orchestrator.py  ← Plan→Execute+Self-Fix→Verify + _post_run_update
│   ├── agent_planner.py       ← 목표 분해 · 템플릿 · DAG · FewShot/Feedback 주입
│   ├── few_shot_injector.py   ← 성공 사례 → 플래너 프롬프트 자동 삽입
│   ├── planner_feedback.py    ← step_type 성공률 통계 → 플래너 힌트
│   ├── skill_library.py       ← 성공 패턴 자동 추출·스킬 재사용·자동 비활성화·자기수정 트리거
│   ├── skill_optimizer.py     ← 스킬 자기수정 엔진 (D1: 스텝 재작성, D2: Python 컴파일·수정)
│   ├── reflection_engine.py   ← 4레이어 실패 자기반성 (분류→원인→교훈→반복감지)
│   ├── strategy_memory.py     ← 전략 기억 (중요도 기반 prune, few_shot_eligible)
│   ├── proactive_scheduler.py ← 예약 작업 · 선제 제안 · 놓친 작업 보충
│   ├── weekly_report.py       ← 주간 자기개선 리포트
│   ├── dag_builder.py         ← 리소스 충돌 기반 의존성 DAG + 병렬 그룹
│   ├── autonomous_executor.py ← Python/Shell 실행기
│   ├── real_verifier.py       ← 휴리스틱→OCR→코드→LLM 4단계 검증
│   ├── embedder.py            ← sentence-transformers / API / 해시 임베딩
│   ├── safety_checker.py      ← 코드/명령 위험 수준 분류
│   └── automation_helpers.py  ← GUI / 브라우저 / 앱 자동화 헬퍼
│
├── memory/                 ← 사용자 기억·학습 시스템
│   ├── conversation_history.py ← 슬라이딩 요약 (MAX_ACTIVE=20, 압축 5개 단위)
│   ├── memory_manager.py       ← 기억 추출 · UserProfileEngine 연동
│   ├── memory_index.py         ← SQLite FTS5 전문 검색 (ResourceManager 경로 분기)
│   ├── memory_consolidator.py  ← 주기적 메모리 정리·압축·스킬 승격
│   ├── user_profile_engine.py  ← 전문 분야·응답 선호·활동 시간대 자동 추론
│   ├── user_context.py         ← FACT/BIO/PREF 저장 (출처별 신뢰도 decay)
│   └── trust_engine.py         ← FACT 신뢰도 업데이트 엔진 (batch_decay 포함)
│
├── services/               ← 외부 서비스 연동
│   ├── web_tools.py        ← 웹 검색 · fetch · SmartBrowser (DOM 재계획 포함)
│   ├── dom_analyser.py     ← Selenium DOM 상태 분석 · 다음 액션 제안
│   └── timer_manager.py    ← 복수 타이머 관리 (이름 지정·최대 10개)
│
├── ui/                     ← PySide6 UI
│   ├── settings_dialog.py       ← 4탭 설정창 (Ollama URL 입력란 포함)
│   ├── scheduler_panel.py       ← 예약 작업 관리 패널 (QTimer 5초 폴링)
│   ├── stt_settings_dialog.py   ← 음성 인식 설정 별도 창
│   ├── theme_editor.py          ← 팔레트 색상 피커 · JSON 편집 위젯
│   └── scheduled_tasks_dialog.py ← 예약 작업 목록·취소 UI
│
└── tts/                    ← TTS 제공자
    ├── cosyvoice_tts.py    ← CosyVoice3 로컬 TTS
    └── ...
```

### 자율 실행 + 자기개선 흐름

```
사용자 요청
     │
     ▼
 LLMProvider (+ ResponseCache · LLMRouter · UserProfile)
     │
     ├── 단순 도구 호출 ──────────────────────────────────► 즉시 실행
     │
     └── run_agent_task (다단계 목표)
              │
              ▼
         AgentOrchestrator.run()
              │
              ├── [0] SkillLibrary.get_applicable_skill()
              │       ├── compiled=True → SkillOptimizer.run_compiled() (Python 직접 실행)
              │       │       └── 실패 시 repair_python() 예약 → JSON 스텝 폴백
              │       └── compiled=False → JSON 스텝 실행 (LLM 계획 생략)
              │
              ├── [1] AgentPlanner.decompose()
              │       ├── FewShotInjector — 유사 성공 사례 프롬프트 주입
              │       ├── PlannerFeedbackLoop — step_type 성공률 힌트 주입
              │       └── DAG 분석 → 병렬 그룹 계산
              │
              ├── [2] 각 단계 실행 (같은 그룹은 ThreadPool 병렬)
              │       └── 실패 시 LLM 자동 수정 후 재시도
              │
              ├── [3] RealVerifier.verify()
              │       └── 휴리스틱 → OCR → 코드 → LLM
              │
              └── [4] _post_run_update()
                      ├── 성공: SkillLibrary.try_extract_skill()
                      │       ├── success_count==5 → SkillOptimizer.compile_to_python() [백그라운드]
                      │       └── success_count==8 → SkillOptimizer.condense_steps() [백그라운드]
                      ├── 실패: ReflectionEngine.reflect() → 다음 플래너에 반영
                      │       └── fail_count>=2 → SkillOptimizer.optimize_steps() [백그라운드]
                      └── PlannerFeedbackLoop.record()
```

### 개발용 검증

```bash
py -3.11 VoiceCommand/validate_repo.py
py -3.11 VoiceCommand/validate_repo.py --compile-only
py -3.11 -m unittest discover -s VoiceCommand/tests -p "test_*.py"
```

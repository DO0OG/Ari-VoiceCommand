# Session Context: Ari Voice Assistant Project

이 파일은 AI 세션(Claude, Gemini 등) 간 프로젝트 상태를 공유하기 위한 문서입니다.
새 세션 시작 시 이 파일을 가장 먼저 제공하세요.

## Last Updated: 2026-04-07
## 상태: UI/TTS 다국어 지원(i18n) 최종 완료 · ko/en/ja 지원 · 301/301 테스트 통과

---

## 1. 프로젝트 개요

"아리(Ari)"는 Windows 전용 다국어(한국어·영어·일본어) 음성 AI 어시스턴트입니다.
- 웨이크워드 "아리야" 감지 → 음성 인식 → 명령 실행 → TTS 응답
- 언어 설정에 따라 UI, 시스템 프롬프트, TTS 음성 자동 전환
- LLM: Groq / OpenAI / Anthropic / Mistral / Gemini / OpenRouter / NVIDIA NIM / **Ollama (로컬)**
- TTS: Fish Audio / CosyVoice3 (로컬) / OpenAI TTS / ElevenLabs / Edge TTS
- UI: PySide6 시스템 트레이 + 캐릭터 애니메이션 (Shimeji 스타일)
- 진입점: `Main.py` → `VoiceCommand.py` → `CommandRegistry` → 각 Command 클래스

### 디렉터리 구조

| 디렉터리 | 내용 |
|----------|------|
| `VoiceCommand/i18n/` | gettext 기반 국제화 번역 엔진 및 로케일 파일 (.po, .mo) |
| `VoiceCommand/agent/` | 자율 실행 엔진 + 자기개선 루프 (LLMRouter, SkillLibrary, ReflectionEngine, PlannerFeedback, FewShot, GoalPredictor, LearningMetrics, RegressionGuard, WeeklyReport) |
| `VoiceCommand/commands/` | BaseCommand 구현체 (priority 기반 디스패치) + MemoryCommand |
| `VoiceCommand/core/` | 앱 런타임 핵심 (AppState, ConfigManager, threads) |
| `VoiceCommand/services/` | 웹 도구, 타이머, DOM 분석 |
| `VoiceCommand/memory/` | FACT/BIO/PREF 기억, 신뢰도 엔진, UserProfileEngine, MemoryIndex, MemoryConsolidator |
| `VoiceCommand/tts/` | TTS 제공자 팩토리 |
| `VoiceCommand/ui/` | PySide6 위젯 (캐릭터, 설정, 테마) |
| `VoiceCommand/audio/` | PyAudio 싱글톤, 웨이크워드 |

---

## 2. 커맨드 우선순위 (priority 낮을수록 먼저 매칭)

| 클래스 | priority | 트리거 |
|--------|----------|--------|
| SystemCommand | 10 | 컴퓨터 종료·재시작·종료취소 |
| LearningCommand | 20 | 학습 모드 (스마트 어시스턴트 자동 승격/패턴 기록 토글) |
| TimerCommand | 30 | 타이머, 알람 |
| MemoryCommand | 45 | 자주 하는 작업, 스킬 목록, 메모리 정리 등 6종 |
| WeatherCommand | 50 | 날씨 |
| VolumeCommand | 50 | 볼륨 |
| TimeCommand | 50 | 몇 시야 |
| YoutubeCommand | 50 | 유튜브 |
| CalculatorCommand | 50 | 계산 |
| AICommand | 100 | 모든 입력 (fallback) |

---

## 3. LLM 도구 목록 (get_available_tools 기준, 2026-03-30)

```
get_screen_status, play_youtube, set_timer, cancel_timer,
get_weather, adjust_volume, get_current_time,
execute_python_code, execute_shell_command, run_agent_task,
web_search, web_fetch, schedule_task,
shutdown_computer, list_scheduled_tasks, cancel_scheduled_task
```
총 16개. 플러그인 도구는 `_plugin_tools`로 동적 추가.

---

## 4. Phase 1-8 핵심 모듈 (2026-04-06 반영)

### agent/ 신규

| 파일 | 클래스·함수 | 역할 |
|------|------------|------|
| `llm_router.py` | `LLMRouter`, `get_llm_router()` | 작업 유형(코드/계획/분석/채팅)별 최적 모델 자동 라우팅 |
| `few_shot_injector.py` | `FewShotInjector`, `get_few_shot_injector()` | 성공 전략 → 플래너 프롬프트 자동 삽입 (MAX_EXAMPLES=3) |
| `skill_library.py` | `SkillLibrary`, `Skill`, `get_skill_library()` | 반복 성공 패턴 자동 추출·재사용·신뢰도 관리·자기수정 트리거 |
| `skill_optimizer.py` | `SkillOptimizer`, `get_skill_optimizer()` | D1: 스텝 재작성, D2: Python 컴파일·수정 |
| `reflection_engine.py` | `ReflectionEngine`, `ReflectionResult`, `get_reflection_engine()` | 실패 4레이어 자기반성 |
| `planner_feedback.py` | `PlannerFeedbackLoop`, `get_planner_feedback_loop()` | step_type별 성공률 통계 → 플래너 힌트 |
| `goal_predictor.py` | `GoalPredictor`, `get_goal_predictor()` | 과거 전략/실패 패턴 기반 위험 경고 |
| `learning_metrics.py` | `LearningMetrics`, `get_learning_metrics()` | 학습 컴포넌트별 lift/활성화 기여도 측정 |
| `regression_guard.py` | `RegressionGuard`, `get_regression_guard()` | 지난 주 대비 성공률 하락 감지 |
| `weekly_report.py` | `WeeklyReport`, `get_weekly_report()` | 주간 자기개선 리포트 생성 |

### memory/ 신규

| 파일 | 클래스·함수 | 역할 |
|------|------------|------|
| `user_profile_engine.py` | `UserProfileEngine`, `UserProfile`, `get_user_profile_engine()` | 전문 분야·응답 선호·활동 시간대 자동 추론 |
| `memory_index.py` | `MemoryIndex`, `MemorySearchResult`, `get_memory_index()` | SQLite FTS5 전문 검색 (ari_memory.db) |
| `memory_consolidator.py` | `MemoryConsolidator`, `get_memory_consolidator()` | 주기적 메모리 정리·압축·전략 병합 |

### commands/ 신규

| 파일 | 클래스 | 역할 |
|------|--------|------|
| `memory_command.py` | `MemoryCommand` (priority=45) | 음성 메모리 명령 6종 |

### 삭제

- `agent/scheduler.py` (AriScheduler) — `agent/proactive_scheduler.py` (ProactiveScheduler)로 완전 통합

---

## 5. 현재 파일별 상태

### `agent/proactive_scheduler.py`
- 단일 스케줄러 (AriScheduler 삭제·통합)
- `add_task(name, goal, schedule_expr)`, `remove_task(task_id)`, `toggle_task(task_id)`, `run_task_now(task_id)`, `check_missed_tasks_on_startup()`
- `schedule_expr` 필드 (구 `schedule_desc` — 로드 시 자동 마이그레이션)
- 기준은 `last_run`이 아니라 `next_run <= now` 이며, 실행 시작 시 `last_run`/`next_run`을 선반영해 missed task를 구조적으로 복구합니다.
- 저장 경로: `ResourceManager.get_writable_path("scheduled_tasks.json")`

### `agent/llm_provider.py`
- Ollama 추가: `api_key="ollama"`, `base_url=ollama_base_url` 설정값 사용
- 도구 16개 정의 완료
- `planner_client`, `execution_client` 역할별 분리
- `ResponseCache`는 `agent/response_cache.py`로 분리되었고 `RLock`으로 보호됩니다. 캐시 키는 질문 원문뿐 아니라 모델/프롬프트 구성을 함께 반영합니다.
- 정적 도구 스키마는 `agent/tool_schemas.py`로 분리되어 플러그인 도구와 합쳐집니다.
- `assistant_text_utils.py`를 통해 AICommand와 공유하는 goal 해석·tool artifact 정리 로직을 재사용합니다.

### `agent/condition_evaluator.py`
- ExecutionEngine step `condition` 평가를 위한 안전 AST 평가 전담 모듈
- 허용 호출: `len`, `str`, `int`, `float`, `bool`, `dict.get()`
- 평가 실패는 상위 `ExecutionEngine._eval_condition()`에서 fail-closed(`False`) 처리

### `agent/agent_orchestrator.py`
- `_post_run_update()`: 성공 시 SkillLibrary 스킬 추출, 실패 시 ReflectionEngine 반성 → StrategyMemory 저장
- PlannerFeedback, UserProfile, MemoryIndex 자동 업데이트
- `_run_with_skill_if_available()`: `skill.compiled=True`면 `_run_compiled_skill()` 우선 실행, 실패 시 JSON 스텝 폴백
- `_run_compiled_skill()`: `SkillOptimizer.run_compiled()` 호출, 실패 에러를 `record_feedback(error=...)` 전달

### `agent/skill_optimizer.py` (신규 2026-03-31)
- Direction 1: `optimize_steps(skill, error)` — 실패 에러 기반 스텝 재작성
- Direction 1: `condense_steps(skill)` — 반복 성공 후 스텝 압축
- Direction 2: `compile_to_python(skill)` — Python 함수로 컴파일 (`ResourceManager.get_writable_path("compiled_skills")/<id>.py`)
- Direction 2: `repair_python(skill, code, error)` — 컴파일 코드 LLM 수정
- 안전: `safety_checker.check_python()` + `ast.parse()` 통과한 코드만 저장

### `agent/agent_planner.py`
- FewShotInjector, PlannerFeedbackLoop 힌트를 시스템 프롬프트에 자동 주입
- JSON 응답 복구와 균형 괄호 추출 로직은 `agent/planner_json_utils.py`로 분리
- 전략/에피소드 메모리 접근 helper를 `_with_strategy_memory`, `_with_episode_memory`로 통일해 중첩 `try/except` 없이 fail-closed 동작 유지

### `core/stt_provider.py`
- `WhisperSTTProvider`는 READY 신호와 전사 응답을 timeout 기반으로 읽고, 워커 hang/종료 시 자동 재시작
- `audio/simple_wake.py`, `core/threads.py`는 같은 설정 서명이어도 unhealthy provider를 감지하면 STT 인스턴스를 재생성
- `audio/simple_wake.py`는 웨이크워드를 정규화된 전체 문구 기준으로 비교해 일반 문장 내부의 `"시작"` 같은 부분 일치 오탐을 줄임
- `core/threads.py`는 TTS 큐에 연속으로 들어온 짧은 응답을 짧은 시간창에서 병합해 문장별 TTS 호출 오버헤드를 줄임

### 싱글톤 팩토리 상태
- `agent_orchestrator`, `agent_planner`, `autonomous_executor`, `embedder`, `llm_provider`, `proactive_scheduler`, `real_verifier`, `skill_library`, `strategy_memory`, `plugin_loader`, `memory_*`, `web_tools` 주요 getter에 생성 락 추가
- `test_singleton_factories.py`로 주요 lock-protected getter의 동시 초기화 회귀를 검증

### `memory/conversation_history.py`
- 슬라이딩 요약: `MAX_ACTIVE=20`, `COMPRESS_UNIT=5`, `MAX_SUMMARIES=5`
- `_summarize_chunk()`는 단순 truncation 대신 문장 경계 우선 요약을 사용하고, 종료 시 `flush()`로 debounce 저장을 강제 반영할 수 있습니다.

### `core/config_manager.py`
- Phase 1-8 기본값: `llm_router_enabled=True`, `few_shot_max_examples`, `skill_library_enabled`, `reflection_engine_enabled`, `memory_consolidation_days`, `weekly_report_enabled`

### `core/resource_manager.py`
- 개발 모드 writable root는 `VoiceCommand/.ari_runtime/`, 배포 모드는 `%AppData%/Ari/`
- 저장소에는 `ari_settings.template.json` 템플릿만 유지하고, 실제 실행 상태와 로그는 `.ari_runtime/` 아래로 분리
- 정리하면 source run(`py Main.py`)은 `.ari_runtime/`, frozen exe run은 `%AppData%/Ari/`를 사용
- 레거시 루트 상태 파일이 있으면 새 런타임 경로로 자동 마이그레이션

### `ui/scheduler_panel.py`
- Qt 시그널 연결 제거 → `QTimer` 5초 폴링 방식으로 교체
- `task.name` 표시: fallback → `task.goal[:30]`
- 긴 작업명/설명/최근 실행 결과 라벨이 패널 안에서 줄바꿈되도록 `wordWrap`/`QSizePolicy` 보강
- 스크롤 영역 가로 스크롤바를 비활성화해 긴 텍스트가 패널을 밀어내지 않도록 유지

---

## 6. 2026-04-07 주요 변경사항

### 국제화 (i18n) 최종 완료
- `i18n/translator.py`: gettext 기반 번역 엔진 구현. `_()` 함수 제공.
- `SettingsDialog`: 언어 선택 UI(ko/en/ja) 추가 및 전체 탭/버튼 번역 적용.
- `TextInterface`: 채팅창 메시지, 상태 패널, 대시보드 전체 번역 적용.
- `settings_schema.py`: 언어별 기본 Edge TTS 음성 매핑(`_TTS_VOICE_BY_LANG`) 및 자동 전환 로직 추가.
- `scripts/compile_po.py`: .po 파일을 .mo 바이너리로 컴파일하는 도구 구현.
- `README.md`: 한국어, 영어, 일본어 3개 국어 버전으로 확장.
- `build_exe.py`: `.mo` 번역 파일들이 EXE에 포함되도록 데이터 디렉터리 설정 보강.

## 7. 2026-04-06 주요 변경사항

### 실행 엔진 / 구조 분리
- `condition_evaluator.py`: ExecutionEngine step 조건 평가를 별도 모듈로 분리
- `ExecutionEngine`: 조건식 로직을 위 모듈에 위임하고 fail-closed 동작 유지
- `planner_json_utils.py`: AgentPlanner JSON 응답 복구 로직을 별도 모듈로 분리
- `automation_plan_utils.py`: AutomationHelpers adaptive/resilient 계획 조립 로직을 별도 모듈로 분리
- `assistant_text_utils.py`: LLMProvider/AICommand 공통 goal 해석·응답 정리 로직을 별도 모듈로 분리

### 문서 / 검증
- README 최근 업데이트와 아키텍처 설명을 최신 구조에 맞게 갱신
- `test_condition_evaluator.py` 추가, `test_execution_engine.py` 확장
- `test_planner_json_utils.py`, `test_automation_plan_utils.py` 추가
- `test_text_interface.py`에 채팅 말풍선 폭 제한·예약 작업 라벨 줄바꿈 회귀 테스트 추가
- `test_validate_repo.py`에 UI 파일 검증 대상 포함 여부 확인 추가
- `test_agent_planner_parsing.py`에 strategy/episode memory helper 정상 경로와 fail-closed 회귀 테스트 추가
- `test_singleton_factories.py`, `test_stt_provider.py` 추가
- `test_automation_helpers.py`, `test_autonomous_executor.py`, `test_validate_repo.py`에 런타임 안정성 회귀 케이스 추가
- 전체 검증 기준: `301/301` + smoke pass

---

## 7. 2026-04-03 주요 변경사항

### 보안 / 운영 안정성
- `plugin_loader.py`: ZIP safe extract, import 직전 `SafetyChecker` 재검사, 악성 경로 차단
- `skill_optimizer.py`: `run_compiled()` 실행 직전 `check_python()` 재검사
- `marketplace_client.py` + Supabase functions + SQL migration + web types: `sha256` 계약 end-to-end 정렬
- `ResourceManager`: 개발 모드 `.ari_runtime/` 분리, 레거시 루트 상태 자동 마이그레이션/정리
- `validate_repo.py`: compile + unittest 외에 clean runtime / marketplace SHA256 smoke 추가

### 자율 학습 / 성능
- `GoalPredictor`: double-digit 반복 실패(`10회`, `11회` 등)도 경고, fresh start 과잉 경고 방지
- `LearningMetrics` + `RegressionGuard`: 주간 리포트에서 학습 요소별 lift와 회귀 경고 제공
- `ConversationHistory`: 문장 경계 우선 요약으로 압축 품질 개선
- `TextInterface`: 스트리밍 응답 즉시 표시 + 문장 경계 TTS 즉시 시작
- `Main.py`: 워밍업과 주기 작업 등록 개선

### 검증 기준
- 당시 전체 테스트: `268/268`
- `validate_repo.py`: full pass
- stream TTS 회귀 테스트: `test_text_interface.py`

---

## 8. 알려진 미해결 문제

### 🟡 Groq Llama-3.3-70b tool call 신뢰도

Llama 계열 모델은 복잡한 tool calling 상황에서 텍스트 응답으로 대체하는 경향 있음.
`_recover_tool_calls_from_response` fallback 파서로 일부 복구 중이나 근본 해결은 모델 교체 권장.

**대응:**
- 설정 → AI&TTS → 제공자: `openai` (gpt-4o-mini 이상) 또는 `anthropic` 으로 변경 시 tool call 신뢰도 대폭 향상

### 🟡 FACT 오염 가능성

LLM이 일시적 상태를 FACT로 저장할 수 있음.
`memory_manager.py`의 `_EPHEMERAL_FACT_KEYS` (22개)로 차단 중이나 완전 차단은 아님.
주기적으로 "메모리 정리해줘" 음성 명령 또는 `MemoryConsolidator.run_all()` 호출 권장.

---

## 9. 개발 검증 명령

```bash
# 실행
py -3.11 VoiceCommand/Main.py

# 전체 검증
py -3.11 VoiceCommand/validate_repo.py

# 단위 테스트
py -3.11 -m unittest discover -s VoiceCommand/tests -p "test_*.py"

# EXE 빌드
py -3.11 VoiceCommand/build_exe.py [--clean] [--onefile]
```

---

## 10. 이 파일 사용법

새 AI 세션 시작 시:
1. 이 파일(`SESSION_CONTEXT.md`)을 먼저 제공
2. 작업하려는 파일을 추가로 제공
3. 섹션 6(미해결 문제)부터 읽고 시작
4. 작업 완료 후 섹션 4(신규 모듈)와 섹션 5(파일별 상태) 업데이트

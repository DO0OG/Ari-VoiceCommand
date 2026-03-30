# Session Context: Ari Voice Assistant Project

이 파일은 AI 세션(Claude, Gemini 등) 간 프로젝트 상태를 공유하기 위한 문서입니다.
새 세션 시작 시 이 파일을 가장 먼저 제공하세요.

## Last Updated: 2026-03-30
## 상태: Phase 1-5 구현 완료 · 전체 문서 업데이트 완료 · 135/135 테스트 통과

---

## 1. 프로젝트 개요

"아리(Ari)"는 Windows 전용 한국어 음성 AI 어시스턴트입니다.
- 웨이크워드 "아리야" 감지 → 음성 인식 → 명령 실행 → TTS 응답
- LLM: Groq / OpenAI / Anthropic / Mistral / Gemini / OpenRouter / NVIDIA NIM / **Ollama (로컬)**
- TTS: Fish Audio / CosyVoice3 (로컬) / OpenAI TTS / ElevenLabs / Edge TTS
- UI: PySide6 시스템 트레이 + 캐릭터 애니메이션 (Shimeji 스타일)
- 진입점: `Main.py` → `VoiceCommand.py` → `CommandRegistry` → 각 Command 클래스

### 디렉터리 구조

| 디렉터리 | 내용 |
|----------|------|
| `VoiceCommand/agent/` | 자율 실행 엔진 + 자기개선 루프 (LLMRouter, SkillLibrary, ReflectionEngine, PlannerFeedback, FewShot, WeeklyReport) |
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
| LearningCommand | 20 | 학습 모드 |
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

## 4. Phase 1-5 신규 모듈 (2026-03-30)

### agent/ 신규

| 파일 | 클래스·함수 | 역할 |
|------|------------|------|
| `llm_router.py` | `LLMRouter`, `get_llm_router()` | 작업 유형(코드/계획/분석/채팅)별 최적 모델 자동 라우팅 |
| `few_shot_injector.py` | `FewShotInjector`, `get_few_shot_injector()` | 성공 전략 → 플래너 프롬프트 자동 삽입 (MAX_EXAMPLES=3) |
| `skill_library.py` | `SkillLibrary`, `Skill`, `get_skill_library()` | 반복 성공 패턴 자동 추출·재사용·신뢰도 관리 |
| `reflection_engine.py` | `ReflectionEngine`, `ReflectionResult`, `get_reflection_engine()` | 실패 4레이어 자기반성 |
| `planner_feedback.py` | `PlannerFeedbackLoop`, `get_planner_feedback_loop()` | step_type별 성공률 통계 → 플래너 힌트 |
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
- 저장 경로: `ResourceManager.get_writable_path("scheduled_tasks.json")`

### `agent/llm_provider.py`
- Ollama 추가: `api_key="ollama"`, `base_url=ollama_base_url` 설정값 사용
- 도구 16개 정의 완료
- `planner_client`, `execution_client` 역할별 분리

### `agent/agent_orchestrator.py`
- `_post_run_update()`: 성공 시 SkillLibrary 스킬 추출, 실패 시 ReflectionEngine 반성 → StrategyMemory 저장
- PlannerFeedback, UserProfile, MemoryIndex 자동 업데이트

### `agent/agent_planner.py`
- FewShotInjector, PlannerFeedbackLoop 힌트를 시스템 프롬프트에 자동 주입

### `memory/conversation_history.py`
- 슬라이딩 요약: `MAX_ACTIVE=20`, `COMPRESS_UNIT=5`, `MAX_SUMMARIES=5`

### `core/config_manager.py`
- Phase 1-5 신규 기본값 6개: `llm_router_enabled`, `few_shot_max_examples`, `skill_library_enabled`, `reflection_engine_enabled`, `memory_consolidation_days`, `weekly_report_enabled`

### `ui/scheduler_panel.py`
- Qt 시그널 연결 제거 → `QTimer` 5초 폴링 방식으로 교체
- `task.name` 표시: fallback → `task.goal[:30]`

---

## 6. 알려진 미해결 문제

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

## 7. 개발 검증 명령

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

## 8. 이 파일 사용법

새 AI 세션 시작 시:
1. 이 파일(`SESSION_CONTEXT.md`)을 먼저 제공
2. 작업하려는 파일을 추가로 제공
3. 섹션 6(미해결 문제)부터 읽고 시작
4. 작업 완료 후 섹션 4(신규 모듈)와 섹션 5(파일별 상태) 업데이트

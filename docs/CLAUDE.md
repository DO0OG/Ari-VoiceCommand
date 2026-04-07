# CLAUDE.md (Ari/아리)

## Project Overview
Korean voice-controlled AI assistant for Windows. Features: Wake word ("아리야"), STT (Google/Whisper), LLM (Groq/OpenAI/Anthropic/Mistral/Gemini/OpenRouter/NVIDIA NIM/Ollama), TTS (CosyVoice3/Fish Audio/OpenAI/ElevenLabs/Edge), GUI/Browser automation, multi-role LLM (planner/executor model separation), streaming responses, self-improving agent loop (SkillLibrary + ReflectionEngine + PlannerFeedback), and SQLite FTS5 memory indexing.

## Commands
- **Run**: `py -3.11 Main.py`
- **Install**: `pip install -r requirements.txt`
- **Validate**:
  - Full: `py -3.11 VoiceCommand/validate_repo.py`
  - Compile only: `py -3.11 VoiceCommand/validate_repo.py --compile-only`
  - Tests: `py -3.11 -m unittest discover -s VoiceCommand/tests -p "test_*.py"` (총 301개)
- **Build EXE**: `py -3.11 build_exe.py [--clean] [--onefile]`
- **Install CosyVoice**: `py -3.11 install_cosyvoice.py [--dir PATH]` (default: `%USERPROFILE%\CosyVoice`)

## Session Startup Checklist
새 세션에서 저장소 작업 시작 전 확인:
1. `git log --oneline -5` — 최근 커밋 확인
2. `git status` — 로컬 변경 파악 (특히 `VoiceCommand/.ari_runtime/`·런타임 산출물은 커밋 제외, 저장소에는 `VoiceCommand/ari_settings.template.json`만 템플릿 기준선 유지)
3. 커밋·푸시 시 author는 **DO0OG(MAD_DOGGO)** 계정만 유지 (`Co-Authored-By` 등 추가 금지)
4. 검증: `validate_repo.py --compile-only` → 영향 테스트 → `git add` (로컬 파일 제외)

## Architecture & Logic
- **Entry**: `Main.py` (Qt App, System Tray, CosyVoice first-run check, plugin load with hook injection, `PluginWatcher` hot-reload timer)
- **State**: `AppState` in `core/VoiceCommand.py` — replaces 13 module-level globals
- **Config**: `ConfigManager` (`core/config_manager.py`) — RLock, double-checked locking cache
- **Threads (QThread)**:
  - `VoiceRecognitionThread`: Wake word → STT command capture.
  - `TTSThread`: Queue-based playback. `is_tts_playing()` checks status.
  - `CommandExecutionThread`: Non-blocking command logic.
- **Command Priority**: `BaseCommand.priority` — lower fires first. `SystemCommand=10`, `AICommand=100`.
- **STT**: `core/stt_provider.py` — `STTProvider` abstract base, `GoogleSTTProvider` (online), `WhisperSTTProvider` (offline, faster-whisper, **subprocess-isolated** via `core/_whisper_worker.py`). Selected via `stt_provider` setting (`"google"` | `"whisper"`). Wake words configurable via `wake_words` setting (default `["아리야", "시작"]`). `VoiceRecognitionThread` and `SimpleWakeWord` share a single STT provider instance — `_refresh_stt_provider()` injects the instance into `wake_detector` to prevent duplicate worker processes.
- **i18n (Internationalization)**: `i18n/translator.py` — `gettext`-based translation engine. `init()` must be called in `Main.py` before any other imports to ensure `_()` works in module constants. Supported languages: `ko`, `en`, `ja`.
- **Plugin System**:
  - `PluginManager` (`core/plugin_loader.py`): Scans `plugins/*.py`, checks `api_version` against `_COMPATIBLE_API_VERSIONS`, calls `register(context)`. Auto-injects `run_sandboxed` if not set by caller. Supports `load_plugin(path)`, `unload_plugin(name)`, `reload_plugin(name)` for hot-reload.
  - `PluginContext`: Carries `register_menu_action`, `register_command`, `register_tool`, `run_sandboxed` hooks injected from `Main.py`.
  - `plugin_sandbox` (`core/plugin_sandbox.py`): Runs arbitrary code string in an isolated Python worker process with configurable timeout. Returns `{"ok", "output", "error"}`.
  - `PluginWatcher` (`core/plugin_watcher.py`): watchdog-based `plugins/` directory watcher. Debounced (1 s). Flushed every 1 s via `QTimer` in `Main.py`. Triggers `load_plugin` / `reload_plugin` / `unload_plugin` automatically.
  - Current API version: `"1.0"`. Bump `_COMPATIBLE_API_VERSIONS` when making breaking changes.
- **Agent System**:
  - `AgentOrchestrator` (`agent/agent_orchestrator.py`): Multi-step task execution with parallel group scheduling and DOM replanning. **God class 분해(2026-04-04)**: 단계 실행 → `ExecutionEngine` (`agent/execution_engine.py`), 검증 → `VerificationEngine` (`agent/verification_engine.py`), 학습/기록 → `LearningEngine` (`agent/learning_engine.py`). `AgentOrchestrator`는 composition으로 세 엔진을 조율. `from agent.agent_orchestrator import AgentOrchestrator/StepResult` import 호환 유지. Post-run calls `_post_run_update()` → updates StrategyMemory, SkillLibrary, PlannerFeedback, UserProfile, MemoryIndex, EpisodeMemory (+ `prune_old_failures(30일)`). Developer goal 시 step 출력 저장 한도 2000자 (일반 목표 300자) — bootstrap JSON이 잘리지 않도록.
  - `AgentPlanner`: Template-first planning → DAG annotation (`dag_builder.py`). Accepts few-shot examples + planner hints injected in system prompt. Developer goal bootstrap: step_0(repo scan, samples=5), step_1(validate_repo.py 경로), step_2(test_*.py 목록). `_infer_relevant_tests(test_names, goal)` — goal에서 `.py` 파일명 추출해 관련 테스트 우선 표시. JSON 복구/균형 괄호 추출은 `agent/planner_json_utils.py`로 분리. 전략/에피소드 메모리 접근은 `_with_strategy_memory`, `_with_episode_memory` helper를 통해 fail-closed로 통일합니다. 주요 singleton getter는 생성 락으로 보호됩니다.
  - `RealVerifier`: 4-stage verification — heuristic → OCR → code → LLM.
  - `dag_builder`: Extracts resource reads/writes, builds dependency DAG, assigns parallel groups.
  - `embedder`: sentence-transformers / OpenAI / Gemini / hash-fallback embedding for strategy search.
  - `ocr_helper`: easyocr (primary) / pytesseract (secondary) screen text extraction.
  - `LLMRouter` (`agent/llm_router.py`): Keyword-based task classifier → routes to optimal provider/model. Task types: `simple_chat`, `complex_plan`, `code_gen`, `long_analysis`, `offline`. Singleton: `get_llm_router()`. Enabled via `llm_router_enabled` setting.
  - `assistant_text_utils.py`: `LLMProvider`와 `AICommand`가 공유하는 goal 해석, agent task 설명 우선순위, tool artifact 응답 정리 로직을 공통화.
  - `FewShotInjector` (`agent/few_shot_injector.py`): Injects top-K successful strategy records as few-shot examples into planner prompt. `MAX_EXAMPLES=3`. Singleton: `get_few_shot_injector()`.
  - `SkillLibrary` (`agent/skill_library.py`): Stores reusable step templates from repeated successes. `Skill` dataclass: `skill_id`, `name`, `trigger_patterns`, `steps`, `success_count`, `fail_count`, `avg_duration_ms`, `confidence`, `enabled`, **`compiled`** (bool). `get_applicable_skill(goal)` — pattern match, requires `confidence >= 0.45`. `try_extract_skill()` — auto-extracts after success; triggers compile at `success_count==5`, condense at `success_count==8`. `record_feedback(skill_id, positive, error="")` — adjusts confidence; triggers `optimize_steps` at `fail_count>=2`; triggers `repair_python` if compiled. All self-modification runs in daemon threads. Saved to `ResourceManager.get_writable_path("skill_library.json")`. Singleton: `get_skill_library()`.
  - `SkillOptimizer` (`agent/skill_optimizer.py`): LLM-driven skill self-modification engine. **Direction 1** — `optimize_steps(skill, error)`: rewrites JSON step sequence after failure; `condense_steps(skill)`: removes redundant steps after repeated success. **Direction 2** — `compile_to_python(skill)`: compiles verified skill to a single `run_skill(goal: str) -> str` Python function; `repair_python(skill, code, error)`: LLM rewrites broken compiled code. `save/load/delete/run_compiled(skill_id)`: manages `compiled_skills/` directory (via `ResourceManager`). Safety: `safety_checker.check_python()` + `ast.parse()` validation before saving. `skill_id`는 `^[A-Za-z0-9_\-]+$` 패턴만 허용 (경로 탈출 방지). Singleton: `get_skill_optimizer()`.
  - `ReflectionEngine` (`agent/reflection_engine.py`): Structured failure analysis → `ReflectionResult(lesson, root_cause, avoid_patterns, fix_suggestion)`. Uses `execution_analysis.classify_failure_message()`. Singleton: `get_reflection_engine()`.
  - `PlannerFeedbackLoop` (`agent/planner_feedback.py`): Records per-step-type success/fail/duration stats to `agent/planner_stats.json`. `get_hints(goal, tags)` returns formatted hint string injected into planner prompt. Singleton: `get_planner_feedback_loop()`.
  - `WeeklyReport` (`agent/weekly_report.py`): Aggregates StrategyMemory + SkillLibrary + UserContext + LearningMetrics + RegressionGuard into a single Korean summary string. Singleton: `get_weekly_report()`.
  - `GoalPredictor` (`agent/goal_predictor.py`): 과거 유사 전략을 바탕으로 목표 위험도 예측. `warn_if_high_risk(goal)` — 성공률 < 35% 또는 반복 실패 패턴 감지 시 한국어 경고 반환. `AgentOrchestrator._run_loop` 진입 시 호출. Singleton: `get_goal_predictor()`.
  - `LearningMetrics` (`agent/learning_metrics.py`): 7개 학습 컴포넌트(GoalPredictor·StrategyMemory·EpisodeMemory·FewShot·PlannerFeedback·SkillLibrary·ReflectionEngine) 기여도 계측. `record(name, activated, success)` — 활성 여부·성공 여부 누적. `get_report_lines(limit)` — lift 순 정렬 리포트. 파일: `learning_metrics.json`. Singleton: `get_learning_metrics()`.
  - `RegressionGuard` (`agent/regression_guard.py`): 이번 주 vs 지난 주 전략 성공률 비교. 10% 이상 하락 시 경고 문자열 반환. `MIN_SAMPLE=10`. Singleton: `get_regression_guard()`.
  - `EpisodeMemory` (`agent/episode_memory.py`): 자율 실행 에피소드(목표·성공여부·요약·실패종류·타임스탬프) 기록. `_MAX_EPISODES=120`. `prune_old_failures(max_age_days=30)` — 30일 이상 된 실패 에피소드 자동 정리. `get_goal_guidance(goal)` — 유사 목표 에피소드를 planner 프롬프트에 주입. Singleton: `get_episode_memory()`.
- **LLM Providers** (`agent/llm_provider.py`): Groq, OpenAI, Anthropic, Mistral, Gemini, OpenRouter, NVIDIA NIM, **Ollama** — all via `_PROVIDER_CONFIG`. Per-role clients: `planner_client`, `execution_client`. Ollama uses openai SDK with `api_key="ollama"` and `base_url` from `ollama_base_url` setting (default `http://localhost:11434/v1`). No extra package needed.
- **Tool Schemas** (`agent/tool_schemas.py`): OpenAI-compatible core tool schema 목록을 별도 관리. `LLMProvider.get_available_tools()`는 이 모듈의 정적 스키마와 플러그인 도구를 합쳐 반환합니다.
- **Condition Evaluation** (`agent/condition_evaluator.py`): ExecutionEngine step condition용 안전 AST 평가기. `len`, `str`, `int`, `float`, `bool`, `dict.get()`만 허용하며 실패 시 ExecutionEngine에서 fail-closed 처리합니다.
- **Memory**:
  - `UserContextManager` — TTL-based fact decay via `trust_engine.py` (source weights, conflict resolution, access-count decay modifier).
  - `StrategyMemory` — 3-stage search: heuristic score → embedding cosine → cross-encoder rerank.
  - `trust_engine` — `compute_reinforcement`, `compute_conflict_update`, `compute_decay`, `should_remove`.
  - `ConversationHistory` (`memory/conversation_history.py`): Sliding-window summary. `MAX_ACTIVE=20`, `COMPRESS_UNIT=5`, `MAX_SUMMARIES=5`. Auto-compresses when active list exceeds MAX_ACTIVE. `_summarize_chunk()` — 문장 경계 우선 의미 추출 (`_extract_key_text`), `Q:질문 → A:답변` 포맷. 단순 truncation 아님.
  - `UserProfileEngine` (`memory/user_profile_engine.py`): Infers user expertise areas, response style, active hours, frequent goals from interactions. Saved to `user_profile.json` via `ResourceManager.get_writable_path()`. `get_prompt_injection()` returns formatted Korean string for system prompt. Singleton: `get_user_profile_engine()`.
  - `MemoryIndex` (`memory/memory_index.py`): SQLite FTS5 full-text search over conversations and facts. DB at `ResourceManager.get_writable_path("ari_memory.db")`. `index_conversation()`, `index_fact()`, `search(query, limit)`, `search_by_date(start, end)`, `rebuild_index()`. Singleton: `get_memory_index()`.
  - `MemoryConsolidator` (`memory/memory_consolidator.py`): Batch cleanup — `consolidate_facts()` (calls `ctx.optimize_memory()`), `consolidate_strategies()` (calls `memory._prune()`), `summarize_old_conversations(days_ago=14)` (moves old items to summaries). `run_all()` returns `{facts, strategies, conversations}` counts. Singleton: `get_memory_consolidator()`.
- **Browser**: `SmartBrowser` (`services/web_tools.py`) + `dom_analyser.py` — DOM state analysis and next-action suggestions after login.
- **UI**: Centralized theme in `ui/theme.py`. `ThemeEditorDialog` (`ui/theme_editor.py`) — palette editor opens as an independent window (`Qt.Window`) from the settings Device tab. `ThemeEditorWidget` is the inner editing widget; `ThemeEditorDialog` wraps it. `ScheduledTasksDialog` (`ui/scheduled_tasks_dialog.py`) — list/cancel scheduled tasks, auto-refreshes every 5 s, and disables horizontal scrolling so long rows stay readable. `STTSettingsDialog` (`ui/stt_settings_dialog.py`) — separate window for STT engine, Whisper model/download, microphone sensitivity, and wake words; opened via "음성 인식 설정..." button in the Device tab. Whisper section toggles visibility and calls `adjustSize()` on provider change.
- **Text streaming / chat layout**: `ui/text_interface.py` — `stream_chunk` signal updates the visible response immediately, `_try_stream_tts()` starts TTS on sentence boundaries before the full response finishes, and `ChatWidget` clamps bubble width to the viewport so long text wraps inside the panel. `test_text_interface.py` covers stream-TTS flush behavior plus chat/scheduler layout guards.
- **Character Widget right-click menu**: `CharacterWidget.set_tray_menu(menu)` — injects the tray `QMenu` so right-clicking the character shows the identical menu (including plugin actions). Called in `Main.py` after `set_character_widget`. Falls back to a standalone menu if no tray is available.
- **Audio**: `GlobalAudio` singleton with separate input/output locks.

## Key Patterns
- **TTS**: `from core.VoiceCommand import tts_wrapper; tts_wrapper("text")`
- **Commands**: Add class in `commands/`, register in `commands/command_registry.py`. Plugins use `context.register_command(instance)` at runtime.
- **Automation**: Use `agent/automation_helpers.py` for GUI/Browser tasks. adaptive/resilient 계획 공통 조립은 `agent/automation_plan_utils.py`에 분리되어 있습니다.
- **AI 응답 정리/goal 해석**: `LLMProvider`와 `AICommand` 모두 `agent/assistant_text_utils.py`를 재사용해 tool artifact 제거와 자세한 goal 선택 기준을 동일하게 유지합니다.
- **Files**: Use `autonomous_executor.save_document()` for txt/md/pdf output.
- **New LLM provider**: Add to `_PROVIDER_CONFIG` in `agent/llm_provider.py`, add API key to `ConfigManager.DEFAULT_SETTINGS`, add to `ui/settings_llm_page.py` `LLM_PROVIDERS` + `LLM_KEYS` (SettingsDialog에서 분리됨). For local providers (like Ollama), set `api_key` to dummy string and override `base_url` in client kwargs.
- **Self-improvement loop**: After each agent task, `AgentOrchestrator._post_run_update()` is called automatically — updates StrategyMemory, SkillLibrary (`try_extract_skill`), PlannerFeedback (`record`), UserProfile (`update`), MemoryIndex (`index_conversation`), EpisodeMemory (`record` + `prune_old_failures`). ReflectionEngine is called on failure to generate lesson/avoid_patterns stored in StrategyMemory.
- **Smart assistant mode**: `learning_mode['enabled']` is not a global on/off switch for the orchestrator. It mainly makes `AICommand._should_escalate_to_agent_task()` more willing to promote complex requests to `run_agent_task`, and records user patterns more aggressively. Explicit `run_agent_task` calls can still invoke the orchestrator when the mode is off.
- **Developer goal flow**: `is_developer_goal()` 판정 시 → bootstrap(step 0~2: repo scan·validate경로·test_*.py 목록) → verify 실패(코드 변경 없음) → 2차 iteration에서 LLM이 context 받아 코드 수정+검증 생성. 검증 필수: `validate_repo.py --compile-only` + `VoiceCommand.tests.*` unittest. `py_compile` 단독·`&&` 체인·`tests/` 루트 경로·전체 재스캔 금지.
- **Planner helper regressions**: `VoiceCommand.tests.test_agent_planner_parsing`는 truncated JSON 복구 외에도 strategy/episode memory helper의 정상 경로와 optional module 실패 시 빈 문자열 반환(fail-closed)까지 검증합니다.
- **STT resilience**: `core/stt_provider.py`의 `WhisperSTTProvider`는 READY 대기와 전사 응답에 timeout을 두고, 워커 hang/종료 시 자동 재시작합니다. `audio.simple_wake`와 `core.threads`는 같은 설정 서명에서도 unhealthy provider를 재생성합니다.
- **Factory regressions**: `VoiceCommand.tests.test_singleton_factories`는 주요 singleton getter가 동시 호출에도 인스턴스를 한 번만 생성하는지 확인합니다.
- **Scheduled tasks**: `ProactiveScheduler` (`agent/proactive_scheduler.py`) is the single scheduler — `scheduler.py` (AriScheduler) has been deleted. Key methods: `add_task(name, goal, schedule_expr)`, `remove_task(task_id)`, `toggle_task(task_id)`, `run_task_now(task_id)`, `check_missed_tasks_on_startup()`. `schedule_expr` supports: `"매일 HH:MM"`, `"매주 요일 HH:MM"`, `"X분마다"`, `"X시간마다"`. Saves to `ResourceManager.get_writable_path("scheduled_tasks.json")`.
- **Plugin tool registration**: Call `context.register_tool(schema, handler)` from `register()`. Tool name must not collide with built-in dispatch keys. Handler signature: `(args: dict) -> Optional[str]`. Return str is spoken via TTS.
- **Plugin menu registration**: Call `context.register_menu_action(label, callback)` — inserts before "설정" in tray menu (and automatically appears in character right-click menu via shared `QMenu`). Must be called from Qt main thread (safe inside `register()`).
- **Character menu visibility control**: Call `context.set_character_menu_enabled(False)` to suppress the character widget's right-click context menu entirely (e.g., for fullscreen/game modes). Automatically restored to `True` when the plugin is unloaded.
- **Plugin sandbox**: `result = context.run_sandboxed(code_str, timeout=15)` — isolated worker-process execution. Check `result["ok"]` before using `result["output"]`.
- **DAG parallel execution**: Steps with same `parallel_group` run concurrently via `ThreadPoolExecutor`. Groups are assigned by `dag_builder.assign_parallel_groups()` (Kahn's algorithm). Step ordering is preserved per step_id in `_group_by_dependency()`.
- **Trust engine**: Call `compute_reinforcement` / `compute_conflict_update` from `memory/trust_engine.py` when updating facts. Never manually update confidence values.

## Technical Constants
- **Plugin API version**: `"1.0"` (`core/plugin_loader.py:PLUGIN_API_VERSION`). Compatible set: `_COMPATIBLE_API_VERSIONS`.
- **Sandbox timeout default**: 15 seconds (`core/plugin_sandbox.py:DEFAULT_TIMEOUT`).
- **NumPy version**: `>=1.26.0,<2` — NumPy 2.x breaks shiboken6 (PySide6) and easyocr compiled extensions.
- **Wake Words**: configurable via `wake_words` setting (default `["아리야", "시작"]`). Changed at runtime without restart.
- **Fish Audio Latency**: 1.5s termination delay.
- **CosyVoice ODE steps**: 3 for text ≤15 chars, 5 for longer text.
- **Log rotation**: Max 10 log files in `VoiceCommand/.ari_runtime/logs/` (auto-purge oldest).
- **Runtime roots**: source run (`py Main.py`) → `VoiceCommand/.ari_runtime/`; frozen exe run → `%AppData%/Ari/`.
- **Scheduled shutdown/restart**: `SystemCommand` parses time expressions → `shutdown /s /t <seconds>` (종료) / `shutdown /r /t <seconds>` (재시작) / `shutdown /a` (취소). Compound relative time supported ("1시간 30분 뒤" = 5400s).
- **Timer**: `TimerManager` (`services/timer_manager.py`) — multiple named timers, max 10. `set_timer(minutes, name="")` auto-names ("타이머 1", "타이머 2", …). `cancel_timer(name="")` cancels by name or most-recent. `list_timers()` returns `[{"name", "remaining_seconds"}]`. LLM tools `set_timer`/`cancel_timer` accept optional `name` param.
- **STT settings**: `stt_provider` (`"google"` | `"whisper"`), `whisper_model` (`"tiny"` | `"small"` | `"medium"`), `whisper_device` (`"auto"` | `"cpu"` | `"cuda"`), `whisper_compute_type` (`"int8"`), `stt_energy_threshold` (int), `stt_dynamic_energy` (bool). Managed via `STTSettingsDialog` (separate window, opened from Device tab).
- **Whisper subprocess isolation**: `WhisperSTTProvider` runs `core/_whisper_worker.py` as a subprocess (`stdin`/`stdout` base64 IPC) to prevent MKL/CTranslate2 DLL conflict with numpy/torch. `KMP_DUPLICATE_LIB_OK=TRUE` is set in `Main.py` at startup as an additional safeguard.
- **TTS fallback**: `tts_fallback_provider` setting — if primary TTS init fails, falls back to this provider (default `"edge"`).
- **LLM tools (built-in, 16개)**: `get_screen_status`, `play_youtube`, `set_timer`, `cancel_timer`, `get_weather`, `adjust_volume`, `get_current_time`, `execute_python_code`, `execute_shell_command`, `run_agent_task`, `web_search`, `web_fetch`, `schedule_task`, `shutdown_computer`, `list_scheduled_tasks`, `cancel_scheduled_task`.
- **MemoryCommand voice triggers (6개)**: `"자주 하는 작업"`, `"저번에 내가"`, `"내 스킬 목록"` / `"스킬 목록"`, `"이 스킬 삭제"`, `"메모리 정리"`, `"나에 대해 뭐 알아"` / `"나에 대해 뭘 알아"`. Priority=45.
- **ConfigManager new defaults (Phase 1-8)**: `llm_router_enabled=True`, `few_shot_max_examples=3`, `skill_library_enabled=True`, `reflection_engine_enabled=True`, `memory_consolidation_days=14`, `weekly_report_enabled=False`.
- **Embedding backends** (priority): sentence-transformers (384-dim) → OpenAI (1536-dim) → Gemini (768-dim) → SHA256 hash fallback (64-dim).
- **Source trust weights**: user=1.0, assistant=0.7, external=0.6, learned=0.5, inferred=0.4.
- **Fact removal threshold**: confidence < 0.12, or conflict_count ≥ 5 with confidence < 0.25.
- **LLMRouter task types**: `simple_chat` → Groq llama-3.3-70b, `complex_plan` → Groq llama-3.3-70b, `code_gen` → Groq qwen-qwq-32b, `long_analysis` → OpenAI gpt-4o-mini, `offline` → Ollama llama3.2. Classification: code keywords → code_gen, plan keywords → complex_plan, len>120 or long keywords → long_analysis, else → simple_chat.
- **SkillLibrary confidence thresholds**: New skill starts at 0.65; `get_applicable_skill` requires ≥0.45; positive feedback +0.06, negative −0.12; disabled when `fail_count >= 2 > success_count`.
- **SkillOptimizer thresholds**: `_OPTIMIZE_ON_FAIL=2` (step rewrite), `_COMPILE_THRESHOLD=5` (Python compile), `_CONDENSE_THRESHOLD=8` (step condense). All async, daemon threads.
- **Compiled skill execution order**: `skill.compiled=True` → `run_compiled()` → fallback to JSON steps → fallback to full agent loop.
- **Compiled skill storage**: `ResourceManager.get_writable_path("compiled_skills")/<skill_id>.py`. Function signature must be `run_skill(goal: str) -> str`.
- **Scheduler import**: Always import from `agent.proactive_scheduler` (not the deleted `agent.scheduler`).
- **EpisodeMemory limits**: `_MAX_EPISODES=120` (오래된 항목 자동 drop). `prune_old_failures(30)` — 실행 후 자동 호출. 파일: `ResourceManager.get_writable_path("episode_memory.json")` (로컬 전용, 커밋 제외).
- **Developer goal step output limit**: 2000자 (일반 목표 300자). `agent_orchestrator._execute_plan:395`.
- **Bootstrap step sizes** (2026-04-06 기준): step_0 ~954자, step_2 ~783자 수준으로 2000자 이내를 유지하도록 설계. 테스트 목록은 최신 `VoiceCommand/tests/test_*.py` 집합 기준으로 갱신됩니다.
- **Commit exclusions**: `VoiceCommand/.ari_runtime/`, `collected.json`, `AGENT_HANDOFF_*.md`, `.idea/`. 루트에 런타임 파일이 다시 생기면 ignore에 추가하지 말고 경로 회귀로 간주해 수정.

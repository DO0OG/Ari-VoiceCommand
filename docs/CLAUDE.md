# CLAUDE.md (Ari/아리)

## Project Overview
Korean voice-controlled AI assistant for Windows. Features: Wake word ("아리야"), STT (Google/Whisper), LLM (Groq/OpenAI/Anthropic/Mistral/Gemini/OpenRouter/NVIDIA NIM/Ollama), TTS (CosyVoice3/Fish Audio/OpenAI/ElevenLabs/Edge), GUI/Browser automation, multi-role LLM (planner/executor model separation), streaming responses, self-improving agent loop (SkillLibrary + ReflectionEngine + PlannerFeedback), and SQLite FTS5 memory indexing.

## Commands
- **Run**: `py -3.11 Main.py`
- **Install**: `pip install -r requirements.txt`
- **Validate**:
  - Full: `py -3.11 validate_repo.py`
  - Tests: `py -3.11 -m unittest discover -s tests -p "test_*.py"`
  - Compile: `py -3.11 -m py_compile <files>`
- **Build EXE**: `py -3.11 build_exe.py [--clean] [--onefile]`
- **Install CosyVoice**: `py -3.11 install_cosyvoice.py [--dir PATH]` (default: `%USERPROFILE%\CosyVoice`)

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
- **Plugin System**:
  - `PluginManager` (`core/plugin_loader.py`): Scans `plugins/*.py`, checks `api_version` against `_COMPATIBLE_API_VERSIONS`, calls `register(context)`. Auto-injects `run_sandboxed` if not set by caller. Supports `load_plugin(path)`, `unload_plugin(name)`, `reload_plugin(name)` for hot-reload.
  - `PluginContext`: Carries `register_menu_action`, `register_command`, `register_tool`, `run_sandboxed` hooks injected from `Main.py`.
  - `plugin_sandbox` (`core/plugin_sandbox.py`): Runs arbitrary code string in an isolated Python worker process with configurable timeout. Returns `{"ok", "output", "error"}`.
  - `PluginWatcher` (`core/plugin_watcher.py`): watchdog-based `plugins/` directory watcher. Debounced (1 s). Flushed every 1 s via `QTimer` in `Main.py`. Triggers `load_plugin` / `reload_plugin` / `unload_plugin` automatically.
  - Current API version: `"1.0"`. Bump `_COMPATIBLE_API_VERSIONS` when making breaking changes.
- **Agent System**:
  - `AgentOrchestrator`: Multi-step task execution with parallel group scheduling and DOM replanning. Post-run calls `_post_run_update()` → updates StrategyMemory, SkillLibrary, PlannerFeedback, UserProfile, MemoryIndex.
  - `AgentPlanner`: Template-first planning → DAG annotation (`dag_builder.py`). Accepts few-shot examples + planner hints injected in system prompt.
  - `RealVerifier`: 4-stage verification — heuristic → OCR → code → LLM.
  - `dag_builder`: Extracts resource reads/writes, builds dependency DAG, assigns parallel groups.
  - `embedder`: sentence-transformers / OpenAI / Gemini / hash-fallback embedding for strategy search.
  - `ocr_helper`: easyocr (primary) / pytesseract (secondary) screen text extraction.
  - `LLMRouter` (`agent/llm_router.py`): Keyword-based task classifier → routes to optimal provider/model. Task types: `simple_chat`, `complex_plan`, `code_gen`, `long_analysis`, `offline`. Singleton: `get_llm_router()`. Enabled via `llm_router_enabled` setting.
  - `FewShotInjector` (`agent/few_shot_injector.py`): Injects top-K successful strategy records as few-shot examples into planner prompt. `MAX_EXAMPLES=3`. Singleton: `get_few_shot_injector()`.
  - `SkillLibrary` (`agent/skill_library.py`): Stores reusable step templates from repeated successes. `Skill` dataclass: `skill_id`, `name`, `trigger_patterns`, `steps`, `success_count`, `fail_count`, `avg_duration_ms`, `confidence`, `enabled`, **`compiled`** (bool). `get_applicable_skill(goal)` — pattern match, requires `confidence >= 0.45`. `try_extract_skill()` — auto-extracts after success; triggers compile at `success_count==5`, condense at `success_count==8`. `record_feedback(skill_id, positive, error="")` — adjusts confidence; triggers `optimize_steps` at `fail_count>=2`; triggers `repair_python` if compiled. All self-modification runs in daemon threads. Saved to `ResourceManager.get_writable_path("skill_library.json")`. Singleton: `get_skill_library()`.
  - `SkillOptimizer` (`agent/skill_optimizer.py`): LLM-driven skill self-modification engine. **Direction 1** — `optimize_steps(skill, error)`: rewrites JSON step sequence after failure; `condense_steps(skill)`: removes redundant steps after repeated success. **Direction 2** — `compile_to_python(skill)`: compiles verified skill to a single `run_skill(goal: str) -> str` Python function; `repair_python(skill, code, error)`: LLM rewrites broken compiled code. `save/load/delete/run_compiled(skill_id)`: manages `compiled_skills/` directory (via `ResourceManager`). Safety: `safety_checker.check_python()` + `ast.parse()` validation before saving. Singleton: `get_skill_optimizer()`.
  - `ReflectionEngine` (`agent/reflection_engine.py`): Structured failure analysis → `ReflectionResult(lesson, root_cause, avoid_patterns, fix_suggestion)`. Uses `execution_analysis.classify_failure_message()`. Singleton: `get_reflection_engine()`.
  - `PlannerFeedbackLoop` (`agent/planner_feedback.py`): Records per-step-type success/fail/duration stats to `agent/planner_stats.json`. `get_hints(goal, tags)` returns formatted hint string injected into planner prompt. Singleton: `get_planner_feedback_loop()`.
  - `WeeklyReport` (`agent/weekly_report.py`): Aggregates StrategyMemory + SkillLibrary + UserContext into a single Korean summary string. Singleton: `get_weekly_report()`.
- **LLM Providers** (`agent/llm_provider.py`): Groq, OpenAI, Anthropic, Mistral, Gemini, OpenRouter, NVIDIA NIM, **Ollama** — all via `_PROVIDER_CONFIG`. Per-role clients: `planner_client`, `execution_client`. Ollama uses openai SDK with `api_key="ollama"` and `base_url` from `ollama_base_url` setting (default `http://localhost:11434/v1`). No extra package needed.
- **Memory**:
  - `UserContextManager` — TTL-based fact decay via `trust_engine.py` (source weights, conflict resolution, access-count decay modifier).
  - `StrategyMemory` — 3-stage search: heuristic score → embedding cosine → cross-encoder rerank.
  - `trust_engine` — `compute_reinforcement`, `compute_conflict_update`, `compute_decay`, `should_remove`.
  - `ConversationHistory` (`memory/conversation_history.py`): Sliding-window summary. `MAX_ACTIVE=20`, `COMPRESS_UNIT=5`, `MAX_SUMMARIES=5`. Auto-compresses when active list exceeds MAX_ACTIVE.
  - `UserProfileEngine` (`memory/user_profile_engine.py`): Infers user expertise areas, response style, active hours, frequent goals from interactions. Saved to `user_profile.json` via `ResourceManager.get_writable_path()`. `get_prompt_injection()` returns formatted Korean string for system prompt. Singleton: `get_user_profile_engine()`.
  - `MemoryIndex` (`memory/memory_index.py`): SQLite FTS5 full-text search over conversations and facts. DB at `ResourceManager.get_writable_path("ari_memory.db")`. `index_conversation()`, `index_fact()`, `search(query, limit)`, `search_by_date(start, end)`, `rebuild_index()`. Singleton: `get_memory_index()`.
  - `MemoryConsolidator` (`memory/memory_consolidator.py`): Batch cleanup — `consolidate_facts()` (calls `ctx.optimize_memory()`), `consolidate_strategies()` (calls `memory._prune()`), `summarize_old_conversations(days_ago=14)` (moves old items to summaries). `run_all()` returns `{facts, strategies, conversations}` counts. Singleton: `get_memory_consolidator()`.
- **Browser**: `SmartBrowser` (`services/web_tools.py`) + `dom_analyser.py` — DOM state analysis and next-action suggestions after login.
- **UI**: Centralized theme in `ui/theme.py`. `ThemeEditorDialog` (`ui/theme_editor.py`) — palette editor opens as an independent window (`Qt.Window`) from the settings Device tab. `ThemeEditorWidget` is the inner editing widget; `ThemeEditorDialog` wraps it. `ScheduledTasksDialog` (`ui/scheduled_tasks_dialog.py`) — list/cancel scheduled tasks, auto-refreshes every 5 s. `STTSettingsDialog` (`ui/stt_settings_dialog.py`) — separate window for STT engine, Whisper model/download, microphone sensitivity, and wake words; opened via "음성 인식 설정..." button in the Device tab. Whisper section toggles visibility and calls `adjustSize()` on provider change.
- **Character Widget right-click menu**: `CharacterWidget.set_tray_menu(menu)` — injects the tray `QMenu` so right-clicking the character shows the identical menu (including plugin actions). Called in `Main.py` after `set_character_widget`. Falls back to a standalone menu if no tray is available.
- **Audio**: `GlobalAudio` singleton with separate input/output locks.

## Key Patterns
- **TTS**: `from core.VoiceCommand import tts_wrapper; tts_wrapper("text")`
- **Commands**: Add class in `commands/`, register in `commands/command_registry.py`. Plugins use `context.register_command(instance)` at runtime.
- **Automation**: Use `agent/automation_helpers.py` for GUI/Browser tasks.
- **Files**: Use `autonomous_executor.save_document()` for txt/md/pdf output.
- **New LLM provider**: Add to `_PROVIDER_CONFIG` in `agent/llm_provider.py`, add API key to `ConfigManager.DEFAULT_SETTINGS`, add to `settings_dialog.py` `_LLM_PROVIDERS` + `LLM_KEYS`. For local providers (like Ollama), set `api_key` to dummy string and override `base_url` in client kwargs.
- **Self-improvement loop**: After each agent task, `AgentOrchestrator._post_run_update()` is called automatically — updates StrategyMemory, SkillLibrary (`try_extract_skill`), PlannerFeedback (`record`), UserProfile (`update`), MemoryIndex (`index_conversation`). ReflectionEngine is called on failure to generate lesson/avoid_patterns stored in StrategyMemory.
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
- **Log rotation**: Max 10 log files in `logs/` (auto-purge oldest).
- **Scheduled shutdown/restart**: `SystemCommand` parses time expressions → `shutdown /s /t <seconds>` (종료) / `shutdown /r /t <seconds>` (재시작) / `shutdown /a` (취소). Compound relative time supported ("1시간 30분 뒤" = 5400s).
- **Timer**: `TimerManager` (`services/timer_manager.py`) — multiple named timers, max 10. `set_timer(minutes, name="")` auto-names ("타이머 1", "타이머 2", …). `cancel_timer(name="")` cancels by name or most-recent. `list_timers()` returns `[{"name", "remaining_seconds"}]`. LLM tools `set_timer`/`cancel_timer` accept optional `name` param.
- **STT settings**: `stt_provider` (`"google"` | `"whisper"`), `whisper_model` (`"tiny"` | `"small"` | `"medium"`), `whisper_device` (`"auto"` | `"cpu"` | `"cuda"`), `whisper_compute_type` (`"int8"`), `stt_energy_threshold` (int), `stt_dynamic_energy` (bool). Managed via `STTSettingsDialog` (separate window, opened from Device tab).
- **Whisper subprocess isolation**: `WhisperSTTProvider` runs `core/_whisper_worker.py` as a subprocess (`stdin`/`stdout` base64 IPC) to prevent MKL/CTranslate2 DLL conflict with numpy/torch. `KMP_DUPLICATE_LIB_OK=TRUE` is set in `Main.py` at startup as an additional safeguard.
- **TTS fallback**: `tts_fallback_provider` setting — if primary TTS init fails, falls back to this provider (default `"edge"`).
- **LLM tools (built-in, 16개)**: `get_screen_status`, `play_youtube`, `set_timer`, `cancel_timer`, `get_weather`, `adjust_volume`, `get_current_time`, `execute_python_code`, `execute_shell_command`, `run_agent_task`, `web_search`, `web_fetch`, `schedule_task`, `shutdown_computer`, `list_scheduled_tasks`, `cancel_scheduled_task`.
- **MemoryCommand voice triggers (6개)**: `"자주 하는 작업"`, `"저번에 내가"`, `"내 스킬 목록"` / `"스킬 목록"`, `"이 스킬 삭제"`, `"메모리 정리"`, `"나에 대해 뭐 알아"` / `"나에 대해 뭘 알아"`. Priority=45.
- **ConfigManager new defaults (Phase 1-5)**: `llm_router_enabled=False`, `few_shot_max_examples=3`, `skill_library_enabled=True`, `reflection_engine_enabled=True`, `memory_consolidation_days=14`, `weekly_report_enabled=False`.
- **Embedding backends** (priority): sentence-transformers (384-dim) → OpenAI (1536-dim) → Gemini (768-dim) → SHA256 hash fallback (64-dim).
- **Source trust weights**: user=1.0, assistant=0.7, external=0.6, learned=0.5, inferred=0.4.
- **Fact removal threshold**: confidence < 0.12, or conflict_count ≥ 5 with confidence < 0.25.
- **LLMRouter task types**: `simple_chat` → Groq llama-3.3-70b, `complex_plan` → Groq llama-3.3-70b, `code_gen` → Groq qwen-qwq-32b, `long_analysis` → OpenAI gpt-4o-mini, `offline` → Ollama llama3.2. Classification: code keywords → code_gen, plan keywords → complex_plan, len>120 or long keywords → long_analysis, else → simple_chat.
- **SkillLibrary confidence thresholds**: New skill starts at 0.65; `get_applicable_skill` requires ≥0.45; positive feedback +0.06, negative −0.12; disabled when `fail_count >= 2 > success_count`.
- **SkillOptimizer thresholds**: `_OPTIMIZE_ON_FAIL=2` (step rewrite), `_COMPILE_THRESHOLD=5` (Python compile), `_CONDENSE_THRESHOLD=8` (step condense). All async, daemon threads.
- **Compiled skill execution order**: `skill.compiled=True` → `run_compiled()` → fallback to JSON steps → fallback to full agent loop.
- **Compiled skill storage**: `ResourceManager.get_writable_path("compiled_skills")/<skill_id>.py`. Function signature must be `run_skill(goal: str) -> str`.
- **Scheduler import**: Always import from `agent.proactive_scheduler` (not the deleted `agent.scheduler`).

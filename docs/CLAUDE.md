# CLAUDE.md (Ari/아리)

## Project Overview
Korean voice-controlled AI assistant for Windows. Features: Wake word ("아리야"), STT (Google), LLM (Groq/OpenAI/Anthropic/Mistral/Gemini/OpenRouter/NVIDIA NIM), TTS (CosyVoice3/Fish Audio/OpenAI/ElevenLabs/Edge), GUI/Browser automation, and multi-role LLM (planner/executor model separation).

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
  - `plugin_sandbox` (`core/plugin_sandbox.py`): Runs arbitrary code string in a subprocess with configurable timeout. Returns `{"ok", "output", "error"}`.
  - `PluginWatcher` (`core/plugin_watcher.py`): watchdog-based `plugins/` directory watcher. Debounced (1 s). Flushed every 1 s via `QTimer` in `Main.py`. Triggers `load_plugin` / `reload_plugin` / `unload_plugin` automatically.
  - Current API version: `"1.0"`. Bump `_COMPATIBLE_API_VERSIONS` when making breaking changes.
- **Agent System**:
  - `AgentOrchestrator`: Multi-step task execution with parallel group scheduling and DOM replanning.
  - `AgentPlanner`: Template-first planning → DAG annotation (`dag_builder.py`).
  - `RealVerifier`: 4-stage verification — heuristic → OCR → code → LLM.
  - `dag_builder`: Extracts resource reads/writes, builds dependency DAG, assigns parallel groups.
  - `embedder`: sentence-transformers / OpenAI / Gemini / hash-fallback embedding for strategy search.
  - `ocr_helper`: easyocr (primary) / pytesseract (secondary) screen text extraction.
- **LLM Providers** (`agent/llm_provider.py`): Groq, OpenAI, Anthropic, Mistral, Gemini, OpenRouter, NVIDIA NIM — all via `_PROVIDER_CONFIG`. Per-role clients: `planner_client`, `execution_client`.
- **Memory**:
  - `UserContextManager` — TTL-based fact decay via `trust_engine.py` (source weights, conflict resolution, access-count decay modifier).
  - `StrategyMemory` — 3-stage search: heuristic score → embedding cosine → cross-encoder rerank.
  - `trust_engine` — `compute_reinforcement`, `compute_conflict_update`, `compute_decay`, `should_remove`.
- **Browser**: `SmartBrowser` (`services/web_tools.py`) + `dom_analyser.py` — DOM state analysis and next-action suggestions after login.
- **UI**: Centralized theme in `ui/theme.py`. `ThemeEditorDialog` (`ui/theme_editor.py`) — palette editor opens as an independent window (`Qt.Window`) from the settings Device tab. `ThemeEditorWidget` is the inner editing widget; `ThemeEditorDialog` wraps it. `ScheduledTasksDialog` (`ui/scheduled_tasks_dialog.py`) — list/cancel scheduled tasks, auto-refreshes every 5 s. `STTSettingsDialog` (`ui/stt_settings_dialog.py`) — separate window for STT engine, Whisper model/download, microphone sensitivity, and wake words; opened via "음성 인식 설정..." button in the Device tab. Whisper section toggles visibility and calls `adjustSize()` on provider change.
- **Character Widget right-click menu**: `CharacterWidget.set_tray_menu(menu)` — injects the tray `QMenu` so right-clicking the character shows the identical menu (including plugin actions). Called in `Main.py` after `set_character_widget`. Falls back to a standalone menu if no tray is available.
- **Audio**: `GlobalAudio` singleton with separate input/output locks.

## Key Patterns
- **TTS**: `from core.VoiceCommand import tts_wrapper; tts_wrapper("text")`
- **Commands**: Add class in `commands/`, register in `commands/command_registry.py`. Plugins use `context.register_command(instance)` at runtime.
- **Automation**: Use `agent/automation_helpers.py` for GUI/Browser tasks.
- **Files**: Use `autonomous_executor.save_document()` for txt/md/pdf output.
- **New LLM provider**: Add to `_PROVIDER_CONFIG` in `agent/llm_provider.py`, add API key to `ConfigManager.DEFAULT_SETTINGS`, add to `settings_dialog.py` `_LLM_PROVIDERS` + `LLM_KEYS`.
- **Plugin tool registration**: Call `context.register_tool(schema, handler)` from `register()`. Tool name must not collide with built-in dispatch keys. Handler signature: `(args: dict) -> Optional[str]`. Return str is spoken via TTS.
- **Plugin menu registration**: Call `context.register_menu_action(label, callback)` — inserts before "설정" in tray menu (and automatically appears in character right-click menu via shared `QMenu`). Must be called from Qt main thread (safe inside `register()`).
- **Character menu visibility control**: Call `context.set_character_menu_enabled(False)` to suppress the character widget's right-click context menu entirely (e.g., for fullscreen/game modes). Automatically restored to `True` when the plugin is unloaded.
- **Plugin sandbox**: `result = context.run_sandboxed(code_str, timeout=15)` — subprocess isolation. Check `result["ok"]` before using `result["output"]`.
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
- **Embedding backends** (priority): sentence-transformers (384-dim) → OpenAI (1536-dim) → Gemini (768-dim) → SHA256 hash fallback (64-dim).
- **Source trust weights**: user=1.0, assistant=0.7, external=0.6, learned=0.5, inferred=0.4.
- **Fact removal threshold**: confidence < 0.12, or conflict_count ≥ 5 with confidence < 0.25.

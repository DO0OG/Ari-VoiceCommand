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
- **Entry**: `Main.py` (Qt App, System Tray, CosyVoice first-run check, plugin load with hook injection)
- **State**: `AppState` in `core/VoiceCommand.py` — replaces 13 module-level globals
- **Config**: `ConfigManager` (`core/config_manager.py`) — RLock, double-checked locking cache
- **Threads (QThread)**:
  - `VoiceRecognitionThread`: Wake word → STT command capture.
  - `TTSThread`: Queue-based playback. `is_tts_playing()` checks status.
  - `CommandExecutionThread`: Non-blocking command logic.
- **Command Priority**: `BaseCommand.priority` — lower fires first. `SystemCommand=10`, `AICommand=100`.
- **Plugin System**:
  - `PluginManager` (`core/plugin_loader.py`): Scans `plugins/*.py`, checks `api_version` against `_COMPATIBLE_API_VERSIONS`, calls `register(context)`. Auto-injects `run_sandboxed` if not set by caller.
  - `PluginContext`: Carries `register_menu_action`, `register_command`, `register_tool`, `run_sandboxed` hooks injected from `Main.py`.
  - `plugin_sandbox` (`core/plugin_sandbox.py`): Runs arbitrary code string in a subprocess with configurable timeout. Returns `{"ok", "output", "error"}`.
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
- **UI**: Centralized theme in `ui/theme.py`. `ThemeEditorDialog` (`ui/theme_editor.py`) — palette editor opens as an independent window (`Qt.Window`) from the settings Device tab. `ThemeEditorWidget` is the inner editing widget; `ThemeEditorDialog` wraps it.
- **Audio**: `GlobalAudio` singleton with separate input/output locks.

## Key Patterns
- **TTS**: `from core.VoiceCommand import tts_wrapper; tts_wrapper("text")`
- **Commands**: Add class in `commands/`, register in `commands/command_registry.py`. Plugins use `context.register_command(instance)` at runtime.
- **Automation**: Use `agent/automation_helpers.py` for GUI/Browser tasks.
- **Files**: Use `autonomous_executor.save_document()` for txt/md/pdf output.
- **New LLM provider**: Add to `_PROVIDER_CONFIG` in `agent/llm_provider.py`, add API key to `ConfigManager.DEFAULT_SETTINGS`, add to `settings_dialog.py` `_LLM_PROVIDERS` + `LLM_KEYS`.
- **Plugin tool registration**: Call `context.register_tool(schema, handler)` from `register()`. Tool name must not collide with built-in dispatch keys. Handler signature: `(args: dict) -> Optional[str]`. Return str is spoken via TTS.
- **Plugin menu registration**: Call `context.register_menu_action(label, callback)` — inserts before "설정" in tray menu. Must be called from Qt main thread (safe inside `register()`).
- **Plugin sandbox**: `result = context.run_sandboxed(code_str, timeout=15)` — subprocess isolation. Check `result["ok"]` before using `result["output"]`.
- **DAG parallel execution**: Steps with same `parallel_group` run concurrently via `ThreadPoolExecutor`. Groups are assigned by `dag_builder.assign_parallel_groups()` (Kahn's algorithm). Step ordering is preserved per step_id in `_group_by_dependency()`.
- **Trust engine**: Call `compute_reinforcement` / `compute_conflict_update` from `memory/trust_engine.py` when updating facts. Never manually update confidence values.

## Technical Constants
- **Plugin API version**: `"1.0"` (`core/plugin_loader.py:PLUGIN_API_VERSION`). Compatible set: `_COMPATIBLE_API_VERSIONS`.
- **Sandbox timeout default**: 15 seconds (`core/plugin_sandbox.py:DEFAULT_TIMEOUT`).
- **NumPy version**: `>=1.26.0,<2` — NumPy 2.x breaks shiboken6 (PySide6) and easyocr compiled extensions.
- **Wake Word**: "아리야" or "시작"
- **Fish Audio Latency**: 1.5s termination delay.
- **CosyVoice ODE steps**: 3 for text ≤15 chars, 5 for longer text.
- **Log rotation**: Max 10 log files in `logs/` (auto-purge oldest).
- **Scheduled shutdown**: `SystemCommand` parses time expressions → `shutdown /s /t <seconds>`.
- **Embedding backends** (priority): sentence-transformers (384-dim) → OpenAI (1536-dim) → Gemini (768-dim) → SHA256 hash fallback (64-dim).
- **Source trust weights**: user=1.0, assistant=0.7, external=0.6, learned=0.5, inferred=0.4.
- **Fact removal threshold**: confidence < 0.12, or conflict_count ≥ 5 with confidence < 0.25.

# CLAUDE.md (Ari/아리)

## Project Overview
Korean voice-controlled AI assistant for Windows. Features: Wake word ("아리야"), STT (Google), LLM (Groq/OpenAI/Anthropic/Mistral/Gemini/OpenRouter/NVIDIA NIM), TTS (CosyVoice3/Fish Audio/OpenAI/ElevenLabs/Edge), and GUI/Browser automation.

## Commands
- **Run**: `py -3.11 Main.py`
- **Install**: `pip install -r requirements.txt`
- **Validate**:
  - Full: `py -3.11 validate_repo.py`
  - Tests: `py -3.11 -m unittest discover -s tests -p "test_*.py"`
  - Compile: `py -3.11 -m py_compile <files>`
- **Build EXE**: `py -3.11 build_exe.py [--clean] [--onefile]`

## Architecture & Logic
- **Entry**: `Main.py` (Qt App, System Tray, CosyVoice first-run check)
- **State**: `AppState` in `core/VoiceCommand.py` — replaces 13 module-level globals
- **Config**: `ConfigManager` (`core/config_manager.py`) — RLock, double-checked locking cache
- **Threads (QThread)**:
  - `VoiceRecognitionThread`: Wake word → STT command capture.
  - `TTSThread`: Queue-based playback. `is_tts_playing()` checks status.
  - `CommandExecutionThread`: Non-blocking command logic.
- **Command Priority**: `BaseCommand.priority` — lower fires first. `SystemCommand=10`, `AICommand=100`.
- **Agent System**:
  - `AgentOrchestrator`: Multi-step task execution with post-mortem learning (`StrategyMemory`).
  - `AgentPlanner`: Template-first planning (Folder/Search/System info/Browser/Desktop workflows).
  - `RealVerifier`: Artifact-based (files/paths/URLs) execution validation.
- **LLM Providers** (`agent/llm_provider.py`): Groq, OpenAI, Anthropic, Mistral, Gemini, OpenRouter, NVIDIA NIM — all via `_PROVIDER_CONFIG`.
- **Memory**: `UserContextManager` with TTL-based fact decay, topic tracking, preference accumulation.
- **UI**: Centralized theme in `ui/theme.py`. Supports "Thinking" state animation.
- **Audio**: `GlobalAudio` singleton with separate input/output locks.
- **Game Mode**: Switches to `Fish Audio` (Cloud) to free VRAM from `CosyVoice` (Local).

## Key Patterns
- **TTS**: `from core.VoiceCommand import tts_wrapper; tts_wrapper("text")`
- **Commands**: Add class in `commands/`, register in `commands/command_registry.py`.
- **Sync**: Always check `is_tts_playing()` before starting recognition.
- **Automation**: Use `agent/automation_helpers.py` for GUI/Browser tasks.
- **Files**: Use `autonomous_executor.save_document()` for txt/md/pdf output.
- **LLM new provider**: Add entry to `_PROVIDER_CONFIG` in `agent/llm_provider.py`, add API key to `ConfigManager.DEFAULT_SETTINGS`, add to `settings_dialog.py` `_LLM_PROVIDERS` + `LLM_KEYS`.

## Technical Constants
- **Wake Word**: "아리야" or "시작"
- **Fish Audio Latency**: 1.5s termination delay.
- **Automation**: Selenium (optional) for complex logins; PyAutoGUI for basic input.
- **CosyVoice ODE steps**: 3 for text ≤15 chars, 5 for longer text.
- **Log rotation**: Max 10 log files in `logs/` (auto-purge oldest).
- **Scheduled shutdown**: `SystemCommand` parses time expressions → `shutdown /s /t <seconds>`.

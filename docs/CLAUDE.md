# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

"Ari" (아리) is a Korean-language voice-controlled AI assistant for Windows. It features wake word detection, voice recognition, natural language understanding, and system control.

## Running the Application

```bash
# Run directly
python Main.py

# Or use batch file
Ari.bat
```

### Dependencies Installation
```bash
# Install all dependencies
pip install -r requirements.txt

# Or use install script
python install_dependencies.py
```

### Validation
```bash
# Full validation
py -3 validate_repo.py

# Individual checks
py -3 validate_repo.py --compile-only
py -3 validate_repo.py --tests-only
py -3 validate_repo.py --smoke-only
py -3 validate_repo.py --no-smoke
py -3 validate_repo.py --list
py -3 validate_repo.py --json
py -3 -m py_compile agent/execution_analysis.py agent/agent_orchestrator.py agent/real_verifier.py agent/strategy_memory.py memory/user_context.py memory/memory_manager.py build_exe.py
py -3 -m unittest discover -s tests -p "test_*.py"
```

## Architecture

### Core Components

**Main.py** - Application entry point
- Initializes Qt application and system tray
- Creates AriCore instance which manages all threads
- Sets up resource monitoring and garbage collection
- Implements file watcher for auto-reload on code changes (development only)

**core/VoiceCommand.py** - Voice interaction engine
- `VoiceRecognitionThread`: Wake word detection ("아리야") via `simple_wake.py`
- `TTSThread`: Queue-based speech synthesis management
- `CommandExecutionThread`: Executes recognized commands
- Command handlers: YouTube playback, weather, timers, volume control, AI chat
- **Game Mode**: Switch to Fish Audio (Cloud) to free up VRAM from CosyVoice (Local)

**assistant/ai_assistant.py** - LLM/NLU system
- Integrates with Groq/OpenAI providers via `llm_provider.py`
- Context-aware conversation handling
- Supports learning mode and RP (Roleplay) generation

**agent/automation_helpers.py** - GUI / Browser automation helpers
- Exposes reusable helpers for URL opening, app launching, keyboard/mouse input, screenshots, clipboard, window waiting
- Optional Selenium-based browser login flow for sites where credentials/selectors are provided

**agent/execution_analysis.py** - Shared execution analysis rules
- Centralizes failure taxonomy, read-only step detection, and artifact extraction used by orchestrator/verifier/strategy memory

**audio/audio_manager.py** - Audio resource management
- `GlobalAudio`: Singleton PyAudio instance manager
- Separate locks for input (`_audio_input_lock`) and output (`_audio_output_lock`)

**tts/fish_tts_ws.py** - Streaming TTS (Cloud)
- WebSocket-based streaming for low latency
- Optimized for "Game Mode" to minimize GPU usage

**tts/cosyvoice_tts.py** - Local TTS (High Quality)
- High-quality Korean TTS running locally (requires GPU/VRAM)
- Uses a separate worker process to avoid DLL conflicts

### Threading Model

The application uses Qt-based threading (QThread):
1. **VoiceRecognitionThread**: Monitors audio for wake words and handles speech recognition
2. **TTSThread**: Processes the TTS queue to ensure sequential and non-blocking playback
3. **CommandExecutionThread**: Executes commands to keep the UI/Recognition threads responsive
4. **ResourceMonitor**: Monitors memory and triggers garbage collection

### Voice Recognition Flow

1. **Wake Word Detection**: `audio/simple_wake.py`의 `SimpleWakeWord` monitors audio for "아리야" or "시작"
2. **Acknowledgment**: Random response ("네?", "부르셨나요?") via `tts_wrapper`
3. **Wait for TTS**: `handle_wake_word` waits until the acknowledgment TTS is finished
4. **Command Listening**: Captures voice command using Google STR
5. **Command Processing**: `CommandRegistry` finds and executes the matching command
6. **Response**: AI feedback via the active TTS provider

## Key Files and Directories

- `Main.py` - Application entry point
- `core/VoiceCommand.py` - Voice recognition and command orchestration
- `core/threads.py` - QThread implementations for various background tasks
- `tts/fish_tts_ws.py` - Fish Audio streaming TTS implementation
- `tts/cosyvoice_tts.py` - CosyVoice local TTS implementation
- `commands/` - Individual command implementations (Youtube, Weather, etc.)
- `images/` - Character animation sprites

## Development Workflow

### Auto-Reload Feature
Monitors `.py` files for changes and restarts automatically. (Disabled in frozen/EXE mode)

### Important Patterns

#### TTS usage
```python
from VoiceCommand import tts_wrapper
tts_wrapper("메시지")  # Uses the queue, safest way
```

#### Checking TTS Status
```python
from VoiceCommand import is_tts_playing
if is_tts_playing():
    # Wait or handle accordingly
```

#### Adding Commands
Add new command classes in `commands/` and register them in `commands/command_registry.py`.

## Optimization Notes (Recent Fixes)

- **Self-Reflection & Lesson Learning**: Implemented a "Post-mortem" analysis step in `AgentOrchestrator`. When a task fails, the LLM analyzes the failure and stores a "lesson" in `StrategyMemory`, which is then used as context for future plans to avoid repeating the same mistakes.
- **Thinking State Visualization**: Added `set_thinking` signal/slot to `CharacterWidget`. The `AgentOrchestrator` now triggers this "Thinking" state (slower animation + "Thinking..." bubble) during execution for better visual feedback.
- **Memory Optimization & Decay**: Added a confidence decay system and `optimize_memory()` method to `UserContextManager`. Facts now have a TTL and naturally lose confidence over time if not updated, ensuring the user profile stays relevant.
- **UI Modularization**: Extracted shared UI constants (colors, fonts, dimensions, common styles) into `ui/theme.py` and reusable layout components into `ui/common.py`. `text_interface.py`, `settings_dialog.py`, `character_widget.py`, and other panels have been refactored to use this centralized theme architecture.
- **Agent Orchestrator Logging**: Standardized module-level logging in `agent/agent_orchestrator.py` for uniform tracking (`logger.info/warning`).
- **Tests Infrastructure**: Expanded `tests/support.py` with mock objects (`DummyExecutor`, `DummyPlanner`, etc.) for more robust unit tests.
- **TTS Sync**: Added `is_processing` flag to `TTSThread` and `is_tts_playing()` helper to ensure voice recognition doesn't start until TTS finishes.
- **Fish Audio Latency**: Reduced playback termination delay from 10s to 1.5s for faster response in Game Mode.
- **Audio Lock**: Input and Output locks are separated to allow concurrent microphone listening and speaker playback (though usually kept sequential for recognition accuracy).
- **Volume Control**: Ensure `adjust_volume` is defined before `CommandRegistry` initialization in `VoiceCommand.py`.
- **Template-first autonomy**: `agent_planner.py` now prefers deterministic templates for common tasks such as folder creation, search→summarize→save, system info reports, directory listings, and file summarization before falling back to free-form LLM planning.
- **Text UI parity**: `text_interface.py` routes user requests through `AICommand.run_interaction()` so tool calling and agent execution behave consistently across voice and text entry.
- **Document save helper**: `autonomous_executor.py` provides `save_document()` / `choose_document_format()` helpers for txt/md/pdf output.
- **Memory reliability**: `memory/user_context.py` now bounds growth, logs load failures, tracks conversation topics, and supports TTL-backed facts.
- **Strategy retrieval**: `agent/strategy_memory.py` now blends tag overlap with lightweight token similarity instead of relying on coarse tags alone.
- **Execution verification**: `real_verifier.py` checks observed file/path artifacts before falling back to generated verification code and LLM judgment.
- **Integration coverage**: `tests/test_agent_integration.py` executes template planner + executor flows against temporary directories for basic end-to-end regression coverage.

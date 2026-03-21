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

## Architecture

### Core Components

**Main.py** - Application entry point
- Initializes Qt application and system tray
- Creates AriCore instance which manages all threads
- Sets up resource monitoring and garbage collection
- Implements file watcher for auto-reload on code changes (development only)

**VoiceCommand.py** - Voice interaction engine
- `VoiceRecognitionThread`: Wake word detection ("아리야") via `simple_wake.py`
- `TTSThread`: Queue-based speech synthesis management
- `CommandExecutionThread`: Executes recognized commands
- Command handlers: YouTube playback, weather, timers, volume control, AI chat
- **Game Mode**: Switch to Fish Audio (Cloud) to free up VRAM from CosyVoice (Local)

**ai_assistant.py** - LLM/NLU system
- Integrates with Groq/OpenAI providers via `llm_provider.py`
- Context-aware conversation handling
- Supports learning mode and RP (Roleplay) generation

**audio_manager.py** - Audio resource management
- `GlobalAudio`: Singleton PyAudio instance manager
- Separate locks for input (`_audio_input_lock`) and output (`_audio_output_lock`)

**fish_tts_ws.py** - Streaming TTS (Cloud)
- WebSocket-based streaming for low latency
- Optimized for "Game Mode" to minimize GPU usage

**cosyvoice_tts.py** - Local TTS (High Quality)
- High-quality Korean TTS running locally (requires GPU/VRAM)
- Uses a separate worker process to avoid DLL conflicts

### Threading Model

The application uses Qt-based threading (QThread):
1. **VoiceRecognitionThread**: Monitors audio for wake words and handles speech recognition
2. **TTSThread**: Processes the TTS queue to ensure sequential and non-blocking playback
3. **CommandExecutionThread**: Executes commands to keep the UI/Recognition threads responsive
4. **ResourceMonitor**: Monitors memory and triggers garbage collection

### Voice Recognition Flow

1. **Wake Word Detection**: `SimpleWakeWord` monitors audio for "아리야" or "시작"
2. **Acknowledgment**: Random response ("네?", "부르셨나요?") via `tts_wrapper`
3. **Wait for TTS**: `handle_wake_word` waits until the acknowledgment TTS is finished
4. **Command Listening**: Captures voice command using Google STR
5. **Command Processing**: `CommandRegistry` finds and executes the matching command
6. **Response**: AI feedback via the active TTS provider

## Key Files and Directories

- `Main.py` - Application entry point
- `VoiceCommand.py` - Voice recognition and command orchestration
- `threads.py` - QThread implementations for various background tasks
- `fish_tts_ws.py` - Fish Audio streaming TTS implementation
- `cosyvoice_tts.py` - CosyVoice local TTS implementation
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

- **TTS Sync**: Added `is_processing` flag to `TTSThread` and `is_tts_playing()` helper to ensure voice recognition doesn't start until TTS finishes.
- **Fish Audio Latency**: Reduced playback termination delay from 10s to 1.5s for faster response in Game Mode.
- **Audio Lock**: Input and Output locks are separated to allow concurrent microphone listening and speaker playback (though usually kept sequential for recognition accuracy).
- **Volume Control**: Ensure `adjust_volume` is defined before `CommandRegistry` initialization in `VoiceCommand.py`.

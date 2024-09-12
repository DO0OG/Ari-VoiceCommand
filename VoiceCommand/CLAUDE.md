# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

"Ari" (아리) is a Korean-language voice-controlled AI assistant designed to run primarily on Raspberry Pi, with Windows support. It features wake word detection, voice recognition, natural language understanding, and smart home integration via Home Assistant.

## Running the Application

### Raspberry Pi (Primary Platform)
```bash
# Activate virtual environment and run
./start_ari.sh

# Or manually
cd /home/laleme/Ari
source ari/bin/activate
python3 Main.py
```

### Windows
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

# Install spaCy Korean model (optional but recommended)
python -m spacy download ko_core_news_sm
```

## Architecture

### Core Components

**Main.py** - Application entry point
- Initializes Qt application and system tray
- Creates AriCore instance which manages all threads
- Sets up resource monitoring and garbage collection
- Implements file watcher for auto-reload on code changes
- Handles LED controller initialization

**VoiceCommand.py** - Voice interaction engine
- `VoiceRecognitionThread`: Porcupine wake word detection ("아리야") + Vosk/Google STR
- `TTSThread`: Text-to-speech using MeloTTS (Korean)
- `CommandExecutionThread`: Executes recognized commands
- Command handlers: YouTube playback, weather, timers, volume control, smart home
- Music playback: yt-dlp + VLC for YouTube audio streaming

**ai_assistant.py** - NLU and learning system
- BERT (DistilBERT) + GRU neural network for understanding
- Q-learning reinforcement learning for response improvement
- Entity recognition and sentiment analysis using spaCy
- Response similarity matching with cosine similarity
- Auto-saves learned responses to `saved_model/`

**LEDController.py** - Visual feedback (Raspberry Pi only)
- GPIO pin 23 controls LED
- States: ON (100% brightness), TTS (slow pulse), VOICE_RECOGNITION (fast pulse)
- Runs in background thread with PWM control

**Config.py** - Configuration management
- Fetches encrypted API keys from remote server (http://dogs.kro.kr:5000)
- Falls back to local `config.json` if server unavailable
- API keys: weather (공공데이터포털), Picovoice access key

**text_interface.py** - Text chat GUI
- PySide6-based chat interface
- Allows text interaction with AI assistant
- Supports auto-learning commands like "학습: [주제]"
- Chat history save/load functionality

**file_share_server.py** - Discord file sharing
- Discord bot for sending files from `/mnt/` to Discord DMs
- Voice command: "보내 줘 [파일명]"
- Searches for partial filename matches and uploads via Discord

### Threading Model

The application uses Qt-based threading (QThread):
1. **VoiceRecognitionThread**: Continuously listens for wake word, processes voice input
2. **TTSThread**: Queue-based speech synthesis to prevent blocking
3. **CommandExecutionThread**: Queue-based command execution
4. **ResourceMonitor**: Monitors memory and triggers GC when needed
5. **FileSystemWatcher**: Auto-restarts app when .py files change

### Voice Recognition Flow

1. **Wake Word Detection**: Porcupine continuously monitors audio for "아리야"
2. **Acknowledgment**: Random response ("네?", "부르셨나요?")
3. **Command Listening**: 5-second window to capture command
4. **Recognition**: Vosk (offline) → Google STR (fallback if Vosk fails)
5. **Command Processing**: Parsed and executed by CommandExecutionThread
6. **Response**: TTS feedback via MeloTTS

### Command Categories

- **Media**: YouTube search/play, pause, resume, next/previous track, shuffle
- **Information**: Weather (공공데이터포털 API), current time
- **System Control**: Volume adjustment, timers, shutdown timers
- **Smart Home**: PC power on/off via Home Assistant
- **File Sharing**: Upload files to Discord
- **AI Chat**: Fallback to AI assistant for unrecognized commands

## Key Files and Directories

- `Main.py` - Application entry point
- `VoiceCommand.py` - Voice recognition and command execution
- `ai_assistant.py` - AI/NLU core
- `LEDController.py` - Raspberry Pi GPIO LED control
- `Config.py` - Configuration and API key management
- `config.json` - Encrypted API keys (weather, Picovoice)
- `settings.json` - Auto-generated microphone settings
- `saved_model/` - Saved AI model weights and responses
- `logs/` - Application logs (ari_log_YYYYMMDD_HHMMSS.log)
- `images/` - Character animation sprites (idle, walk, drag, fall, sit)
- `vosk-model-ko-0.22/` - Vosk Korean speech recognition model
- `아리야아_ko_*.ppn` - Porcupine wake word files (platform-specific)
- `porcupine_params_ko.pv` - Porcupine Korean model parameters

## Platform-Specific Notes

### Raspberry Pi
- Uses PipeWire audio system (`pw-cli` commands)
- LED control via GPIO pin 23 (BCM numbering)
- Auto-starts with `start_ari.sh` (activates venv at `/home/laleme/Ari/ari`)
- Uses wake word file: `아리야아_ko_raspberry-pi_v3_0_0.ppn`
- Display environment: WAYLAND with DISPLAY=:0

### Windows
- No LED control (LEDController methods become no-ops)
- Uses wake word file: `아리야아_ko_windows_v3_0_0.ppn`
- Audio via standard Windows audio stack

## Configuration

### API Keys (config.json)
```json
{
  "weather_api_key": "encrypted_key",
  "picovoice_access_key": "encrypted_key"
}
```

### Home Assistant Integration
Set these in Config.py via remote server:
- `home_assistant_url` - Home Assistant instance URL
- `home_assistant_token` - Long-lived access token
- Entity used: `input_boolean.pc_power` (PC power control)

### Discord Bot (file_share_server.py)
- `discord_bot_token` - Discord bot token
- `discord_user_id` - Target user ID for file sharing
- `FILEBROWSER_ROOT` - Root path for file search (`/mnt/`)

## Development Workflow

### Auto-Reload Feature
The application monitors .py files for changes and auto-restarts when modifications are detected. This is handled by `FileChangeHandler` (watchdog) in Main.py.

### Logging
All logs go to both console and `logs/ari_log_YYYYMMDD_HHMMSS.log`. Use `logging.info()`, `logging.warning()`, `logging.error()` appropriately.

### Testing Voice Commands
Example Korean commands:
- "유튜브 [곡명] 재생"
- "날씨 어때"
- "몇 시야"
- "10분 타이머"
- "컴퓨터 켜 줘" / "컴퓨터 꺼 줘"
- "볼륨 올려" / "볼륨 내려"
- "[파일명] 보내 줘"

### AI Learning Mode
Voice command: "학습 모드 활성화"
Text interface: "학습: [주제]" or "배워: [주제]"

When active, the assistant asks for feedback after each response and learns from corrections.

## Important Patterns

### TTS with LED Control
```python
from VoiceCommand import tts_wrapper
tts_wrapper("한글 메시지")  # Automatically handles LED state
```

### Direct TTS (without LED)
```python
from VoiceCommand import text_to_speech
text_to_speech("한글 메시지")
```

### Home Assistant Commands
```python
from VoiceCommand import home_assistant_command
home_assistant_command("input_boolean", "turn_on", "input_boolean.pc_power")
```

### LED State Changes
```python
from LEDController import voice_recognition_start, tts_start, idle
voice_recognition_start()  # Fast pulse
tts_start()  # Slow pulse
idle()  # Solid on
```

### Queue-based Threading
```python
# TTSThread and CommandExecutionThread use queues
tts_thread.speak("message")  # Adds to queue
command_thread.execute("command")  # Adds to queue
```

## Weather API Details

Uses 공공데이터포털 (data.go.kr) weather API:
- **초단기실황** (Ultra Short-term Actual): Current conditions
- **단기예보** (Short-term Forecast): Today's high/low, precipitation probability
- Converts lat/lon to Korean grid coordinates via `convert_coord()`
- Forecast times: 02:00, 05:00, 08:00, 11:00, 14:00, 17:00, 20:00, 23:00

## Common Issues

### Microphone Not Found
The app retries 5 times with 2-second delays. Logs will show "마이크를 찾을 수 없습니다" errors. Check:
- PipeWire is running (Raspberry Pi)
- Audio device permissions
- `settings.json` for saved microphone selection

### TTS Model Not Loaded
If "TTS 모델이 초기화되지 않았습니다" appears, check:
- CUDA availability (falls back to CPU)
- MeloTTS installation
- `device` variable is set correctly

### Home Assistant Connection
If "Home Assistant 연결을 확인해주세요" errors occur:
- Verify `get_home_assistant_url()` and `get_home_assistant_token()` return valid values
- Check network connectivity to Home Assistant instance
- Verify `input_boolean.pc_power` entity exists

### File Sharing Fails
Check Discord bot is running and logged in. The bot runs in a background thread and logs "로 로그인했습니다!" when ready.

## Branch Information

- **Main branch**: `main` (stable releases)
- **Current branch**: `For-RaspberryPi` (Raspberry Pi-specific features)
- Recent work: Auto-reload, TTS model changes, computer on/off fixes, shutdown timer fixes

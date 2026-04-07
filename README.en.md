# Ari — AI Voice Assistant

[한국어](./README.md) | [日本語](./README.ja.md) | **English**

> Multilingual (Korean, English, Japanese) Voice AI Assistant for Windows.
> Features Shimeji-style character widget + multiple LLM/TTS provider support.
> Includes a self-improvement loop that learns user patterns and improves over time.

- Character Model: [Jaratang](https://www.pixiv.net/users/78194943)

![preview](https://github.com/user-attachments/assets/fc8de4b7-57ca-4c22-812c-e5dcc7b45cdd)

---

## Key Features

### 1. Interaction & Dialogue
- **Wake Word**: Listens for a call sign with echo cancellation and normalization.
- **Speech Recognition**: Online (Google STT) and Offline (faster-whisper).
- **AI Chat**: Supports Groq, OpenAI, Anthropic, Mistral, Gemini, OpenRouter, NVIDIA NIM, and **Ollama (Local LLM)**.
- **Role-based LLM**: Separate models for chat, planning, and execution/fixing.
- **Multilingual Support**: Full UI and prompt optimization for Korean, English, and Japanese.
- **TTS**: High-quality speech synthesis via Fish Audio, CosyVoice3 (Local), OpenAI, ElevenLabs, and Edge TTS.
- **Emotion Engine**: AI-generated emotion tags like `(joy)` trigger character animations.

### 2. Automation & Execution
- **Autonomous Agent**: Generates and executes Python/Shell code with self-fixing capabilities.
- **Multi-step Planning**: Plan → Execute → Verify loop with parallel DAG execution.
- **Browser Automation**: Login analysis, DOM state tracking, and next-action suggestions.
- **Vision Verification**: 4-stage verification using OCR and LLM.
- **Smart Assistant Mode**: Automatically promotes complex requests to agent tasks.

### 3. Learning & Memory
- **Skill Library**: Automatically extracts and reuse successful patterns.
- **Self-Improvement**: Compiles verified skills into Python code for instant execution.
- **Memory System**: Long-term memory (FACT/BIO/PREF) with SQLite FTS5 search.
- **User Profiling**: Learns user expertise and response style to personalize interactions.
- **Weekly Report**: Automated summaries of success rates and newly learned skills.

---

## Quick Start

### Requirements
- **Python**: 3.11
- **OS**: Windows 10/11
- **RAM**: 4 GB (8 GB+ recommended)
- **GPU**: CUDA support recommended for Local TTS/LLM.

### Installation
```bash
# 1. Clone repository
git clone https://github.com/DO0OG/Ari-VoiceCommand.git
cd Ari-VoiceCommand

# 2. Install dependencies
pip install -r VoiceCommand/requirements.txt

# 3. Run
cd VoiceCommand
py -3.11 Main.py
```

### Language Settings
To change the language:
1. Right-click the tray icon and select **Settings**.
2. Go to the **Device** tab.
3. Select your language (English/Japanese/Korean) in the **Language** section.
4. Click **Save** and restart the application.

---

## Documentation
- [Usage Guide](./docs/USAGE.md)
- [Plugin Guide](./docs/PLUGIN_GUIDE.md)
- [Character Image Guide](./docs/CHARACTER_IMAGES.md)

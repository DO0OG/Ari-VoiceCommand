# 🎙️ Ari — Open-Source AI Voice Assistant for Windows

<div align="center">
  <img src="docs/assets/ari-idle.gif" width="180" alt="Ari desktop assistant character" />
  <p><strong>Talk to your PC. Ari listens, answers, and gets things done on your desktop.</strong></p>
  <p>
    <a href="https://github.com/DO0OG/Ari-VoiceCommand/releases/latest"><img src="https://img.shields.io/github/v/release/DO0OG/Ari-VoiceCommand?display_name=tag&sort=semver" alt="Latest release" /></a>
    <a href="https://github.com/DO0OG/Ari-VoiceCommand/stargazers"><img src="https://img.shields.io/github/stars/DO0OG/Ari-VoiceCommand?style=flat&logo=github" alt="GitHub stars" /></a>
    <img src="https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4?logo=windows&logoColor=white" alt="Windows 10 and 11" />
    <img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white" alt="Python 3.11" />
    <img src="https://img.shields.io/badge/Local%20LLM-Ollama-black" alt="Ollama local LLM support" />
    <img src="https://img.shields.io/badge/Protocol-MCP-7C3AED" alt="Model Context Protocol support" />
    <img src="https://img.shields.io/badge/Languages-KO%20%7C%20EN%20%7C%20JA-orange" alt="Korean, English, Japanese" />
    <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License" />
  </p>
  <p><strong>English</strong> · <a href="./README.ko.md">한국어</a> · <a href="./README.ja.md">日本語</a></p>
  <p>
    <a href="https://github.com/DO0OG/Ari-VoiceCommand/releases/latest"><img src="https://img.shields.io/badge/Download-Latest%20Release-blue?style=for-the-badge" alt="Download the latest Ari release" /></a>
    <a href="https://ari-voice-command.vercel.app"><img src="https://img.shields.io/badge/Visit-Homepage-6c5ce7?style=for-the-badge" alt="Visit Ari homepage" /></a>
    <a href="./docs/USAGE.md"><img src="https://img.shields.io/badge/Read-Usage%20Guide-20a779?style=for-the-badge" alt="Read the usage guide" /></a>
  </p>
</div>

---

Ari is an **open-source AI voice assistant for Windows**. Call it with a wake word or a hotkey, or click the desktop character, and it listens, answers out loud, and gets things done on your PC. Simple commands run locally right away. Bigger jobs are planned, carried out with tools, and checked step by step.

> [!NOTE]
> Ari runs on **Windows 10/11 (64-bit)** only.

## What Ari can do

| Area | Description |
| :--- | :--- |
| **Voice conversation** | Start talking with a wake word, a hotkey, or a click on the character. Answers are spoken sentence by sentence, and you can interrupt at any time. |
| **PC control** | Handles commands such as volume, screenshots, and launching apps, as well as multi-step desktop tasks. |
| **Fast responses** | Common commands are recognized and run on your PC without waiting for an LLM. |
| **Model choice** | Use local Ollama models, hosted providers, or any OpenAI-compatible server. |
| **Speech engines** | Speech recognition with Google or offline Whisper. Speech synthesis with Edge, local CosyVoice3, OpenAI, ElevenLabs, Fish Audio, and more. |
| **Memory** | Remembers what it learns in conversation and brings it up when relevant. Manage it yourself with "remember" and "forget". |
| **Extensions** | Add features with plugins, `SKILL.md` skills, and MCP servers. |
| **Remote commands** | Send commands from Telegram accounts you allow. Off by default. |
| **Character** | A desktop character shows what Ari is doing and how it feels, and speaks up when something happens. |
| **Languages** | Korean, English, Japanese |

## Things you can say

```text
"What time is it?"
"Set the volume to 30%."
"Take a screenshot."
"Which apps are running?"
"Remember that I prefer short answers."
"Forget what I told you about that preference."
```

For more complex requests, the agent makes a plan and works through it step by step. What Ari can actually do depends on the features you enable and the model you choose.

## Install

### Requirements

- Windows 10/11 (64-bit)
- 8 GB RAM recommended
- 4 GB VRAM recommended for running local models on a GPU
- Python 3.11 if you run from source

### Installer

Download `Ari-Setup-<version>.exe` from **[GitHub Releases](https://github.com/DO0OG/Ari-VoiceCommand/releases/latest)** and run it. Ari installs to `Program Files\Ari` by default and keeps settings and history in `%AppData%\Ari`.

### Run from source

```bat
git clone https://github.com/DO0OG/Ari-VoiceCommand.git
cd Ari-VoiceCommand\VoiceCommand
setup.bat
Ari.vbs
```

Use `setup.bat --with-tts` to install local CosyVoice3 as well. If Ari does not start, run `Ari.bat` to see the error.

## Privacy and running locally

With Ollama for the LLM, Whisper for speech recognition, CosyVoice3 for speech synthesis, and local embeddings for memory search, all of that processing stays on your PC. What leaves your PC depends on the providers and features you turn on.

- Remote embeddings and the Telegram integration are off by default.
- Only plugins you approve are loaded. Approved plugins run with the app's permissions and are not sandboxed, so approve only the ones you trust.

## Documentation

The documents below are written in Korean.

- **[User guide](./docs/USAGE.md)** — settings, providers and speech engines, skills, automation examples
- **[Documentation index](./docs/README.md)** — all documents, architecture diagram, local decision evaluation results
- **[Release notes](https://github.com/DO0OG/Ari-VoiceCommand/releases)** — changes in each version
- For developers: [Plugins](./docs/PLUGIN_GUIDE.md) · [MCP server and tools](./docs/MCP_SERVER.md) · [Autonomous agent](./docs/AGENT_ADVANCED.md) · [Local decision engine](./docs/LOCAL_DECISION_ENGINE.md) · [Themes](./docs/THEME_CUSTOMIZATION.md) · [Credentials](./docs/CREDENTIALS.md) · [Contributing](./docs/CONTRIBUTING.md)

Contributions are always welcome.

## Assets & credits

- Default character illustrations by **JAraTang**: <https://www.pixiv.net/users/78194943>
- `DNFBitBitv2` font, official source: <https://df.nexon.com/data/font/dnfbitbitv2>

Check the font's usage terms before redistributing or reusing it outside this project.

## License

Copyright © 2026 [DO0OG (MAD_DOGGO)](https://github.com/DO0OG).

Ari is released under the **MIT License**.

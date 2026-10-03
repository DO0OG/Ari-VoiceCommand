# 🎙️ Ari — 오픈소스 Windows AI 음성 비서 · 데스크톱 자동화 에이전트

<div align="center">
  <img src="docs/assets/ari-idle.gif" width="180" alt="Ari 데스크톱 비서 캐릭터" />
  <p><strong>음성 제어, 데스크톱 자동화, 로컬 AI, 기억, MCP 도구와 캐릭터 비서를 하나의 Windows 앱에서.</strong></p>
  <p>
    <a href="https://github.com/DO0OG/Ari-VoiceCommand/releases/latest"><img src="https://img.shields.io/github/v/release/DO0OG/Ari-VoiceCommand?display_name=tag&sort=semver" alt="최신 릴리스" /></a>
    <a href="https://github.com/DO0OG/Ari-VoiceCommand/stargazers"><img src="https://img.shields.io/github/stars/DO0OG/Ari-VoiceCommand?style=flat&logo=github" alt="GitHub 스타" /></a>
    <img src="https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4?logo=windows&logoColor=white" alt="Windows 10 및 11" />
    <img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white" alt="Python 3.11" />
    <img src="https://img.shields.io/badge/Local%20LLM-Ollama-black" alt="Ollama 로컬 LLM 지원" />
    <img src="https://img.shields.io/badge/Protocol-MCP-7C3AED" alt="Model Context Protocol 지원" />
    <img src="https://img.shields.io/badge/Languages-KO%20%7C%20EN%20%7C%20JA-orange" alt="한국어, 영어, 일본어" />
    <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License" />
  </p>
  <p><a href="./README.md">English</a> · <strong>한국어</strong> · <a href="./README.ja.md">日本語</a></p>
  <p>
    <a href="https://github.com/DO0OG/Ari-VoiceCommand/releases/latest"><img src="https://img.shields.io/badge/다운로드-최신%20릴리스-blue?style=for-the-badge" alt="최신 Ari 릴리스 다운로드" /></a>
    <a href="https://ari-voice-command.vercel.app"><img src="https://img.shields.io/badge/방문-홈페이지-6c5ce7?style=for-the-badge" alt="Ari 홈페이지" /></a>
    <a href="./docs/USAGE.md"><img src="https://img.shields.io/badge/읽기-사용%20가이드-20a779?style=for-the-badge" alt="사용 가이드" /></a>
  </p>
</div>

---

Ari는 Windows에서 말로 부르고 시키는 **오픈소스 AI 음성 비서**입니다. 웨이크워드나 단축키로 부르거나 데스크톱 캐릭터를 클릭해 말을 걸면, 듣고 답하고 PC에서 필요한 일을 대신 합니다. 간단한 명령은 PC 안에서 바로 처리하고, 여러 단계가 필요한 일은 계획을 세워 도구를 쓰고 결과를 확인합니다.

> [!NOTE]
> Ari는 **Windows 10/11 (64-bit)** 전용입니다.

## 할 수 있는 일

| 영역 | 설명 |
| :--- | :--- |
| **음성 대화** | 웨이크워드, 단축키, 캐릭터 클릭으로 말을 겁니다. 답은 문장 단위로 바로 들려주고, 말하는 도중에 끊을 수 있습니다. |
| **PC 조작** | 볼륨, 스크린샷, 앱 실행 같은 명령부터 여러 단계에 걸친 데스크톱 작업까지 처리합니다. |
| **빠른 응답** | 자주 쓰는 명령은 LLM을 거치지 않고 PC 안에서 바로 판정해 실행합니다. |
| **모델 선택** | Ollama 로컬 모델, 호스팅 제공자, OpenAI 호환 서버 가운데 골라 씁니다. |
| **음성 엔진** | 음성 인식은 Google과 오프라인 Whisper, 음성 합성은 Edge, 로컬 CosyVoice3, OpenAI, ElevenLabs, Fish Audio 등을 지원합니다. |
| **기억** | 대화에서 알게 된 내용을 기억했다가 필요할 때 꺼내 씁니다. "기억해줘", "잊어줘"로 직접 관리할 수 있습니다. |
| **확장** | 플러그인, `SKILL.md` 스킬, MCP 서버로 기능을 더합니다. |
| **원격 명령** | 허용한 Telegram 계정에서 명령을 보낼 수 있습니다. 기본으로 꺼져 있습니다. |
| **캐릭터** | 데스크톱 캐릭터가 상태와 기분을 보여 주고 상황에 맞춰 말을 겁니다. |
| **언어** | 한국어, 영어, 일본어 |

## 이렇게 말해 보세요

```text
"지금 몇 시야?"
"볼륨 30%로 해줘."
"스크린샷 찍어줘."
"실행 중인 앱 알려줘."
"나는 짧은 답변을 선호한다고 기억해줘."
"아까 말한 그 취향은 잊어줘."
```

더 복잡한 요청은 에이전트가 계획을 세워 단계별로 처리합니다. 실제로 할 수 있는 일은 켜 둔 기능과 고른 모델에 따라 달라집니다.

## 설치

### 요구 사항

- Windows 10/11 (64-bit)
- RAM 8GB 권장
- GPU로 로컬 모델을 돌리려면 VRAM 4GB 권장
- 소스에서 실행하려면 Python 3.11

### 설치본

**[GitHub Releases](https://github.com/DO0OG/Ari-VoiceCommand/releases/latest)**에서 `Ari-Setup-<version>.exe`를 내려받아 실행하세요. 기본 설치 위치는 `Program Files\Ari`이고, 설정과 기록은 `%AppData%\Ari`에 저장됩니다.

### 소스에서 실행

```bat
git clone https://github.com/DO0OG/Ari-VoiceCommand.git
cd Ari-VoiceCommand\VoiceCommand
setup.bat
Ari.vbs
```

로컬 CosyVoice3까지 설치하려면 `setup.bat --with-tts`를 쓰세요. 시작이 안 될 때는 `Ari.bat`로 실행하면 오류를 볼 수 있습니다.

## 개인정보와 로컬 구성

LLM은 Ollama, 음성 인식은 Whisper, 음성 합성은 CosyVoice3, 기억 검색은 로컬 임베딩으로 두면 이 처리들은 PC 안에서 끝납니다. 어떤 데이터가 밖으로 나가는지는 켜 둔 제공자와 기능에 따라 달라집니다.

- 원격 임베딩과 Telegram 연동은 기본으로 꺼져 있습니다.
- 플러그인은 사용자가 승인한 것만 불러옵니다. 승인한 플러그인은 격리 없이 앱 권한으로 실행되므로 믿을 수 있는 것만 승인하세요.

## 문서

- **[사용 가이드](./docs/USAGE.md)** — 설정, 제공자와 음성 엔진, 스킬, 자동화 예시
- **[문서 모음](./docs/README.md)** — 전체 문서 색인, 동작 구조, 로컬 판정 평가 결과
- **[릴리스 노트](https://github.com/DO0OG/Ari-VoiceCommand/releases)** — 버전별 변경 사항
- 개발자용: [플러그인](./docs/PLUGIN_GUIDE.md) · [MCP 서버와 도구](./docs/MCP_SERVER.md) · [자율 에이전트](./docs/AGENT_ADVANCED.md) · [로컬 판정 엔진](./docs/LOCAL_DECISION_ENGINE.md) · [테마](./docs/THEME_CUSTOMIZATION.md) · [인증 정보](./docs/CREDENTIALS.md) · [기여 가이드](./docs/CONTRIBUTING.md)

기여는 언제나 환영합니다.

## 에셋 및 크레딧

- 기본 캐릭터 이미지 — **JAraTang**: <https://www.pixiv.net/users/78194943>
- `DNFBitBitv2` 폰트 — 공식 출처: <https://df.nexon.com/data/font/dnfbitbitv2>

프로젝트 밖으로 재배포하거나 다시 사용할 때는 해당 폰트의 이용 조건을 확인해 주세요.

## 라이선스

Copyright © 2026 [DO0OG (MAD_DOGGO)](https://github.com/DO0OG).

Ari는 **MIT License**로 배포됩니다.

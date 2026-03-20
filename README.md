# Ari (아리) — AI 음성 어시스턴트

> 한국어 음성 인식 기반 데스크탑 AI 어시스턴트.
> Shimeji 스타일 캐릭터 위젯 + 다중 LLM / TTS 제공자 선택 지원.

- 캐릭터 모델 제작 : [자라탕](https://github.com/yongmen20)

![preview](https://github.com/user-attachments/assets/fc8de4b7-57ca-4c22-812c-e5dcc7b45cdd)

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| **웨이크워드** | "아리야" 호출 → 음성 입력 대기 |
| **음성 인식** | Google STT (기본) |
| **AI 대화** | Groq · OpenAI · Anthropic · Mistral · Gemini · OpenRouter 선택 |
| **감정 표현** | AI가 내용에 따라 (기쁨), (슬픔) 등 태그를 생성하고 캐릭터가 반응 |
| **TTS** | Fish Audio · CosyVoice3(로컬) · OpenAI TTS · ElevenLabs · Edge TTS 선택 |
| **캐릭터 위젯** | Shimeji 스타일 드래그·물리 애니메이션 |
| **스마트 모드** | AI가 상황을 판단하여 도구(타이머, 날씨 등) 자동 실행 |
| **미디어** | 유튜브 오디오 스트리밍 (yt-dlp + VLC) |

---

## 빠른 시작

```bash
# 1. 의존성 설치
pip install -r VoiceCommand/requirements.txt

# 2. 실행 (Windows)
cd VoiceCommand
python Main.py
```

### 로컬 TTS (CosyVoice3) 설치
고품질 로컬 TTS를 사용하려면 아래 스크립트를 실행하세요 (GPU 권장).
```bash
python VoiceCommand/install_cosyvoice.py
```

---

## 설정

앱 트레이 아이콘 우클릭 → **설정** 에서 3개의 탭으로 구분된 설정을 관리할 수 있습니다.

1. **RP 설정**: 캐릭터의 성격 및 대화 지침 설정
2. **AI & TTS 설정**: 사용할 엔진 및 API 키 관리
3. **장치 설정**: 마이크 입력 장치 선택

---

## 캐릭터 커스터마이징

`VoiceCommand/images/` 폴더 내의 PNG 파일들을 교체하여 자신만의 캐릭터를 만들 수 있습니다. 

### 이미지 규칙 (요약)
- **형식**: 배경이 투명한 PNG
- **파일명**: `동작이름번호.png` (예: `idle1.png`, `walk1.png`)
- **동작 종류**: `idle`, `walk`, `drag`, `fall`, `sit`, `surprised`, `sleep`, `climb` 등

> 💡 **상세 제작 가이드**: [CHARACTER_IMAGES.md](VoiceCommand/CHARACTER_IMAGES.md) 파일을 확인하세요.

---

## 아키텍처 (모듈화 완료)

```
Main.py                  ← Qt 앱 진입점, 트레이, 리소스 모니터
VoiceCommand.py          ← 핵심 비즈니스 로직 및 오케스트레이션
threads.py               ← 음성 인식, TTS, 명령 실행 전용 스레드 분리
audio_manager.py         ← 전역 오디오 및 스레드 락 관리
tts_factory.py           ← TTS 제공자 동적 생성 팩토리
│
├── commands/            ← 명령 패턴 (BaseCommand 구현체들)
│   ├── ai_command.py    ← LLM fallback + tool calling
│   └── ...
│
├── images/              ← 캐릭터 애니메이션 PNG 프레임
└── ...
```

---

## 빌드 (EXE)

Nuitka를 사용하여 최적화된 단일 폴더/파일 빌드를 지원합니다.
```bash
python build_exe.py           # 증분 빌드 (빠름)
python build_exe.py --onefile  # 배포용 단일 파일 빌드
```

---

## 라이선스

MIT License — 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.

## 연락처

- 이슈: [github.com/DO0OG/AI-Assistant/issues](https://github.com/DO0OG/AI-Assistant/issues)
- 이메일: mad_doggo@dogdev.buzz

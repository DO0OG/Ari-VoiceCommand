# Ari (아리) — AI 음성 어시스턴트

> 한국어 음성 인식 기반 데스크탑 AI 어시스턴트.
> Shimeji 스타일 캐릭터 위젯 + 다중 LLM / TTS 제공자 선택 지원.

- 캐릭터 모델 제작 : [자라탕](https://github.com/yongmen20)

![preview](https://github.com/user-attachments/assets/fc8de4b7-57ca-4c22-812c-e5dcc7b45cdd)

---

## 개발 현황

### 최근 업데이트 (2026-03-23)

- **코드 구조 정리**: 자율 실행 핵심 구현을 `VoiceCommand/agent/`, 웹 연동 구현을 `VoiceCommand/services/`로 재배치하고, 루트에는 호환 wrapper를 남겨 기존 import 경로를 유지했습니다.
- **영역별 패키지 분리**: UI는 `VoiceCommand/ui/`, TTS 제공자는 `VoiceCommand/tts/`, 기억/컨텍스트 관리는 `VoiceCommand/memory/`로 정리해 결합도를 낮췄습니다.
- **패키지 우선 import 정리**: 내부 구현 간 의존은 가능한 한 `core.*`, `agent.*`, `ui.*`, `tts.*`, `memory.*`, `services.*` 경로를 직접 사용하도록 정리했고, 루트 파일은 주로 호환 목적의 얇은 wrapper로 남겼습니다.
- **범용 자율 실행 템플릿 확장**: 뉴스 검색·요약·저장뿐 아니라 폴더 생성, 시스템 정보 보고서 저장, 파일 요약 저장, 디렉터리 목록 저장 등 자주 쓰는 작업군을 LLM 자유 생성보다 먼저 안정적인 템플릿으로 처리하도록 개선했습니다.
- **텍스트 UI 자율 실행 통합**: 채팅창 입력도 음성과 동일한 `AICommand → tool call → orchestrator` 경로를 사용하도록 수정하여, 텍스트 대화에서도 실제 작업 수행이 가능해졌습니다.
- **문서 저장 자동 포맷 선택**: `save_document()` 도우미를 추가하여 결과 구조에 따라 `txt`, `md`, `pdf`를 자동 선택하거나 사용자가 지정한 포맷으로 저장할 수 있습니다.
- **웹 검색 폴백 강화**: `ddgs` 우선 사용 + DuckDuckGo HTML 폴백으로, 별도 검색 패키지 상태에 따라 자율 실행이 멈추지 않도록 보강했습니다.
- **감정 태그 UI 정리**: `(진지)`뿐 아니라 `[진지]`, `[기쁨]` 형태도 말풍선과 텍스트 UI에서 이모지 기반 표시로 정리되도록 수정했습니다.
- **GUI / 브라우저 자동화 헬퍼 추가**: `open_url`, `open_path`, `launch_app`, `click_screen`, `type_text`, `hotkey`, `take_screenshot`, `wait_for_window`, `browser_login` 등의 헬퍼를 실행 환경에 주입하여 앱 실행·브라우저 조작·기본 GUI 자동화 기반을 확장했습니다.
- **자율 실행 도구 주입**: AI가 생성하는 Python 코드 내에서 `web_search`, `web_fetch`를 별도 도구 호출 없이 즉시 호출 가능하도록 환경을 개선했습니다.
- **에이전트-캐릭터 감정 연동**: 에이전트의 실행 상태(계획 수립, 코드 수정, 목표 달성 등)에 따라 캐릭터가 [진지], [걱정], [기쁨] 등 감정 애니메이션을 자동으로 수행합니다.
- **스케줄러 표현식 확장**: `ProactiveScheduler`에 "매시간", "N일 후" 등 다양한 반복 및 스케줄 파싱 로직을 추가하여 자율 작업 예약 능력을 강화했습니다.
- **웹 검색 요약 파이프라인**: 검색 결과를 단순히 나열하지 않고, LLM이 구어체로 3문장 이내 요약하여 TTS로 응답하는 최적화된 흐름을 구현했습니다.
- **UI 시각화 및 안정성**: 위험 작업 확인 다이얼로그의 위험 요소를 HTML 리스트로 시각화하여 가독성을 높였으며, `StrategyMemory` 태그 확장으로 과거 경험 회상 능력을 개선했습니다.
- **자율 실행 엔진**: AI가 Python/Shell 코드를 직접 생성·실행하며, 실패 시 LLM이 자동으로 코드를 수정해 재시도합니다.
- **3레이어 에이전트 루프**: 복잡한 목표를 Plan → Execute+Self-Fix → Verify 순서로 처리합니다. 목표 미달성 시 이전 결과를 컨텍스트로 삼아 최대 4회 재계획합니다.
- **안전 검사기**: 코드/명령을 SAFE · CAUTION · DANGEROUS 3단계로 분류하며, 위험한 작업은 15초 카운트다운 확인 다이얼로그를 통해 사용자 승인을 요청합니다.


### 구현 완료

| 기능 | 설명 |
|------|------|
| **웨이크워드** | Porcupine "아리야" + SimpleWakeWord(Google STT) 폴백 |
| **음성 인식** | Google STT (기본) · Vosk 오프라인 옵션 |
| **AI 대화** | Groq · OpenAI · Anthropic · Mistral · Gemini · OpenRouter 선택 |
| **감정 표현** | AI 태그(`(기쁨)` 등) 기반 캐릭터 애니메이션 반응 |
| **TTS** | Fish Audio WS · CosyVoice3(로컬) · OpenAI TTS · ElevenLabs · Edge TTS 선택 |
| **캐릭터 위젯** | Shimeji 스타일 드래그 · 물리 엔진 · 마우스 반응 |
| **스마트 모드** | LLM tool calling으로 타이머 · 날씨 · 유튜브 등 자동 실행 |
| **자율 실행** | Python / Shell 코드 생성·실행 + LLM 자동 수정(Self-Fix) |
| **에이전트 루프** | 복잡한 목표를 Plan→Execute→Verify 3레이어로 자율 처리 (최대 4회 재계획) |
| **작업 템플릿** | 폴더 생성, 검색·요약·저장, 시스템 정보 보고서, 디렉터리 목록, 파일 요약 등 자주 쓰는 작업군을 규칙 기반으로 우선 처리 |
| **문서 저장** | 결과 구조에 따라 `txt` · `md` · `pdf` 자동 저장 또는 사용자 지정 포맷 저장 |
| **GUI 자동화 기반** | 앱 실행, URL 열기, 키 입력, 마우스 클릭, 스크린샷, 클립보드 제어, 창 대기, Selenium 기반 로그인 자동화 |
| **안전 검사** | 실행 전 위험 수준 3단계 분류 + 위험 작업 확인 다이얼로그 (15초 카운트다운) |
| **미디어** | 유튜브 오디오 스트리밍 (yt-dlp + VLC) |
| **기억 시스템** | FACT/BIO/PREF 태그 기반 장기 기억 (LTM/STM) |
| **설정 UI** | 트레이 아이콘 기반 3탭 설정창 (RP · AI&TTS · 장치) |
| **텍스트 인터페이스** | PySide6 채팅 UI (음성 없이 텍스트로 대화 가능) |
| **계산기** | 수식 음성 인식 및 계산 |
| **빌드 시스템** | Nuitka 기반 EXE 빌드 (단일 파일 · 폴더 선택) |

### 개선 여지

| 항목 | 내용 |
|------|------|
| `load_context` bare except | `user_context.py` 파일 로드 실패 시 예외 종류·로그 없이 조용히 무시됨 |
| 크기 상한 누락 | `command_sequences` · `command_frequency` 딕셔너리 무제한 성장 가능 |
| `user_bio` 리스트 상한 | `interests` · `memos` 리스트에 크기 제한 없음 |
| `conversation_topics` 미사용 | 데이터 구조에 정의되어 있으나 실제로 기록하는 코드 없음 (stub 상태) |

### 추후 개발

| 기능 | 설명 |
|------|------|
| **Discord 파일 공유** | 파일 전송 명령 commands/ 모듈로 재구현 (현재 미이식) |
| **알람** | 특정 시각 지정 알림 (현재 카운트다운 타이머만 지원) |
| **대화 주제 분석** | `conversation_topics` 실제 집계 및 컨텍스트 프롬프트 활용 |

### 다음 구현 우선순위

1. **파일 작업군 확대**
   파일 이름 변경, 병합, 정리, CSV/JSON 분석, 로그 리포트 자동 생성
2. **GUI 자동화 강화**
   창 찾기, 포커스 전환, 좌표 기반 클릭을 넘어 앱 상태 인식 기반 자동화 확장
3. **브라우저 워크플로우 강화**
   로그인 이후 반복 작업, 다운로드 처리, 페이지별 selector 전략 축적
4. **플래너 모델 분리**
   실행용 LLM과 플래너/검증용 LLM을 분리해 전체 안정성 향상
5. **검증 계층 강화**
   파일/폴더 존재 확인 외에 GUI 상태, 브라우저 상태, 앱 상태 검증 추가
6. **안전 정책 정교화**
   위험 작업 범주 세분화, 앱/사이트별 허용 정책, 사용자 승인 UX 개선

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
| **자율 실행** | AI가 Python/Shell 코드를 생성하고 직접 실행, 오류 시 자동 수정 |
| **결과 저장 형식** | `txt`, `md`, `pdf`, 자동 선택(`auto`) 지원 |
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

## 아키텍처

```
Main.py                     ← Qt 앱 진입점
VoiceCommand.py             ← 호환 wrapper (실제 구현: core/VoiceCommand.py)
llm_provider.py             ← 호환 wrapper (실제 구현: agent/llm_provider.py)
tts_factory.py              ← 호환 wrapper (실제 구현: tts/tts_factory.py)
│
├── commands/               ← 커맨드 패턴 기반 도구 모음 (BaseCommand 구현체)
│   ├── ai_command.py       ← LLM 대화 및 Tool Calling 처리, 에이전트 루프 진입점
│   ├── youtube_command.py  ← 유튜브 검색 및 재생 제어
│   └── ...
│
├── core/                   ← 앱 런타임 핵심 로직
│   ├── VoiceCommand.py        ← 음성 인식-판단-실행 오케스트레이션
│   ├── threads.py             ← 음성 인식 / TTS / 명령 실행 스레드
│   ├── config_manager.py      ← 설정 로드/저장
│   ├── constants.py           ← 전역 상수
│   ├── core_manager.py        ← 앱 코어 초기화/관리
│   ├── resource_manager.py    ← 리소스 관리
│   └── rp_generator.py        ← 페르소나/RP 문장 생성
│
├── assistant/              ← LLM 어시스턴트 레이어
│   ├── ai_assistant.py        ← 통합 AI 어시스턴트
│   └── groq_assistant.py      ← Groq 기반 보조 어시스턴트 경로
│
├── audio/                  ← 오디오 입력 및 웨이크워드
│   ├── audio_manager.py       ← 전역 오디오 장치/락 관리
│   └── simple_wake.py         ← 웨이크워드 감지
│
├── ui/                     ← PySide6 기반 UI 구성요소
│   ├── text_interface.py      ← 채팅창 UI
│   ├── tray_icon.py           ← 시스템 트레이
│   ├── settings_dialog.py     ← 설정창
│   ├── speech_bubble.py       ← 말풍선 위젯
│   └── character_widget.py    ← 캐릭터 위젯/애니메이션
│
├── tts/                    ← TTS 제공자 및 팩토리
│   ├── tts_factory.py         ← 제공자 선택 팩토리
│   ├── tts_openai.py          ← OpenAI TTS
│   ├── tts_edge.py            ← Edge TTS
│   ├── tts_elevenlabs.py      ← ElevenLabs TTS
│   ├── cosyvoice_tts.py       ← CosyVoice 로컬 TTS
│   ├── fish_tts_ws.py         ← Fish Audio WS TTS
│   └── cosyvoice_worker.py    ← CosyVoice 워커 프로세스
│
├── memory/                 ← 대화 이력 및 사용자 기억
│   ├── memory_manager.py      ← FACT/BIO/PREF 기반 기억 관리
│   ├── user_context.py        ← 사용자 컨텍스트 저장/로드
│   └── conversation_history.py ← 대화 기록 저장/조회
│
├── agent/                  ← 자율 실행 핵심 구현
│   ├── agent_orchestrator.py  ← Plan → Execute+Self-Fix → Verify 3레이어 루프
│   ├── agent_planner.py       ← 목표 프로파일링 + 템플릿 계획 + LLM 기반 보조 분해/수정
│   ├── autonomous_executor.py ← Python/Shell 실행기 + 문서 저장 + runner 기반 격리 실행
│   ├── automation_helpers.py  ← GUI / 브라우저 / 앱 자동화 공통 헬퍼
│   ├── llm_provider.py        ← 다중 LLM 제공자 통합 및 tool routing
│   ├── real_verifier.py       ← 부작용 없는 실행 검증기
│   ├── safety_checker.py      ← 코드/명령 위험 수준 분류
│   └── ...
│
├── services/               ← 외부 웹/서비스 연동
│   ├── web_tools.py           ← 검색 / 웹 페이지 fetch / HTML 폴백
│   ├── weather_service.py     ← 날씨 조회
│   └── timer_manager.py       ← 타이머 관리
│
├── images/                 ← 캐릭터 애니메이션 PNG 프레임 (Shimeji 규격)
└── ...
```

### 자율 실행 흐름

```
사용자 음성 요청
     │
     ▼
 LLM (chat_with_tools)
     │
     ├── 단순 도구 호출 (타이머, 날씨 등) ──────────────────────────────► 즉시 실행
     │
     ├── execute_python_code / execute_shell_command
     │        │
     │        ▼
     │   SafetyChecker (SAFE/CAUTION/DANGEROUS 분류)
     │        │
     │        ├── SAFE    → 즉시 실행
     │        ├── CAUTION → TTS 경고 후 실행
     │        └── DANGEROUS → 확인 다이얼로그 (15초 카운트다운)
     │                │
     │                ▼
     │   AgentOrchestrator.execute_with_self_fix()
     │        │ 실패 시 LLM이 코드 수정 후 재시도 (최대 2회)
     │        ▼
     │   실행 결과 → LLM 피드백 → 최종 TTS 응답
     │
     └── run_agent_task (복잡한 다단계 목표)
              │
              ▼
         AgentOrchestrator.run()
              │
              ├── Layer 1: AgentPlanner.decompose() → 템플릿 계획 또는 LLM 계획 생성
              ├── Layer 2: 각 단계 실행 + 실패 시 LLM 자동 수정 (Self-Fix)
              │           단계 간 출력을 step_outputs 딕셔너리로 전달
              └── Layer 3: AgentPlanner.verify() → 목표 달성 검증
                           미달성 시 컨텍스트 포함 재계획 (최대 4회 반복)
```

### 현재 강한 작업군

- 폴더 생성 및 바탕화면 결과 저장
- 웹 검색 → 요약 → 문서 저장
- 오늘 뉴스 검색 → 기사 본문 일부 수집 → 구조화 요약 저장
- 시스템 정보 수집 → 보고서 저장
- 로컬 텍스트/마크다운/로그/JSON/CSV 파일 요약 저장
- 디렉터리 목록 생성 및 저장
- URL 열기, 앱 실행, 기본 GUI 클릭/입력 자동화
- Selenium 기반 브라우저 로그인 자동화 (환경/사이트 구조 의존)

### 아직 한계가 있는 영역

- 사이트별 DOM 구조가 크게 다른 로그인/인증 흐름
- 복잡한 GUI 클릭 시퀀스와 앱별 내부 워크플로의 높은 변동성
- 외부 앱의 비표준 UI 자동화
- 사용자의 로컬 환경에 강하게 의존하는 특수 작업
- MFA / CAPTCHA / 보안 키 등 추가 인증이 필요한 사이트

---

## 기억 시스템 (LTM / STM)

Ari는 대화 중 AI 응답에 포함된 특수 태그를 분석하여 장기 기억을 자동으로 구축합니다.

### 태그 형식

| 태그 | 형식 | 예시 |
|------|------|------|
| `[FACT:]` | `[FACT: key=value]` | `[FACT: 취미=코딩]` |
| `[BIO:]` | `[BIO: field=value]` | `[BIO: name=홍길동]` |
| `[PREF:]` | `[PREF: category=value]` | `[PREF: 음악장르=로파이]` |

- **FACT**: 사용자에 대한 단편적 사실 (`user_context.json` → `facts` 저장)
- **BIO**: 이름·관심사 등 기본 프로필 정보 (`user_bio` 갱신)
- **PREF**: 카테고리별 선호도 빈도 기록 (`preferences` 누적)

### 데이터 상한

| 항목 | 상한 | 초과 시 정책 |
|------|------|-------------|
| `facts` | 100개 | `updated_at` 기준 오래된 항목부터 삭제 |
| `time_patterns` (슬롯당) | 20개 | 오래된 항목(앞쪽)부터 제거 |
| `preferences` (카테고리당) | 50개 | 빈도 낮은 항목부터 제거 |

기억 데이터는 `VoiceCommand/user_context.json`에 저장되며, `MemoryManager`가 매 대화마다 태그를 추출하여 자동 갱신합니다.

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
- 이메일: laleme@naver.com

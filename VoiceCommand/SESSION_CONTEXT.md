# Session Context: Ari Voice Assistant Project

이 파일은 AI 세션(Gemini, Claude 등) 간 프로젝트 상태를 공유하기 위한 문서입니다.
새 세션 시작 시 이 파일을 가장 먼저 제공하세요.

## Last Updated: 2026-03-23 (Session: Agent Package Refactor, Verification Fixes & Bubble Consistency)
## Autonomy Level: 자율 실행 범위 확장 + 열기 작업/검증/TTS 말풍선 동기화 보강 완료

---

## 1. 프로젝트 개요

"아리(Ari)"는 Windows 전용 한국어 음성 AI 어시스턴트입니다.
- 웨이크워드 "아리야" 감지 → 음성 인식 → 명령 실행 → TTS 응답
- LLM: Groq (기본, llama-3.3-70b-versatile) / OpenAI / Anthropic / Mistral / Gemini / OpenRouter
- TTS: Fish Audio (Cloud, Game Mode) / CosyVoice (Local, 고품질)
- UI: PySide6 시스템 트레이 + 캐릭터 애니메이션 (Shimeji 스타일)
- 진입점: `Main.py` → `VoiceCommand.py` → `CommandRegistry` → 각 Command 클래스
- 현재 구조 정리:
  - 핵심 자율 실행 구현: `VoiceCommand/agent/`
  - 웹 연동 구현: `VoiceCommand/services/`
  - UI 모듈: `VoiceCommand/ui/`
  - TTS 제공자/팩토리: `VoiceCommand/tts/`
  - 기억/대화 이력: `VoiceCommand/memory/`
  - 앱 런타임 핵심: `VoiceCommand/core/`
  - AI 어시스턴트 레이어: `VoiceCommand/assistant/`
  - 오디오/웨이크워드: `VoiceCommand/audio/`
  - 내부 구현 import는 패키지 경로(`core.*`, `agent.*`, `ui.*`, `tts.*`, `memory.*`, `services.*`) 우선으로 정리됨
  - 루트의 `llm_provider.py`, `text_interface.py`, `tts_factory.py`, `memory_manager.py` 등은 하위 패키지로 연결하는 호환 wrapper

---

## 2. 자율 실행 아키텍처

### 2.1 계층 구조

```
사용자 음성/텍스트
    ↓
[llm_provider] _build_system() 시 실시간 '감각 데이터' 주입
    ├── 위치(X, Y), 화면 상태(전체화면/일반), 현재 동작 상태 포함
    └── AI가 도구 호출 없이도 자신의 물리적 처지를 인지 가능
    ↓
[AICommand] execute(text)
    ↓ chat_with_tools()
[LLMProvider] tool call 결정
    ├── 단순 도구 (play_youtube, set_timer, 날씨 등)
    │       ↓ dispatch table
    │   각 핸들러 직접 실행
    │
    ├── execute_python_code / execute_shell_command
    │       ↓
    │   [AgentOrchestrator] execute_with_self_fix()
    │       ↓ 실패 시 [AgentPlanner] fix_step()
    │   [AutonomousExecutor] run_python / run_shell
    │
    └── run_agent_task (복잡한 다단계 목표)
            ↓
        [AgentOrchestrator] run(goal)
        ├── Layer 1: [AgentPlanner] decompose() — 단계 분해
        │       └── [StrategyMemory] 과거 유사 전략 주입
        ├── Layer 2: _execute_plan() — 순차 실행
        │       ├── on_failure 정책 (abort/skip/continue)
        │       └── _execute_step_with_retry() → fix_step()
        └── Layer 3: [RealVerifier] verify()
                ├── LLM이 생성한 검증 코드 실행 → True/False
                └── 실패 시 [AgentPlanner] verify() (LLM 텍스트 폴백)
```

---

## 3. 오늘 세션에서 수정한 것들 (2026-03-23)

### 3.1 수정된 파일 목록

| 파일 | 수정 내용 | 상태 |
|------|----------|------|
| `user_context.json` | 오염된 FACT (귀가 시간, 요청내용) 2회 삭제 | ✅ |
| `llm_provider.py` | FACT 저장 기준 강화 (일시적 상태 금지) | ✅ |
| `llm_provider.py` | get_screen_status 도구 사용 지침 추가 | ✅ |
| `llm_provider.py` | max_tokens 300→1000, temperature 0.7→0.3 | ✅ |
| `llm_provider.py` | web_search query 한국어 강제 지침 | ✅ |
| `llm_provider.py` | run_agent_task description 강화 | ✅ |
| `llm_provider.py` | 지침 7번 신규: 텍스트 가짜 명령 금지 | ✅ |
| `llm_provider.py` | _filter_korean: 가짜 명령 블록·파일 경로 사전 제거 | ✅ |
| `llm_provider.py` | **시스템 프롬프트 길이 최적화 (토큰 압박 완화)** | ✅ |
| `llm_provider.py` | **raw_msg에서 가짜 도구 호출 사전 감지(폴백) 로직 추가** | ✅ |
| `ari_settings.json` | system_prompt 규칙 3: 명시적 질문 시 도구 우선 | ✅ |
| `agent_orchestrator.py` | _group_by_dependency: 병렬→순차 실행으로 전환 | ✅ |
| `agent_orchestrator.py` | _verify: 폴백 보수화, 실패 단계 있으면 즉시 False | ✅ |
| `agent_planner.py` | _DECOMPOSE_PROMPT: Windows 경로, makedirs, condition 강화 | ✅ |
| `agent_planner.py` | _FIX_PROMPT: Windows 경로 경고 추가 | ✅ |
| `agent_planner.py` | _VERIFY_PROMPT: 불확실 시 false 반환 지침 | ✅ |
| `real_verifier.py` | _VERIFY_CODE_PROMPT: Windows 경로 예시 추가 | ✅ |
| `memory_manager.py` | _EPHEMERAL_FACT_KEYS: 22개 일시적 키 차단 | ✅ |
| `memory_manager.py` | _is_persistent_fact(): FACT 저장 전 검증 | ✅ |
| `memory_manager.py` | clean_response(): 일본어·CJK 한자 제거 | ✅ |
| `commands/ai_command.py` | **사용 중단된 _parse_pseudo_tool_calls 로직 삭제** | ✅ |
| `autonomous_executor.py` | **execution_globals에 desktop_path 변수 주입** | ✅ |
| `llm_provider.py` | **요청 의도 분석 기반 tool_choice 강화 (screen / schedule / multi-step)** | ✅ |
| `llm_provider.py` | **tool call 실패 시 실행형 요청을 run_agent_task 등으로 자동 승격** | ✅ |
| `llm_provider.py` | **tool trace 로그(`logs/tool_trace_YYYYMMDD.log`) 추가** | ✅ |
| `agent_planner.py` | **planner raw trace 로그(`logs/planner_trace_YYYYMMDD.log`) 추가** | ✅ |
| `agent_planner.py` | **균형 괄호 기반 JSON 추출로 파싱 복원력 강화** | ✅ |
| `real_verifier.py` | **verification code trace 로그(`logs/verifier_trace_YYYYMMDD.log`) 추가** | ✅ |
| `text_interface.py` | **텍스트 UI도 AICommand 자율 실행 경로 재사용** | ✅ |
| `web_tools.py` | **ddgs 우선 사용 + DuckDuckGo HTML 폴백 검색 추가** | ✅ |
| `VoiceCommand.py` | **[진지]/(진지) 감정 태그 통합 파싱 및 UI 이모지 정리** | ✅ |
| `autonomous_executor.py` | **save_document / choose_document_format / PDF 저장 지원 추가** | ✅ |
| `agent_planner.py` | **템플릿 작업군 확장: 폴더 생성 / 뉴스 검색·요약·저장 / 파일 요약 / 시스템 정보 / 디렉터리 목록** | ✅ |
| `agent_planner.py` | **LLM fix_step 실패 시 규칙 기반 heuristic 복구 추가** | ✅ |
| `requirements.txt` | **ddgs, reportlab 의존성 반영** | ✅ |
| `build_exe.py` | **ddgs/reportlab/psutil 패키지 포함 갱신** | ✅ |
| `automation_helpers.py` | **GUI / 브라우저 / 앱 자동화 공통 헬퍼 신설** | ✅ |
| `autonomous_executor.py` | **GUI/브라우저 자동화 헬퍼 주입(open_url, launch_app, click/type, screenshot, clipboard, browser_login 등)** | ✅ |
| `agent_planner.py` | **앱 실행 / URL 열기 / 디렉터리 목록 / 시스템 보고 / 파일 요약 등 템플릿 확장** | ✅ |
| `requirements.txt` | **pyautogui, pyperclip, pygetwindow, selenium, webdriver-manager 추가** | ✅ |
| `README.md` | **최신 자율 실행 범위 및 GUI 자동화 설명 반영** | ✅ |
| `CLAUDE.md` | **개발용 아키텍처 문서 최신화** | ✅ |

---

## 4. 핵심 미해결 문제 (다음 세션에서 반드시 확인)

### 🔴 문제 1: Groq Llama-3.3-70b의 지독한 Tool Call 거부 (심각)

**증상:**
가짜 도구 호출 폴백(`LLMProvider`)을 추가했음에도 불구하고, 모델이 JSON을 생성하다가 중간에 끊어버리거나(`"path": "바"` 등), 실제 도구 호출을 수행하지 않고 텍스트로만 실행 계획을 나열함. 
특히 `run_agent_task` 같은 복합 작업에서 지시를 무시하고 자신의 내부 지식으로 대충 대답하려는 경향이 강함.

**현재 상태:**
- `llm_provider.py`에 요청 의도 분석이 추가되어, 화면 조회/예약/복합 작업은 `tool_choice="required"` 또는 특정 function 강제로 요청함.
- 모델이 여전히 tool call을 거부해도, 실행형 요청이면 `run_agent_task` 등으로 자동 승격하는 폴백이 추가됨.
- 그래도 `AgentPlanner`가 생성하는 단계별 코드(`decompose`) 자체는 Llama-3.3-70b 기반이라 신뢰도가 낮을 수 있음.
- 이를 완화하기 위해 `AgentPlanner`에 자주 쓰는 작업군 템플릿을 추가하여 LLM 자유 계획 의존도를 낮춤.

**대응 방안:**
1. **모델 교체**: `ari_settings.json`에서 `llm_provider`를 `openai`(gpt-4o-mini 이상) 또는 `anthropic`으로 변경하여 테스트 권장.
2. **프롬프트 극단적 단순화**: 플래너와 시스템 프롬프트의 불필요한 수식어를 모두 제거.
3. **직접 명령 유도**: 사용자에게 "도구 호출 모드로 실행해" 같은 명시적 힌트를 주도록 유도.

---

### 🔴 문제 2: 바탕화면 작업 실행 실패

**증상:**
`desktop_path` 변수를 주입했으나, 실제 실행 단계(`AgentOrchestrator`)에서 폴더 생성이나 파일 저장이 이루어지지 않음.

**원인 추정:**
- `AgentPlanner`가 생성한 파이썬 코드에서 `os.makedirs`를 누락하거나, 잘못된 변수명을 사용함.
- `web_search` 결과가 비어있어 저장할 내용이 없는 경우 예외 처리 미흡.

---

### 🟡 문제 3: FACT 오염 및 컨텍스트 압박 (주시 필요)

Llama 모델은 컨텍스트가 길어질수록 성능이 급격히 저하됨. 주기적인 `conversation_history.json` 초기화 또는 FACT 정리 필요.

---

## 5. 파일별 현재 상태 요약

### `llm_provider.py`
- 요청 문장을 `질문/관찰/예약/복합 실행` 관점으로 분석해 도구 사용을 강제.
- 가짜 도구 호출 감지 및 실행형 요청 자동 승격 폴백 탑재.
- `logs/tool_trace_YYYYMMDD.log`에 raw 응답과 tool routing 기록.
- 파일/폴더/문서/시스템 정보 관련 요청도 더 적극적으로 `run_agent_task`로 라우팅.

### `agent_planner.py`
- `desktop_path` 변수 사용 지침 추가됨.
- 균형 괄호 기반 JSON 추출 추가로 잘린 JSON에 대한 복원력이 조금 개선됨.
- `logs/planner_trace_YYYYMMDD.log`에 decompose/fix/verify raw 출력 기록.
- 템플릿 작업군:
  - 폴더 생성
  - 웹 검색→요약→저장
  - 오늘 뉴스 검색→기사 fetch→구조화 요약 저장
  - 로컬 파일 요약 저장
  - 시스템 정보 보고서 저장
  - 디렉터리 목록 저장
  - URL 열기 / 앱 실행
- `fix_step` JSON 파싱 실패 시 heuristic 규칙 기반 복구 적용.

### `autonomous_executor.py`
- `desktop_path` 전역 주입 완료.
- `save_document()` / `choose_document_format()` 추가.
- `txt`, `md`, `pdf` 저장 지원 (`pdf`는 reportlab 사용).
- GUI/브라우저 자동화 함수 주입:
  - `open_url`, `open_path`, `launch_app`
  - `click_screen`, `move_mouse`, `type_text`, `press_keys`, `hotkey`
  - `take_screenshot`, `read_clipboard`, `write_clipboard`
  - `wait_for_window`, `get_active_window_title`, `browser_login`

### `real_verifier.py`
- 생성된 검증 코드를 `logs/verifier_trace_YYYYMMDD.log`에 남김.

### `text_interface.py`
- 텍스트 대화창도 AICommand 자율 실행 경로를 그대로 사용하여 실제 tool call / agent task 수행 가능.

### `web_tools.py`
- `ddgs` 우선 사용.
- 미설치/실패 시 DuckDuckGo HTML 결과 페이지 파싱 폴백 지원.

### `VoiceCommand.py`
- `(감정)`과 `[감정]` 모두 처리.
- 말풍선/텍스트 UI에서 태그를 제거하고 이모지 기반으로 표시.

### `automation_helpers.py`
- GUI / 브라우저 / 앱 자동화 공통 헬퍼 모듈.
- optional dependency 기반:
  - pyautogui / pyperclip / pygetwindow
  - selenium / webdriver-manager
- MFA, CAPTCHA, 동적 selector가 심한 사이트는 여전히 불안정.

---

## 6. 다음 세션(또는 지금) 할 일

1. **[최우선] 모델 성능 검증**: Groq의 한계인지 확인하기 위해 OpenAI API 키가 있다면 모델을 `gpt-4o` 계열로 바꿔서 테스트.
2. **[중요] 플래너 로그 강화**: `agent_planner.py`에서 LLM이 실제로 어떤 JSON을 뱉었는지 로그를 파일로 남겨서 분석.
3. **[선택] 수동 도구 호출 강제**: `tool_choice="required"` 옵션을 일시적으로 켜서 강제로 도구를 호출하게 함.


`_EPHEMERAL_FACT_KEYS`로 22개 키워드 차단 중이지만, LLM이 다른 키로 일시적 상태를 저장할 수 있음.
근본 해결: `memory_manager.py`의 `_is_persistent_fact()`에 키워드 계속 추가하거나, FACT 저장을 화이트리스트 방식으로 전환.

---

## 5. 파일별 현재 상태 요약

### `llm_provider.py` (핵심 파일)
- `chat_with_tools()`: temperature=0.3, max_tokens=1000, tool_choice="auto"
- `_build_system()`: 감각 데이터 주입 + 7개 중요 지침 + 기억/학습 지침
- `_filter_korean()`: 가짜 명령 블록 제거 → 파일 경로 제거 → 비한국어 제거
- `get_available_tools()`: 14개 도구 정의 (get_screen_status, play_youtube, set_timer, cancel_timer, get_weather, adjust_volume, get_current_time, execute_python_code, execute_shell_command, run_agent_task, web_search, web_fetch, schedule_task, cancel_scheduled_task, list_scheduled_tasks)

### `commands/ai_command.py` (실행 진입점)
- `execute()`: chat_with_tools → 폴백 파서 → tool 실행 → agentic followup
- `_parse_pseudo_tool_calls()`: 텍스트 기반 가짜 명령 감지 → 실제 tool call 변환
- `_handle_get_screen_status()`: 화면 상태 수집 및 반환
- `_handle_agent_task()`: orchestrator.run(goal) 호출

### `agent_orchestrator.py`
- `_group_by_dependency()`: 모든 단계 순차 실행 (병렬 실행 제거)
- `_verify()`: 실패 단계 있으면 즉시 False, RealVerifier 실패 시 TTS 경고

### `agent_planner.py`
- `_DECOMPOSE_PROMPT`: Windows 경로 공식, makedirs 필수, condition 의존성 지침
- `_FIX_PROMPT`: Windows 경로 경고
- `_VERIFY_PROMPT`: 불확실 시 false 반환

### `memory_manager.py`
- `_EPHEMERAL_FACT_KEYS`: 22개 일시적 키 블랙리스트
- `_is_persistent_fact()`: FACT 저장 전 검증
- `clean_response()`: 일본어·CJK 한자 제거

### `user_context.json`
- 현재 오염 없음 (facts: {})

---

## 6. 다음 세션에서 할 일 (우선순위 순)

1. **[최우선] tool call 실제 동작 여부 확인**
   - 앱 실행 → "바탕화면에 폴더 만들고 오늘 뉴스 저장해줘" 입력
   - 로그에서 `AI tool 실행: run_agent_task` 또는 `logs/tool_trace_YYYYMMDD.log`의 routing 확인
   - 만약 여전히 안 되면 → planner trace와 verifier trace를 함께 보고 모델 교체 판단

2. **[중요] 템플릿 범위 바깥 작업군 계속 확대**
   - 파일 이름 변경 / 파일 병합 / CSV 요약 / 로그 분석 / 앱 실행/종료 / 브라우저 반복 작업 등
   - 자주 실패하는 목표는 템플릿으로 우선 처리하여 LLM 계획 의존도 축소

3. **[중요] planner 품질 확인**
   - `logs/planner_trace_YYYYMMDD.log`에서 `decompose` raw 응답 확인
   - JSON이 깨져 있거나 내용이 부실하면 Groq 플래너 한계로 판단

4. **[중요] 시스템 프롬프트 길이 최적화**
   - `_build_system()` 출력이 너무 길면 Llama가 tool call 포기
   - 불필요한 지침 통합·축소 검토

5. **[선택] Groq 모델 변경 테스트**
   - `ari_settings.json`의 `llm_model` 값을 빈 문자열로 두면 기본값 `llama-3.3-70b-versatile` 사용
   - tool call 신뢰도 비교: llama-3.3-70b vs mixtral-8x7b-32768

---

## 7. 실행 방법

```bash
pip install -r requirements.txt
# 필요 시 추가 패키지:
# pip install ddgs pyautogui pyperclip pygetwindow selenium webdriver-manager reportlab

python Main.py
```

---

## 8. 이 파일 사용법

새 AI 세션 시작 시:
1. 이 파일(`SESSION_CONTEXT.md`)을 먼저 제공
2. 작업하려는 파일을 추가로 제공
3. 섹션 4(미해결 문제)부터 읽고 시작
4. 작업 완료 후 이 파일 업데이트

# Session Context: Ari Voice Assistant Project

이 파일은 AI 세션(Claude, Gemini 등) 간 프로젝트 상태를 공유하기 위한 문서입니다.
새 세션 시작 시 이 파일을 가장 먼저 제공하세요.

## Last Updated: 2026-03-27
## 상태: 전체 코드 리뷰 3차 완료 · 주요 버그 수정 완료

---

## 1. 프로젝트 개요

"아리(Ari)"는 Windows 전용 한국어 음성 AI 어시스턴트입니다.
- 웨이크워드 "아리야" 감지 → 음성 인식 → 명령 실행 → TTS 응답
- LLM: Groq (기본, llama-3.3-70b-versatile) / OpenAI / Anthropic / Mistral / Gemini / OpenRouter / NVIDIA NIM
- TTS: Fish Audio (Cloud) / CosyVoice3 (Local, 고품질) / OpenAI TTS / ElevenLabs / Edge TTS
- UI: PySide6 시스템 트레이 + 캐릭터 애니메이션 (Shimeji 스타일)
- 진입점: `Main.py` → `VoiceCommand.py` → `CommandRegistry` → 각 Command 클래스

### 디렉터리 구조

| 디렉터리 | 내용 |
|----------|------|
| `VoiceCommand/agent/` | 자율 실행 엔진 (Plan→Execute+Self-Fix→Verify) |
| `VoiceCommand/commands/` | BaseCommand 구현체 (priority 기반 디스패치) |
| `VoiceCommand/core/` | 앱 런타임 핵심 (AppState, ConfigManager, threads) |
| `VoiceCommand/services/` | 웹 도구, 타이머, DOM 분석 |
| `VoiceCommand/memory/` | FACT/BIO/PREF 기억, 신뢰도 엔진 |
| `VoiceCommand/tts/` | TTS 제공자 팩토리 |
| `VoiceCommand/ui/` | PySide6 위젯 (캐릭터, 설정, 테마) |
| `VoiceCommand/audio/` | PyAudio 싱글톤, 웨이크워드 |

---

## 2. 커맨드 우선순위 (priority 낮을수록 먼저 매칭)

| 클래스 | priority | 트리거 |
|--------|----------|--------|
| SystemCommand | 10 | 컴퓨터 종료·재시작·종료취소 |
| LearningCommand | 20 | 학습 모드 |
| TimerCommand | 30 | 타이머, 알람 |
| WeatherCommand | 50 | 날씨 |
| VolumeCommand | 50 | 볼륨 |
| TimeCommand | 50 | 몇 시야 |
| YoutubeCommand | 50 | 유튜브 |
| CalculatorCommand | 50 | 계산 |
| AICommand | 100 | 모든 입력 (fallback) |

---

## 3. LLM 도구 목록 (get_available_tools 기준, 2026-03-27)

```
get_screen_status, play_youtube, set_timer, cancel_timer,
get_weather, adjust_volume, get_current_time,
execute_python_code, execute_shell_command, run_agent_task,
web_search, web_fetch, schedule_task,
shutdown_computer, list_scheduled_tasks, cancel_scheduled_task
```
총 16개. 플러그인 도구는 `_plugin_tools`로 동적 추가.

---

## 4. 2026-03-27 세션에서 수정한 것들

### 4.0 3차 검토 추가 수정

| 파일 | 수정 내용 |
|------|----------|
| `commands/ai_command.py` | `_SCHEDULE_PATTERN_STRINGS` 복합 시간 패턴(시간+분+초 등) 단일 패턴보다 앞에 배치 — "1시간 30분 뒤" 정확 추출 |
| `commands/ai_command.py` | `_handle_list_scheduled_tasks` 날짜 형식: `strftime("%m/%d %H:%M")` → `_format_datetime_kr(dt)` |
| `agent/llm_provider.py` | `feed_tool_result` max_tokens 150 → 300 (비-Anthropic 경로) |

### 4.1 버그 수정

| 파일 | 수정 내용 |
|------|----------|
| `agent/llm_provider.py` | `shutdown_computer` · `list_scheduled_tasks` · `cancel_scheduled_task` 스키마 누락 → 추가 |
| `agent/llm_provider.py` | `set_timer` description 구체화 (알림용 타이머임을 명시, 지연 실행은 `schedule_task` 사용 유도) |
| `agent/llm_provider.py` | `schedule_task` description 구체화 (컴퓨터 종료 예시 포함) |
| `agent/llm_provider.py` | `_analyze_request` force_tool 키워드를 단독 토큰 → 2어절 구절로 좁힘 (오발동 방지) |
| `agent/llm_provider.py` | `chat()` max_tokens 200→400 (OpenAI), 300→400 (Anthropic) |
| `agent/llm_provider.py` | `_anthropic_feed_tool_result` max_tokens 200→500 |
| `commands/ai_command.py` | `_handle_set_timer`: shutdown 요청에 set_timer 잘못 호출 시 SystemCommand 리다이렉트 |
| `commands/ai_command.py` | `_handle_get_current_time`: 자정(0시) → "오전 0시" 대신 "오전 12시" |
| `commands/ai_command.py` | `_parse_relative_schedule`: 첫 매칭 즉시 return → 전체 단위 누산 방식 ("1시간 30분 뒤" 정확 파싱) |
| `commands/ai_command.py` | `_format_datetime_kr`: 제로패딩 제거 + 오전/오후 포함 자연어 형식 |
| `commands/ai_command.py` | `_handle_schedule_task`: 종료/재시작 goal 감지 시 SystemCommand 직접 라우팅 |
| `commands/system_command.py` | 재시작(`shutdown /r`) / 종료취소(`shutdown /a`) 구현 |
| `commands/system_command.py` | `_parse_scheduled_time`: 복합 상대시간 누산 파싱 ("1시간 30분 뒤" 정확 처리) |
| `commands/system_command.py` | `_cancel_shutdown`: subprocess 실행 후 returncode 검증하여 TTS 출력 |
| `commands/system_command.py` | `_format_time_kr`: 분 제로패딩 `:02d` 제거 |
| `commands/timer_command.py` | 잔여시간 조회 ("타이머 얼마 남았어?", "타이머 확인") 추가 |
| `commands/timer_command.py` | `matches()` "알람" 키워드 추가 (LLM 경유 없이 직접 처리) |
| `commands/timer_command.py` | `if minutes:` → `if minutes is not None:` (0.0 처리 정확화) |
| `services/timer_manager.py` | `parse_timer_command`: 숫자 연결 버그(130분) → 정규식 개별 파싱 (시간·분·초 각각 처리) |
| `services/timer_manager.py` | `set_timer`: 1초 폴링 루프 → 단일 `threading.Timer` (15분 타이머 객체 생성 900→1회) |
| `services/timer_manager.py` | `set_timer`: 초(seconds) 단위 지원, `timer.daemon = True` 추가 |

### 4.2 빌드 수정 (이전 세션)

| 파일 | 수정 내용 |
|------|----------|
| `build_exe.py` | `--nofollow-import-to=pygments` 추가 (clcache preprocessor 실패 방지) |
| `build_exe.py` | `--nofollow-import-to=reportlab` 추가 (C 확장 충돌 방지) |
| `.github/workflows/build-release.yml` | `timeout-minutes: 30` → `50` |

---

## 5. 현재 파일별 상태

### `commands/system_command.py`
- 종료(`/s`), 재시작(`/r`), 종료취소(`/a`) 모두 구현
- 상대시간: 시간·분·초 단위 누산 파싱 (복합 표현 지원)
- 절대시간: 오전/오후 N시 M분 파싱 → 당일/익일 자동 선택
- `_cancel_shutdown`: 실행 후 returncode 검증 → 성공 시에만 "취소했습니다" TTS

### `services/timer_manager.py`
- `parse_timer_command`: 정규식 기반 시간·분·초 개별 파싱, float 반환
- `set_timer`: `threading.Timer(total_seconds, callback)` 단일 예약, daemon=True
- `get_remaining_time`: 잔여 초 반환 (TimerCommand에서 TTS로 출력)

### `agent/llm_provider.py`
- 도구 16개 정의 (shutdown_computer 등 3개 스키마 추가 완료)
- `chat()` max_tokens: Anthropic 400, OpenAI 400
- `chat_with_tools()` max_tokens: 1000 (기존 유지)
- `_anthropic_feed_tool_result` max_tokens: 500
- `force_tool` 키워드: 단독 토큰 → 2어절 구절 (오발동 방지)

### `commands/ai_command.py`
- `_handle_set_timer`: shutdown 리다이렉트 fallback 포함
- `_handle_shutdown_computer`: 시간 표현 있으면 schedule_task, 없으면 SystemCommand 직접
- `_handle_schedule_task`: 종료/재시작 goal → SystemCommand 직접 라우팅
- `_parse_relative_schedule`: 전체 누산 방식 (일·시간·분·초 복합 지원)
- `_format_datetime_kr`: 오전/오후 포함, 제로패딩 없는 자연어 형식

---

## 6. 알려진 미해결 문제

### 🟡 Groq Llama-3.3-70b tool call 신뢰도

Llama 계열 모델은 복잡한 tool calling 상황에서 텍스트 응답으로 대체하는 경향 있음.
`_recover_tool_calls_from_response` fallback 파서로 일부 복구 중이나 근본 해결은 모델 교체 권장.

**대응:**
- 설정 → AI&TTS → 제공자: `openai` (gpt-4o-mini 이상) 또는 `anthropic` 으로 변경 시 tool call 신뢰도 대폭 향상
- `ari_settings.json`의 `llm_model` 비워두면 각 제공자 기본 모델 자동 사용

### 🟡 FACT 오염 가능성

LLM이 일시적 상태를 FACT로 저장할 수 있음.
`memory_manager.py`의 `_EPHEMERAL_FACT_KEYS` (22개)로 차단 중이나 완전 차단은 아님.
주기적으로 `conversation_history.json` 초기화 권장.

---

## 7. 개발 검증 명령

```bash
# 실행
py -3.11 VoiceCommand/Main.py

# 전체 검증
py -3.11 VoiceCommand/validate_repo.py

# 단위 테스트
py -3.11 -m unittest discover -s VoiceCommand/tests -p "test_*.py"

# EXE 빌드
py -3.11 VoiceCommand/build_exe.py [--clean] [--onefile]
```

---

## 8. 이 파일 사용법

새 AI 세션 시작 시:
1. 이 파일(`SESSION_CONTEXT.md`)을 먼저 제공
2. 작업하려는 파일을 추가로 제공
3. 섹션 6(미해결 문제)부터 읽고 시작
4. 작업 완료 후 섹션 4(수정 내역)와 섹션 5(파일별 상태) 업데이트

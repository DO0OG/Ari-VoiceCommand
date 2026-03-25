# Ari (아리) — AI 음성 어시스턴트

> 한국어 음성 인식 기반 데스크탑 AI 어시스턴트.
> Shimeji 스타일 캐릭터 위젯 + 다중 LLM / TTS 제공자 선택 지원.

- 캐릭터 모델 제작 : [자라탕](https://github.com/yongmen20)

![preview](https://github.com/user-attachments/assets/fc8de4b7-57ca-4c22-812c-e5dcc7b45cdd)

---

## 개발 현황

### 최근 업데이트 (2026-03-25)

- **자율성 레이어 보강**: 플래너 의존성 분석이 경로 충돌·브라우저/GUI 상태 충돌까지 고려하도록 확장되어, 독립적인 읽기 작업은 더 잘 병렬화하고 상태 변경 작업은 더 안전하게 직렬화합니다.
- **복합 요청 자동 승격**: LLM이 도구 호출을 놓쳐도 저장·분석·정리·브라우저 작업 같은 복합 요청은 `run_agent_task`로 자동 승격해 실제 실행으로 이어지게 했습니다.
- **브라우저 전략 기억 지속화**: 사이트별로 성공한 셀렉터 전략을 파일로 유지해, 반복 웹 작업에서 이전 성공 경로를 우선 재사용합니다.
- **실행 상태 기반 재계획**: 실패 후 재계획 시 활성 창 제목, 현재 브라우저 URL, 최근 산출물 경로를 함께 넘겨 다음 시도가 더 상황 인식적으로 바뀌게 했습니다.
- **파일 작업 템플릿 추가 확장**: 파일 이름 변경, 텍스트 병합, 확장자별 폴더 정리, CSV/JSON 분석, 로그 리포트 생성까지 LLM 자유 생성 대신 안정적인 템플릿 경로로 먼저 처리합니다.
- **GUI 상태 스냅샷 강화**: 활성 창뿐 아니라 열린 창 목록과 데스크톱 상태 스냅샷을 실행기/검증기에 함께 넘겨 앱 실행 검증과 재계획 정확도를 높였습니다.
- **브라우저 액션 상태 보강**: 브라우저 상태에 마지막 액션 요약을 남기고, 다운로드 대기·링크 읽기 같은 반복 작업용 액션 타입을 추가했습니다.
- **예약 종료 안전 가드**: `"5분 뒤에 컴퓨터 꺼줘"` 같은 지연 종료 요청은 즉시 종료로 실행하지 않고 스케줄 작업으로 강제 우회되도록 수정했습니다.
- **시간 표현 파싱 보강**: `5분 뒤`, `5분 후`, `11시에`, `11시 30분에` 같은 상대/절대 시간 표현을 더 정확히 구분해 예약 작업에 반영합니다.
- **기억 품질 보강**: FACT 충돌 이력(`fact_history`)과 충돌 횟수/강화 횟수를 함께 기록해, 같은 사실의 반복 확인과 상충 정보 누적을 더 안정적으로 다룹니다.
- **전략 검색 고도화**: 전략 기억이 태그/토큰/N-gram 외에 해시 기반 임베딩 유사도까지 반영해 비슷한 작업 이력을 더 잘 찾습니다.
- **알람/스케줄 확장**: 스케줄러가 반복 규칙(`daily`, `weekly`, `hourly`), 예외일, 알림 사운드 메타데이터를 함께 보존합니다.
- **대량 파일 작업 확장**: `detect_file_set()`과 `batch_rename_files()`를 추가해 파일 세트 스캔과 정규식 기반 일괄 이름 변경을 처리할 수 있습니다.
- **고급 데이터 요약 추가**: CSV/JSON 분석 시 컬럼 샘플과 숫자 컬럼 요약, 기본 이상치 개수까지 함께 반환합니다.
- **테마 저장 API 추가**: `save_custom_theme()`로 커스텀 팔레트를 JSON 파일로 저장해 외부 테마 폴더와 바로 연동할 수 있습니다.
- **창 상태 인식 보강**: 창 개수/제목/활성 상태를 읽는 헬퍼와 `wait_window_count`, `focus_last_window` 액션을 추가해 GUI 상태 기반 자동화를 더 넓혔습니다.
- **페이지 단위 브라우저 전략 축적**: 브라우저 액션 플랜이 도메인뿐 아니라 페이지 fingerprint까지 함께 기억해, 같은 사이트 내에서도 페이지별 반복 작업을 더 잘 재사용합니다.
- **사용자 플러그인 확장 추가**: `%AppData%\\Ari\\plugins` 기반 플러그인 로더와 `sample_plugin.py` 템플릿을 추가해, 사용자가 직접 확장을 만들고 로드할 수 있습니다.
- **설정 UI 시각 구현 보강**: 설정창에 테마 미리보기 카드와 `확장` 탭을 추가해 색상 변화와 플러그인 상태를 바로 확인할 수 있습니다.
- **브라우저 액션 전략 기억**: 셀렉터뿐 아니라 성공한 액션 시퀀스 자체를 `goal_hint` 기준으로 저장해, 이후 같은 사이트/목표에서 이전 전략을 다시 사용할 수 있게 했습니다.
- **데스크톱 창 전략 기억**: 앱 자동화에서도 성공한 창 제목을 `goal_hint` 기준으로 기억해, 이후 같은 작업에서 창 찾기/포커스를 더 안정적으로 재사용합니다.
- **데스크톱 워크플로우 헬퍼**: `run_desktop_workflow()`로 앱 실행, 창 대기, 포커스, 타이핑/단축키 같은 후속 액션을 하나의 목표 단위로 묶어 재사용할 수 있습니다.
- **유사 목표 전략 재사용**: exact match가 아니어도 비슷한 `goal_hint`라면 브라우저 액션 플랜, 창 타깃, 데스크톱 워크플로우를 다시 찾아 재사용합니다.
- **앱 실행 경로 확장**: Chrome, Edge, VS Code 같은 앱은 기본 경로와 `PATH` 탐색을 함께 사용해 데스크톱 워크플로우 성공률을 높였습니다.
- **데스크톱 액션 타입 확장**: `run_desktop_workflow()`가 URL 열기, 경로 열기, 창 대기, 이미지 클릭, 좌표 클릭까지 한 번에 처리할 수 있습니다.
- **전략 기억 품질 보강**: 브라우저/데스크톱 자동화는 실패나 오류가 섞인 액션 시퀀스를 기억하지 않고, 완전히 성공한 전략만 재사용합니다.
- **화면 대기 액션 추가**: `wait_image` 기반으로 특정 UI 요소가 실제로 나타날 때까지 기다린 뒤 후속 액션을 이어갈 수 있습니다.
- **브라우저 상태 대기 액션 추가**: `wait_url`, `wait_title`, `read_title`로 로그인 후 리다이렉트나 동적 페이지 전환을 더 안정적으로 따라갑니다.
- **브라우저 액션 확장**: `wait_selector`, `read_url`까지 추가해 동적 페이지 로딩과 현재 위치 확인을 더 세밀하게 처리합니다.
- **액션 디스패치 모듈화**: 데스크톱 워크플로우 액션 실행을 내부 헬퍼로 정리해 유지보수성과 Codacy 친화도를 높였습니다.
- **브라우저 검증 보강**: 검증기는 현재 URL/제목뿐 아니라 마지막 브라우저 액션 요약도 읽어 성공 여부를 더 안정적으로 판정합니다.
- **다운로드 템플릿 재사용 보강**: 브라우저 다운로드 템플릿도 `goal_hint`를 직접 넘겨, 이전에 성공한 다운로드 액션 시퀀스를 다음 실행에서 곧바로 재사용합니다.
- **학습 전략 조회 추가**: `get_learned_strategies(goal_hint=...)`로 브라우저 액션 플랜, 창 타깃, 데스크톱 워크플로우를 한 번에 읽어 다음 계획에 바로 참고할 수 있습니다.
- **재계획 컨텍스트 보강**: 오케스트레이터가 `learned_strategies_json`도 함께 넘겨, 실패 후 다음 시도가 과거 성공 전략을 더 직접 재사용합니다.
- **runner 전역 동기화**: 생성된 Python 실행 runner도 `get_learned_strategies`, `get_desktop_state`, `list_open_windows`, 확장된 `get_runtime_state`를 그대로 노출해 self-fix 코드가 배운 전략을 직접 참고할 수 있습니다.
- **전략 요약 API 추가**: `get_learned_strategy_summary(goal_hint=...)`로 브라우저/데스크톱 학습 전략을 짧은 문자열로 먼저 확인할 수 있어, 플래너와 self-fix가 긴 JSON 없이 더 직접적으로 재사용 전략을 따릅니다.
- **planning snapshot 추가**: `get_planning_snapshot_summary(goal_hint=...)`와 `get_planning_snapshot(goal_hint=...)`가 현재 활성 창, 열린 창, 브라우저 URL/제목, 마지막 액션 상태, 학습 전략 요약을 한 번에 제공해 재계획 품질을 더 올립니다.
- **adaptive workflow 실행 추가**: `run_adaptive_browser_workflow()`와 `run_adaptive_desktop_workflow()`가 과거 성공 전략을 우선 적용하고, 없을 때만 fallback 액션을 사용합니다.
- **템플릿 적응 실행 전환**: 브라우저 다운로드 템플릿과 앱 실행 템플릿이 이제 adaptive workflow를 직접 사용해 반복 작업 재현성이 더 높아졌습니다.
- **adaptive plan 합성 추가**: `build_adaptive_browser_plan()`과 `build_adaptive_desktop_plan()`이 학습 전략과 fallback 액션을 병합한 실행 계획을 먼저 만들고, workflow는 그 계획을 그대로 실행합니다.
- **상태 기반 자동 보강**: adaptive plan은 현재 브라우저 URL/제목/마지막 액션 상태를 보고 `wait_url`, `read_url`, `read_title`, `read_links`를 자동 삽입하고, 데스크톱은 `wait_window`, `focus`, `wait`를 자동 보강합니다.
- **resilient workflow 추가**: `run_resilient_browser_workflow()`와 `run_resilient_desktop_workflow()`가 adaptive·learned-only·fallback-only 실행안을 순차 시도해, 첫 계획이 흔들려도 다음 전략으로 자동 복구합니다.
- **resilient plan 합성 추가**: `build_resilient_browser_plans()`와 `build_resilient_desktop_plans()`가 재사용 전략과 fallback 전략을 중복 없이 정리한 다중 시도안을 만들고, 실행 결과에 선택된 계획과 시도 기록을 남깁니다.
- **앱 템플릿 확대**: 메모장·탐색기·크롬·엣지에 더해 VS Code와 계산기도 `run_desktop_workflow()` 템플릿으로 우선 처리합니다.
- **화면 이미지 검증**: `is_image_visible()`를 통해 특정 버튼/상태 이미지가 실제로 화면에 보이는지 읽기 전용으로 확인할 수 있어 GUI 검증 신뢰도를 더 높였습니다.
- **워크플로우 힌트 기억**: 성공한 브라우저/데스크톱 워크플로우의 `goal_hint`와 호출 패턴을 전략 기억에도 함께 남겨, 다음 계획 수립에서 재사용 가능한 접근을 더 직접적으로 주입합니다.
- **앱 워크플로우 템플릿 확장**: 메모장·탐색기·크롬·엣지 같은 자주 쓰는 앱 열기 작업은 단순 `launch_app()` 대신 `run_desktop_workflow()` 템플릿으로 내려 반복 작업 안정성을 높였습니다.
- **워크플로우 결과 해석 검증**: 데스크톱/브라우저 워크플로우가 JSON 형태로 남긴 `window_title`, `opened_url`, `actions`도 검증기가 직접 읽어 성공 여부를 더 안정적으로 판정합니다.
- **사용자 컨텍스트 API 보강**: 다음 명령 예측, 시간대 습관, 상위 선호도 요약을 공용 메서드로 정리해 텍스트 UI와 선제 제안 품질을 높였습니다.
- **전략 기억 회수 강화**: 유사 목표 검색 시 최근성, 실패 교훈, 성공 접근을 더 안정적으로 반영하도록 개선했습니다.
- **검증/안전 보강**: 활성 창 제목·브라우저 상태를 휴리스틱 검증에 더 적극적으로 사용하고, 민감 정보 자동 입력은 더 위험하게 분류합니다.
- **에이전트 아키텍처 고도화**: 계획 수립(Stronger Model)과 실행(Faster Model)을 위한 LLM 모델 분리를 지원하여 성능과 비용 효율을 동시에 잡았습니다.
- **파일 작업군 대폭 확대**: 단순 저장을 넘어 파일 이름 변경, 병합, 확장자별 자동 정리, CSV/JSON 분석 및 마크다운 보고서 생성 기능을 추가했습니다.
- **테마 외부화**: 기본 테마를 Python 상수 대신 `theme/*.json`으로 분리했고, 빌드 후에는 `%AppData%\\Ari\\theme` 폴더의 JSON만 수정해도 UI 테마를 바꿀 수 있게 했습니다.
- **실시간 테마 hot-swap**: 설정창에서 테마를 적용하면 앱 재시작 없이 열린 위젯 단위로 즉시 다시 그립니다.
- **로컬 TTS 최적화**: CosyVoice 워커 warmup, reference 특징 캐시, 안정화된 스트리밍 출력, bounded PCM 버퍼를 적용해 초기 지연과 메모리 흔들림을 줄였습니다.
- **로컬 TTS 비동기 로드**: CosyVoice 워커 READY 대기를 UI 초기화에서 분리해, 앱/설정창이 모델 로드 동안 멈추지 않게 했습니다.
- **메모리 패널 레이아웃 보정**: 통계 탭의 주제 칩을 줄바꿈 그리드로 바꿔 가로 스크롤 없이 한 화면에 표시되도록 했습니다.
- **강화된 자율성 및 지능**:
  - **병렬 실행**: 단계별 의존성 그래프(DAG) 분석을 통해 독립적인 작업들을 동시 실행하여 속도를 높였습니다.
  - **선제적 제안**: 사용자의 대화 주제와 습관을 분석하여 할 일을 먼저 제안합니다.
  - **지정 시각 알람**: 카운트다운 타이머 외에 특정 시각에 맞춰 알림을 주는 기능을 통합했습니다.
- **실제 상태 검증 계층 강화**: `RealVerifier`가 활성 창 제목, 브라우저 URL, 파일 존재 여부 등을 코드로 직접 확인하여 신뢰도를 높였습니다.
- **지능형 메모리 관리**: 사실 간의 충돌을 스스로 해소하고, 오래된 정보의 신뢰도를 점진적으로 낮추는 감쇄(Decay) 로직을 적용했습니다.
- **GUI/브라우저 자동화 강화**: 창 포커스 제어, Selenium 스마트 셀렉터 전략, 다운로드 대기, 브라우저 상태 조회, 이미지 인식 기반 클릭 등을 지원합니다.
- **안전 정책 정교화**: 로그인 자동화, 민감 URL, 차단 앱에 대한 카테고리 기반 판정을 보강했습니다.

### 최근 업데이트 (2026-03-23)

- **기억 신뢰성 강화**: `UserContextManager`에 로드 실패 로그, FACT TTL, BIO/주제/명령 패턴 크기 제한, 대화 주제 자동 추출을 추가해 장시간 실행 시 메모리 품질이 무너지는 문제를 줄였습니다.
- **대화 주제 회상 추가**: `conversation_topics`를 실제로 집계하여 프롬프트 컨텍스트에 반영하고, 최근 반복 주제를 기억 기반으로 재주입할 수 있게 했습니다.
- **실행 컨텍스트 분리**: Python 실행 시 `step_outputs`와 검증용 컨텍스트를 전역 공유 상태 대신 runner payload 스냅샷으로 주입하도록 바꿔 병렬 실행 시 컨텍스트 오염 가능성을 낮췄습니다.
- **선택적 병렬 실행**: 오케스트레이터가 이전 단계 출력에 의존하지 않는 read-only 단계만 제한적으로 병렬 실행하도록 변경해 안전성을 유지하면서 처리량을 높였습니다.
- **실패 분류형 전략 기억**: Strategy Memory가 timeout, 권한, 리소스 누락, 네트워크 오류 등 실패 유형을 함께 기록하여 다음 self-fix와 계획 수립 때 더 직접적인 힌트를 줄 수 있습니다.
- **의미 유사 전략 검색**: Strategy Memory가 태그뿐 아니라 목표 문장 토큰 유사도도 함께 사용해 비슷한 작업 이력을 더 잘 회수하도록 개선했습니다.
- **실제 검증 강화**: 검증기가 생성/저장된 경로 존재 여부를 우선 확인하고, LLM 검증 코드에도 관측된 파일/URL 아티팩트를 함께 넘겨 단순 로그 기반 성공 오판을 줄였습니다.
- **통합 테스트 추가**: 템플릿 기반 폴더 생성/디렉터리 목록 저장 경로를 실제 임시 디렉터리에서 실행하는 회귀 테스트를 추가했습니다.
- **텍스트 UI 상태 패널 추가**: 채팅창 상단에 최근 주제, 다음 추천 명령, 선호 요약을 보여주는 `기억 상태` 패널을 추가했습니다.
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
| **웨이크워드** | SimpleWakeWord(Google STT) "아리야" |
| **음성 인식** | Google STT (기본) · Vosk 오프라인 옵션 |
| **AI 대화** | Groq · OpenAI · Anthropic · Mistral · Gemini · OpenRouter 선택 |
| **감정 표현** | AI 태그(`(기쁨)` 등) 기반 캐릭터 애니메이션 반응 |
| **TTS** | Fish Audio WS · CosyVoice3(로컬) · OpenAI TTS · ElevenLabs · Edge TTS 선택 |
| **캐릭터 위젯** | Shimeji 스타일 드래그 · 물리 엔진 · 마우스 반응 |
| **스마트 모드** | LLM tool calling으로 타이머 · 날씨 · 유튜브 등 자동 실행 |
| **자율 실행** | Python / Shell 코드 생성·실행 + LLM 자동 수정(Self-Fix) + read-only 단계 제한 병렬 실행 |
| **에이전트 루프** | 복잡한 목표를 Plan→Execute→Verify 3레이어로 자율 처리 (최대 4회 재계획) |
| **작업 템플릿** | 폴더 생성, 검색·요약·저장, 시스템 정보 보고서, 디렉터리 목록, 파일 이름 변경, 텍스트 병합, 확장자별 정리, CSV/JSON 분석, 로그 리포트 등 자주 쓰는 작업군을 규칙 기반으로 우선 처리 |
| **파일 작업 확장** | 파일 세트 인식, 정규식 기반 일괄 이름 변경, 컬럼 샘플/숫자 컬럼 요약/이상치 기반 데이터 분석 |
| **문서 저장** | 결과 구조에 따라 `txt` · `md` · `pdf` 자동 저장 또는 사용자 지정 포맷 저장 |
| **GUI 자동화 기반** | 앱 실행, URL/경로 열기, 키 입력, 마우스 클릭, 스크린샷, 클립보드 제어, 창 대기, 창 포커스, 이미지 인식 클릭/대기, Selenium 기반 로그인/상태 조회 |
| **안전 검사** | 실행 전 위험 수준 3단계 분류 + 위험 작업 확인 다이얼로그 (15초 카운트다운) |
| **미디어** | 유튜브 오디오 스트리밍 (yt-dlp + VLC) |
| **기억 시스템** | FACT/BIO/PREF 태그 기반 장기 기억 + FACT TTL/상한 + 대화 주제 자동 추출/회상 |
| **전략 검색** | 태그/토큰/N-gram + 해시 기반 임베딩 유사도 검색 |
| **실행 검증** | 경로/파일 아티팩트 기반 실제 검증 + 활성 창/브라우저 상태 휴리스틱 + LLM 코드 검증 폴백 |
| **설정 UI** | 트레이 아이콘 기반 3탭 설정창 (RP · AI&TTS · 장치/UI, 외부 테마 폴더 안내 포함) |
| **텍스트 인터페이스** | PySide6 채팅 UI + 상단 `기억 상태` 패널 (음성 없이 텍스트로 대화 가능) |
| **계산기** | 수식 음성 인식 및 계산 |
| **빌드 시스템** | Nuitka 기반 EXE 빌드 (단일 파일 · 폴더 선택) |

### 개선 여지

| 항목 | 내용 |
|------|------|
| 장기 기억 품질 | FACT 충돌 이력과 보정 규칙은 들어갔지만, 시간 경과·재확인 빈도·출처별 신뢰도를 함께 학습하는 수준까지는 아직 미구현 |
| GUI 상태 검증 | 창 상태와 이미지 대기까지는 지원하지만, OCR/비전 기반 범용 요소 인식과 앱별 세밀한 상태 판별은 아직 제한적 |
| 플래너 병렬성 | 경로/도메인/창 타깃/goal_hint 충돌까지 반영하지만, 실제 side effect 추적 기반의 정밀 DAG 최적화는 아직 미구현 |
| 전략 기억 검색 | 해시 기반 경량 임베딩 유사도는 추가됐지만, 외부 모델 기반 의미 검색이나 피드백 학습형 랭킹은 아직 없음 |

### 추후 개발

| 기능 | 설명 |
|------|------|
| **Discord 파일 공유** | 파일 전송 명령 commands/ 모듈로 재구현 (현재 미이식) |
| **비전 기반 GUI 인식** | OCR/아이콘/텍스트 블록 인식으로 앱 UI 요소를 더 범용적으로 찾는 계층 추가 |
| **브라우저 후속 액션 자동계획** | 로그인/페이지 전환 이후 다음 액션을 DOM 상태 기반으로 더 적극 재계획 |
| **전략 품질 학습** | 성공/실패 피드백을 받아 전략 재사용 우선순위를 장기적으로 조정하는 계층 추가 |

### 다음 구현 우선순위

1. **비전 기반 GUI 검증 강화**
   OCR/화면 텍스트 인식과 상태 이미지 조합으로 앱별 UI 상태 판별 정확도 향상
2. **브라우저 후속 워크플로우 강화**
   로그인 이후 DOM 상태를 읽고 다음 액션을 자동 제안·재계획하는 계층 추가
3. **플래너 병렬성 고도화**
   단순 read-only 판정을 넘어 실제 부작용 대상과 리소스 충돌 기반으로 DAG 최적화
4. **전략 기억 검색 고도화**
   외부 임베딩 모델 또는 재랭킹 계층을 붙여 유사 전략 검색 품질 향상
5. **기억 신뢰도 학습 고도화**
   FACT 충돌/재확인 빈도/출처 신뢰도를 반영한 장기 신뢰도 업데이트 규칙 추가
6. **테마 편집 UX 확장**
   설정 UI 안에서 팔레트 편집과 JSON 저장을 직접 수행하는 편집 인터페이스 추가

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

## 문서

- [문서 모음](docs/README.md)
- [프로그램 사용 가이드](docs/USAGE.md)
- [테마 커스터마이징 가이드](docs/THEME_CUSTOMIZATION.md)
- [플러그인 가이드](docs/PLUGIN_GUIDE.md)
- [캐릭터 이미지 가이드](docs/CHARACTER_IMAGES.md)

## 빠른 시작

```bash
# 1. 의존성 설치
py -3.11 -m pip install -r VoiceCommand/requirements.txt

# 2. 실행 (Windows)
cd VoiceCommand
py -3.11 Main.py

# 3. 권장 검증
py -3.11 validate_repo.py
```

### 로컬 TTS (CosyVoice3) 설치
고품질 로컬 TTS를 사용하려면 아래 스크립트를 실행하세요 (GPU 권장).
```bash
python VoiceCommand/install_cosyvoice.py
```

---

## 설정

앱 트레이 아이콘 우클릭 → **설정** 에서 4개의 탭으로 구분된 설정을 관리할 수 있습니다.

1. **RP 설정**: 캐릭터의 성격 및 대화 지침 설정
2. **AI & TTS 설정**: 기본 모델, 플래너 모델, 실행 모델, TTS 엔진 및 API 키 관리
3. **장치/UI 설정**: 마이크 입력 장치, UI 테마 프리셋, 글꼴 배율, 테마 미리보기 관리
4. **확장 설정**: 플러그인 폴더 위치와 현재 감지된 플러그인 목록 확인

### 프로그램 사용 흐름

- 기본 사용 순서는 [프로그램 사용 가이드](docs/USAGE.md)에 정리했습니다.
- 예약 명령은 `5분 뒤`, `5분 후`, `11시에`, `11시 30분에`처럼 말할 수 있습니다.
- 텍스트 채팅 UI와 음성 명령은 같은 실행 경로를 사용하므로, 둘 다 자율 실행 기능을 사용할 수 있습니다.

### 외부 테마 커스터마이징

빌드된 EXE를 실행하면 기본 테마 파일이 `%AppData%\Ari\theme` 폴더로 준비됩니다.

- 각 파일은 `.json` 형식이며 Python 코드 수정 없이 색상/폰트 값을 직접 바꿀 수 있습니다.
- 설정창에서는 어떤 테마 JSON을 사용할지 선택만 하고, 실제 값 편집은 파일에서 하면 됩니다.
- 테마 파일을 수정한 뒤 설정창에서 다시 적용하면 열린 UI에 즉시 반영됩니다.
- 상세 항목과 운영 팁은 [테마 커스터마이징 가이드](docs/THEME_CUSTOMIZATION.md)를 확인하세요.

### 사용자 플러그인 확장

빌드된 EXE를 실행하면 사용자 플러그인 폴더가 `%AppData%\Ari\plugins`에 준비됩니다.

- 플러그인은 Python 파일 하나로 추가할 수 있습니다.
- 앱 시작 시 자동 로드되고, 설정창 `확장` 탭에서 현재 목록을 확인할 수 있습니다.
- 텍스트 UI 보조 기능, 트레이 연동, 캐릭터 위젯 반응, 시작 시 사용자 초기화 로직 같은 확장에 적합합니다.
- 플러그인은 `register(context)`를 통해 `app`, `tray_icon`, `character_widget`, `text_interface`에 접근할 수 있습니다.
- 자세한 구조와 예시는 [플러그인 가이드](docs/PLUGIN_GUIDE.md)를 확인하세요.

### 로컬 TTS 최적화 포인트

- 로컬 TTS(`CosyVoice3`)는 워커 프로세스를 계속 유지하고, `reference.wav` 특징을 미리 추출해 반복 호출 비용을 줄입니다.
- 워커 로드는 백그라운드에서 진행되며, UI는 READY까지 동기 대기하지 않습니다.
- 재생 출력은 안정성을 우선해 문장마다 새 스트림을 열고, 모델 워커만 재사용합니다.
- PCM 수신 버퍼는 상한을 둬 긴 문장에서도 메모리가 과도하게 늘어나지 않도록 제한합니다.
- 현재 앱 레벨에서 안전하게 넣을 수 있는 최적화는 대부분 반영된 상태이며, 그 이상은 CosyVoice 엔진 자체 수정 영역에 가깝습니다.

---

## 캐릭터 커스터마이징

`VoiceCommand/images/` 폴더 내의 PNG 파일들을 교체하여 자신만의 캐릭터를 만들 수 있습니다.

### 이미지 규칙 (요약)
- **형식**: 배경이 투명한 PNG
- **파일명**: `동작이름번호.png` (예: `idle1.png`, `walk1.png`)
- **동작 종류**: `idle`, `walk`, `drag`, `fall`, `sit`, `surprised`, `sleep`, `climb` 등

> 💡 **상세 제작 가이드**: [캐릭터 이미지 가이드](docs/CHARACTER_IMAGES.md)를 확인하세요.

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
│   ├── settings_dialog.py     ← 설정창 (LLM 분리 모델/테마 프리셋 포함)
│   ├── speech_bubble.py       ← 말풍선 위젯
│   ├── theme.py               ← UI 테마 프리셋/상수 로더
│   ├── common.py              ← 플로팅 패널/공용 UI 유틸
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
│   ├── execution_analysis.py  ← 실패 분류 / 읽기 전용 단계 판정 / 실행 산출물 추출 공용 유틸
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

### 개발용 검증

```bash
# 전체 검증
py -3.11 VoiceCommand/validate_repo.py

# 개별 실행
py -3.11 VoiceCommand/validate_repo.py --compile-only
py -3.11 VoiceCommand/validate_repo.py --tests-only
py -3.11 VoiceCommand/validate_repo.py --smoke-only
py -3.11 VoiceCommand/validate_repo.py --no-smoke
py -3.11 VoiceCommand/validate_repo.py --list
py -3.11 VoiceCommand/validate_repo.py --json
py -3 -m py_compile VoiceCommand/agent/execution_analysis.py VoiceCommand/agent/agent_orchestrator.py VoiceCommand/agent/real_verifier.py VoiceCommand/agent/strategy_memory.py VoiceCommand/memory/user_context.py VoiceCommand/memory/memory_manager.py
py -3 -m unittest discover -s VoiceCommand/tests -p "test_*.py"
```

`validate_repo.py`는 전체 실행 시 compile/test/smoke 단계별 소요 시간도 함께 출력합니다.

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

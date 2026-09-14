# 기여 가이드라인

아리 음성 명령 프로그램에 기여해 주셔서 감사합니다.
이 문서에는 저장소 작업 방식, 검증 기준, 문서 점검 범위를 한데 모아 두었습니다.

## 기여 방법

1. 이슈 제기
   - 규모가 크거나 논의가 필요한 변경은 GitHub 이슈를 먼저 올려 주세요.
   - 작은 문서 수정, 오탈자, 단순 정리는 바로 PR로 보내셔도 됩니다.
   - 이슈 제목은 가능하면 `<Type>: 설명` 형식을 사용해 주세요.
     - 예: `Fix: 세션 컨텍스트 문서 최신화`
   - 허용 타입은 `Feat`, `Fix`, `Docs`, `Style`, `Refactor`, `Test`, `Chore` 입니다.
   - 이슈 본문은 가능하면 `-` 목록 형식으로 정리해 주세요.

2. 풀 리퀘스트 제출
   - 코드 기여를 하고 싶으시다면 다음 단계를 따라주세요:
     a. 필요하다면 작업 내용을 구분하기 쉬운 브랜치를 생성합니다.
        - 권장 형식: `<issue-number>-<type>-<slug>`
        - 예: `58-docs-기여-체크리스트-최신화-및-후속-개선-과제-정리`
     b. 변경사항을 검증한 뒤 커밋합니다.
     c. 브랜치에 푸시합니다.
     d. 풀 리퀘스트를 생성합니다.
   - PR 제목은 가능하면 `[Type] 설명` 형식을 사용해 주세요.
     - 예: `[Docs] 기여 체크리스트 최신화`
   - PR 본문에는 변경 요약, 테스트 내용, 관련 이슈를 함께 적어 주세요.

## 코딩 스타일

읽기 쉽고 검증할 수 있는 변경을 유지하는 것이 기본 원칙입니다.

- PEP 8 가이드라인을 따라 주세요.
- 함수와 클래스에는 문서화 문자열(docstring)을 적어 주세요.
- 변수와 함수 이름은 무엇을 하는지 바로 알아볼 수 있게 지어 주세요.

## 테스트

기능을 더하거나 고친 뒤에는 아래 기준으로 검증해 주세요.

- 새 기능을 넣거나 버그를 고칠 때는 관련 테스트도 같이 작성해 주세요.
- 테스트가 모두 통과하는지 확인한 뒤에 풀 리퀘스트를 올려 주세요.
- 기본 검증 명령:
  - `VoiceCommand\.venv\Scripts\python.exe VoiceCommand\validate_repo.py`
  - 빠른 문법 검사만 필요하면 `VoiceCommand\.venv\Scripts\python.exe VoiceCommand\validate_repo.py --compile-only`
- 기본 기준선은 **전체 unittest + smoke** 입니다.
- `validate_repo.py`는 compile + unit test에 더해 clean runtime 환경과 marketplace SHA256 계약 smoke도 확인합니다.
- 기능 회귀만 빠르게 보고 싶다면 필요한 테스트만 골라 `VoiceCommand\.venv\Scripts\python.exe -m unittest ...` 형태로 부분 실행해도 됩니다.
- 자율 실행 코어를 건드렸다면 `test_agent_integration`, `test_autonomous_executor`, `test_automation_helpers`, `test_real_verifier`, `test_episode_memory`까지 같이 돌려 보시길 권합니다.
- Agent Skills/MCP를 건드렸다면 `test_skill_manager`, `test_skill_installer`, `test_mcp_client`, `test_llm_provider`, `test_ai_command`도 함께 확인해 주세요.
- 자기개선 루프(ReflectionEngine / SkillLibrary / WeeklyReport / i18n)를 건드렸다면 `test_learning_engine`, `test_skill_library`, `test_episode_memory`, `test_learning_quality`, `test_weekly_report`, `test_agent_integration`, `test_skill_optimizer`를 먼저 확인해 주세요.

## i18n 변경 체크리스트

사용자에게 보이는 문자열을 고치거나 새로 넣었다면 아래 항목을 함께 점검해 주세요.

- 문자열이 있는 파일에서 `from i18n.translator import _` 를 사용하고 있는지
- 모듈 레벨 상수에서 `_()` 를 호출하지 않았는지
- `VoiceCommand/i18n/locales/ko/LC_MESSAGES/ari.po`
- `VoiceCommand/i18n/locales/en/LC_MESSAGES/ari.po`
- `VoiceCommand/i18n/locales/ja/LC_MESSAGES/ari.po`
- `VoiceCommand\.venv\Scripts\python.exe VoiceCommand\scripts\extract_strings.py`
- `VoiceCommand\.venv\Scripts\python.exe VoiceCommand\scripts\compile_po.py`

자기개선 루프처럼 보고서·lesson·fallback 메시지가 계속 늘어나는 영역은 ko/en/ja 세 locale을 같이 갱신하지 않으면 언어별 품질 차이가 금세 벌어집니다.

## Agent Skills 작성 가이드

새 스킬을 추가하거나 기존 `SKILL.md`를 손볼 때는 아래 메타데이터부터 살펴봐 주세요.

- `skill_type`: `prompt_only` / `search` / `script` / `mcp`
- `triggers_ko`, `triggers_en`, `triggers_ja`
- `description_ko`, `description_en`, `description_ja`
- `search_query_template_ko`, `search_query_template_en`, `search_query_template_ja` (`search` 타입일 때)

이렇게 권하는 이유는 다음과 같습니다.

- 한국어·영어·일본어 사용자가 같은 스킬을 안정적으로 매칭할 수 있습니다.
- 실시간 데이터 스킬은 언어별 검색 템플릿 덕분에 `web_search` 강제 경로를 더 정확히 탑니다.
- 스크립트형 스킬은 `script` 타입을 선언해 두면 `run_agent_task` 승격 조건이 분명해집니다.

메타데이터가 없어도 Ari가 스킬 이름과 설명으로 fallback 매칭을 시도하긴 합니다. 다만 다국어 품질은 frontmatter를 명시했을 때가 확실히 낫습니다.

## 문서 / 체크리스트 유지

- PR을 병합했거나 구조를 바꿨다면 아래 항목을 함께 확인해 주세요.
  - `README.md` (영문 기본)
  - `README.en.md` (영문 호환 링크)
  - `README.ko.md`
  - `README.ja.md`
  - `docs/README.md`
  - 테스트 기준 설명(예: 전체 unittest + smoke)이 지금의 검증 흐름과 맞는지
- 문서만 고치는 경우에도 저장소 운영 규칙과 실제 검증 기준이 어긋나지 않는지 같이 봐 주세요.

## 로컬 전용 파일

아래 파일과 폴더는 로컬 환경에서만 생기는 산출물이라 Git 추적 대상이 아닙니다.
- `VoiceCommand/.ari_runtime/`
- `VoiceCommand/reference.wav`
- `market/web/.env.local`
- `market/web/node_modules/`
- `market/web/.next/`
- `market/web/tsconfig.tsbuildinfo`
- `market/supabase/.temp/`
- `supabase/`
- 저장소에는 템플릿 기준선인 `VoiceCommand/ari_settings.template.json`만 둡니다. 실제로 쓰는 `VoiceCommand/ari_settings.json`은 로컬 전용이라 Git 추적 대상이 아닙니다.
- 처음 설정할 때는 이 템플릿을 런타임 경로(`VoiceCommand/.ari_runtime/ari_settings.json` 또는 `%AppData%/Ari/ari_settings.json`)로 복사해서 쓰세요.
- 소스 실행 중 만들어지는 개인 API 키, 예약 작업, 로그, 메모리, 플러그인 캐시는 `.ari_runtime/` 아래에만 남겨 주세요. 빌드된 exe는 `%AppData%/Ari/`를 씁니다.
- 문서나 빌드 스크립트를 고칠 때는 이런 로컬 파일이 없는 환경에서도 동작하도록 해 주세요.

## 커밋 메시지 가이드라인

- 커밋 제목은 가능하면 `<Type>: 설명` 형식을 써 주세요.
  - `Feat` : 새로운 기능 추가
  - `Fix` : 버그 수정
  - `Docs` : 문서 수정
  - `Style` : 코드 포맷팅, 세미콜론 누락, 코드 변경 없는 경우
  - `Refactor` : 코드 리팩토링
  - `Test` : 테스트 코드, 리팩토링 테스트 추가
  - `Chore` : 빌드 업무 수정, 패키지 매니저 수정
- 커밋 본문은 `-` 목록 형식으로 적어 주세요.
- 푸시하기 전에 검증 명령 결과와 문서를 고쳐야 할지 여부를 한 번 더 확인해 주세요.

## 행동 강령

이 프로젝트는 누구나 편하게 참여할 수 있는 분위기를 지향합니다. 함께하는 사람들에게 존중과 예의를 갖춰 주세요.

궁금한 점이나 하고 싶은 이야기가 있다면 언제든 이슈로 남겨 주세요. 기여해 주셔서 감사합니다.

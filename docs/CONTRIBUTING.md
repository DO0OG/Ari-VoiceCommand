# 기여 가이드라인

아리 음성 명령 프로그램에 기여해 주셔서 감사합니다.
이 문서는 저장소 작업 방식, 검증 기준, 문서 점검 범위를 한 번에 확인할 수 있도록 정리한 기여 안내서입니다.

## 기여 방법

1. 이슈 제기
   - 규모가 크거나 논의가 필요한 변경은 GitHub 이슈를 먼저 생성해 주세요.
   - 작은 문서 수정, 오탈자 수정, 단순 정리는 바로 PR로 진행해도 됩니다.
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

기본 원칙은 읽기 쉽고 검증 가능한 변경을 유지하는 것입니다.

- PEP 8 가이드라인을 따라주세요.
- 함수와 클래스에는 적절한 문서화 문자열(docstring)을 추가해 주세요.
- 변수와 함수 이름은 의미 있고 이해하기 쉽게 지어주세요.

## 테스트

기능 추가나 수정 이후에는 아래 기준으로 검증을 진행해 주세요.

- 새로운 기능을 추가하거나 버그를 수정할 때는 관련 테스트도 함께 작성해 주세요.
- 모든 테스트가 통과하는지 확인 후 풀 리퀘스트를 제출해 주세요.
- 기본 검증 명령:
  - `py -3.11 VoiceCommand/validate_repo.py`
  - 빠른 문법 검사만 필요하면 `py -3.11 VoiceCommand/validate_repo.py --compile-only`
- 현재 기본 기준선은 **전체 unittest + smoke** 입니다.
- `validate_repo.py`는 현재 compile + unit test 외에 clean runtime 환경과 marketplace SHA256 계약 smoke도 함께 확인합니다.
- 기능 회귀를 빠르게 보려면 필요한 테스트만 골라 `py -3.11 -m unittest ...` 형태로 부분 실행해도 됩니다.
- 자율 실행 코어를 건드렸다면 `test_agent_integration`, `test_autonomous_executor`, `test_automation_helpers`, `test_real_verifier`, `test_episode_memory`까지 함께 확인하는 것을 권장합니다.
- Agent Skills/MCP를 건드렸다면 `test_skill_manager`, `test_skill_installer`, `test_mcp_client`, `test_llm_provider`, `test_ai_command`도 함께 확인해 주세요.

## Agent Skills 작성 가이드

새 스킬을 추가하거나 기존 `SKILL.md`를 갱신할 때는 아래 메타데이터를 우선 검토해 주세요.

- `skill_type`: `prompt_only` / `search` / `script` / `mcp`
- `triggers_ko`, `triggers_en`, `triggers_ja`
- `description_ko`, `description_en`, `description_ja`
- `search_query_template_ko`, `search_query_template_en`, `search_query_template_ja` (`search` 타입일 때)

권장 이유:

- 한국어/영어/일본어 사용자가 같은 스킬을 안정적으로 매칭할 수 있습니다.
- 실시간 데이터 스킬은 언어별 검색 템플릿으로 `web_search` 강제 경로를 더 정확하게 탈 수 있습니다.
- 스크립트형 스킬은 `script` 타입 선언으로 `run_agent_task` 승격 조건을 명확히 할 수 있습니다.

메타데이터가 부족해도 Ari가 스킬 이름/설명 기반 fallback 매칭을 시도하지만, 다국어 품질은 frontmatter를 명시했을 때가 가장 좋습니다.

## 문서 / 체크리스트 유지

- PR 병합 또는 구조 변경 이후에는 아래 항목을 함께 확인해 주세요.
  - `README.md` (영문 기본)
  - `README.en.md` (영문 호환 링크)
  - `README.ko.md`
  - `README.ja.md`
  - `docs/README.md`
  - 테스트 기준 설명(예: 전체 unittest + smoke)이 최신 검증 흐름과 일치하는지
- 문서만 수정하더라도 현재 저장소 운영 규칙과 실제 검증 기준이 어긋나지 않는지 함께 점검해 주세요.

## 로컬 전용 파일

아래 파일과 폴더는 로컬 환경 전용 산출물이므로 기본적으로 Git 추적 대상이 아닙니다.
- `VoiceCommand/.ari_runtime/`
- `VoiceCommand/reference.wav`
- `market/web/.env.local`
- `market/web/node_modules/`
- `market/web/.next/`
- `market/web/tsconfig.tsbuildinfo`
- `market/supabase/.temp/`
- `supabase/`
- 저장소에는 `VoiceCommand/ari_settings.template.json`만 템플릿 기준선으로 유지합니다. 실제 사용 중인 `VoiceCommand/ari_settings.json`은 로컬 전용 파일이며 Git 추적 대상이 아닙니다.
- 처음 설정할 때는 템플릿을 참고해 런타임 경로(`VoiceCommand/.ari_runtime/ari_settings.json` 또는 `%AppData%/Ari/ari_settings.json`)에 복사해서 사용하세요.
- 소스 실행 중 생성되는 개인 API 키, 예약 작업, 로그, 메모리, 플러그인 캐시는 `.ari_runtime/` 아래에만 남도록 유지해 주세요. 빌드된 exe는 `%AppData%/Ari/`를 사용합니다.
- 문서나 빌드 스크립트를 수정할 때는 이런 로컬 파일이 없어도 동작하도록 유지해 주세요.

## 커밋 메시지 가이드라인

- 커밋 제목은 가능하면 `<Type>: 설명` 형식을 사용해 주세요.
  - `Feat` : 새로운 기능 추가
  - `Fix` : 버그 수정
  - `Docs` : 문서 수정
  - `Style` : 코드 포맷팅, 세미콜론 누락, 코드 변경 없는 경우
  - `Refactor` : 코드 리팩토링
  - `Test` : 테스트 코드, 리팩토링 테스트 추가
  - `Chore` : 빌드 업무 수정, 패키지 매니저 수정
- 커밋 본문은 `-` 목록 형식으로 작성해 주세요.
- 푸시 전에는 검증 명령 결과와 문서 반영 필요 여부를 다시 확인해 주세요.

## 행동 강령

이 프로젝트의 기여자로서, 우리는 개방적이고 환영하는 커뮤니티를 만들기 위해 노력합니다. 모든 참여자에게 존중과 예의를 갖추어 주시기 바랍니다.

질문이나 의견이 있으시면 언제든 이슈를 통해 문의해 주세요. 여러분의 기여에 감사드립니다!

# 기여 가이드라인

아리 음성 명령 프로그램에 기여해 주셔서 감사합니다. 여러분의 기여는 이 프로젝트를 더욱 발전시키는 데 큰 도움이 됩니다.

## 기여 방법

1. 이슈 제기
   - 버그를 발견하셨거나 새로운 기능을 제안하고 싶으시다면 GitHub 이슈를 열어주세요.
   - 이슈를 작성할 때는 가능한 한 자세히 설명해 주시기 바랍니다.

2. 풀 리퀘스트 제출
   - 코드 기여를 하고 싶으시다면 다음 단계를 따라주세요:
     a. 프로젝트를 포크합니다.
     b. 새로운 브랜치를 생성합니다 (`git checkout -b feature/AmazingFeature`).
     c. 변경사항을 커밋합니다 (`git commit -m 'Add some AmazingFeature'`).
     d. 브랜치에 푸시합니다 (`git push origin feature/AmazingFeature`).
     e. 풀 리퀘스트를 열어주세요.

## 코딩 스타일

- PEP 8 가이드라인을 따라주세요.
- 함수와 클래스에는 적절한 문서화 문자열(docstring)을 추가해 주세요.
- 변수와 함수 이름은 의미 있고 이해하기 쉽게 지어주세요.

## 테스트

- 새로운 기능을 추가하거나 버그를 수정할 때는 관련 테스트도 함께 작성해 주세요.
- 모든 테스트가 통과하는지 확인 후 풀 리퀘스트를 제출해 주세요.
- 기본 검증 명령:
  - `py -3.11 VoiceCommand/validate_repo.py`
  - 빠른 문법 검사만 필요하면 `py -3.11 VoiceCommand/validate_repo.py --compile-only`
- 기능 회귀를 빠르게 보려면 필요한 테스트만 골라 `py -3.11 -m unittest ...` 형태로 부분 실행해도 됩니다.
- 자율 실행 코어를 건드렸다면 `test_agent_integration`, `test_autonomous_executor`, `test_automation_helpers`, `test_real_verifier`, `test_episode_memory`까지 함께 확인하는 것을 권장합니다.

## 로컬 전용 파일

- 아래 파일/폴더는 로컬 개발 산출물이라 기본적으로 Git 추적 대상이 아닙니다.
  - `VoiceCommand/ari_settings.json`
  - `VoiceCommand/reference.wav`
  - `market/web/.env.local`
  - `market/supabase/.temp/`
  - `supabase/`
- 문서나 빌드 스크립트를 수정할 때는 이런 로컬 파일이 없어도 동작하도록 유지해 주세요.

## 커밋 메시지 가이드라인

- 커밋 메시지는 명확하고 설명적으로 작성해 주세요.
- 현재 시제를 사용하세요 (예: "Add feature" not "Added feature").
- 첫 줄은 50자 이내로 작성하고, 필요하다면 빈 줄 후에 자세한 설명을 추가해 주세요.

## 행동 강령

이 프로젝트의 기여자로서, 우리는 개방적이고 환영하는 커뮤니티를 만들기 위해 노력합니다. 모든 참여자에게 존중과 예의를 갖추어 주시기 바랍니다.

질문이나 의견이 있으시면 언제든 이슈를 통해 문의해 주세요. 여러분의 기여에 감사드립니다!

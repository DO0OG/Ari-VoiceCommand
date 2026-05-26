# 자율 에이전트 고급 기능

- 에이전트는 독립 목표를 하위 에이전트에 위임할 수 있으며 `max_subagents` 설정으로 동시 실행 수를 제한합니다.
- 구조화 지식 베이스는 `.ari_runtime/knowledge_base.db`에 사실을 저장하고 관련 지식을 시스템 프롬프트에 자동 주입합니다.
- Google Calendar/Gmail, OpenAPI 기반 `api_call`, 이미지 생성 도구는 설정에서 활성화한 뒤 사용할 수 있습니다.
- 대화 검색 UI는 메모리 인덱스를 조회하며, 벤치마크는 `py -3.11 VoiceCommand/tests/benchmark_agent.py`로 실행합니다.

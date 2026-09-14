# 자율 에이전트 고급 기능

- 에이전트는 독립적인 목표를 하위 에이전트에 넘길 수 있고, 동시 실행 개수는 `max_subagents` 설정으로 제한합니다.
- 구조화 지식 베이스는 사실을 `.ari_runtime/knowledge_base.db`에 저장해 두었다가, 관련 있는 지식을 시스템 프롬프트에 알아서 넣어 줍니다.
- Google Calendar/Gmail, OpenAPI 기반 `api_call`, 이미지 생성 도구는 설정에서 켠 뒤에 쓸 수 있습니다.
- 대화 검색 UI는 메모리 인덱스를 조회합니다.
- 벤치마크는 `VoiceCommand` 디렉터리로 이동한 뒤 `.venv\Scripts\python.exe -m tests.benchmark_agent`로 실행합니다. 다른 위치에서 실행하면 `core` 모듈을 찾지 못해 실패합니다.

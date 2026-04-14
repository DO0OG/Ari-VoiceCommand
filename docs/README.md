# 문서 모음

아리(Ari) 프로젝트 문서를 한 곳에 모았습니다.
README가 프로젝트의 첫 소개라면, 이 문서는 목적에 따라 필요한 문서를 빠르게 찾기 위한 색인 역할을 합니다.

## 빠르게 시작하기

처음 설치하거나 기본 사용 흐름을 확인할 때는 아래 문서부터 보시면 됩니다.

- [프로그램 사용 가이드](./USAGE.md) — 실행, 기본 사용법, 로컬 설치(Ollama/CosyVoice3), 자동화 예시, NVIDIA NIM
- [기여 가이드](./CONTRIBUTING.md) — 검증 명령, 브랜치/커밋 규칙, 로컬 산출물 관리

## 최근 문서화된 변경 포인트

최근 자기개선 루프 갱신에 맞춰 아래 항목도 문서 기준선을 함께 맞췄습니다.

- 실패 반성 결과를 동일 실행 재시도에 주입하는 자율 실행 흐름
- 성공 시 background reflection, 실패 시 동기 reflection 재시도 흐름
- 임베딩 기반 스킬 매칭과 컴파일 실패 추적
- 주간 보고서의 학습 컴포넌트 통계 / 신규 스킬 / Python 컴파일 / 추정 토큰 표시
- ko/en/ja 3개 언어 동시 반영을 전제로 한 i18n 유지 절차

## 확장과 커스터마이징

앱 기능을 확장하거나 외형을 조정할 때는 아래 문서를 참고하시면 됩니다.

- [프로그램 사용 가이드 - Agent Skills / MCP](./USAGE.md#4-에이전트-스킬-skills--mcp) — Agent Skills 설치, MCP 스킬 사용 흐름, 관리 UI
- [플러그인 가이드](./PLUGIN_GUIDE.md) — 훅(메뉴·명령·도구·샌드박스) 등록, API 버전, ZIP 패키지 구조, 코드 예시
- [테마 커스터마이징 가이드](./THEME_CUSTOMIZATION.md) — 팔레트 에디터와 JSON 테마 파일 편집 방법, `DNFBitBitv2` 폰트 출처
- [캐릭터 이미지 가이드](./CHARACTER_IMAGES.md) — 애니메이션 이미지 파일명 규칙, 감정 표현 시스템

## 개발 및 운영 참고

아래 메모는 실행 경로와 검증 흐름을 빠르게 확인하기 위한 운영 참고 사항입니다.

### 운영 메모

- 소스 실행(`py Main.py`) 기준 런타임 상태는 `VoiceCommand/.ari_runtime/`에 저장됩니다.
- 빌드된 exe 실행 기준 런타임 상태는 `%AppData%/Ari/`에 저장됩니다.
- `reference.wav`는 소스/테스트 실행 시 런타임 경로를 우선하고, exe 실행 시에는 `%AppData%/Ari/` 경로를 우선합니다.
- `VoiceCommand/validate_repo.py`는 compile + unittest 외에 clean runtime 환경과 marketplace SHA256 계약 smoke까지 함께 확인합니다.

# 문서 모음

아리(Ari) 프로젝트 문서를 한 곳에 모았습니다.

## 사용자 문서

- [프로그램 사용 가이드](./USAGE.md) — 실행, 기본 사용법, 로컬 설치(Ollama/CosyVoice3), 자동화 예시, NVIDIA NIM
- [테마 커스터마이징 가이드](./THEME_CUSTOMIZATION.md) — JSON 테마 파일 편집, 팔레트 에디터 창 사용법
- [플러그인 가이드](./PLUGIN_GUIDE.md) — 훅(메뉴·명령·도구·샌드박스) 등록, API 버전, ZIP 패키지 구조, 코드 예시
- [기여 가이드](./CONTRIBUTING.md) — 검증 명령, 브랜치/커밋 규칙, 로컬 산출물 관리

## 프로젝트 문서

- 최근 자율 실행 코어는 `state transition`, `execution policy`, `episode memory`, `backup/recovery guidance`까지 포함하도록 확장되었습니다. `workspace audit` 명령은 열린 창을 브라우저/일반 앱으로 분류하고 `summary.md`를 자동 백업 덮어쓰기하는 템플릿을 사용합니다.
- 소스 실행(`py Main.py`) 기준 런타임 상태는 `VoiceCommand/.ari_runtime/`에 저장되며, 루트에는 `ari_settings.json` 템플릿만 유지합니다. 로그는 `VoiceCommand/.ari_runtime/logs/`에 쌓입니다.
- 빌드된 exe 실행 기준 런타임 상태는 `%AppData%/Ari/`에 저장됩니다.
- `reference.wav`는 소스/테스트 실행 시 `VoiceCommand/.ari_runtime/reference.wav` 우선, 없으면 `VoiceCommand/reference.wav`를 사용하고, 빌드된 exe 실행 시에는 `%AppData%/Ari/reference.wav` 우선, 없으면 번들된 `reference.wav`를 사용합니다.
- `VoiceCommand/validate_repo.py`는 compile + unittest 외에 clean runtime 환경과 marketplace SHA256 계약 smoke까지 함께 확인합니다.
- [캐릭터 이미지 가이드](./CHARACTER_IMAGES.md) — 애니메이션 이미지 파일명 규칙, 감정 표현 시스템
- [Claude 메모](./CLAUDE.md) — 개발자용 아키텍처·패턴·상수 레퍼런스
- [마켓플레이스 설정 가이드](./MARKETPLACE_SETUP_GUIDE.md) — Supabase, GitHub OAuth, Edge Functions, Vercel 배포
- [세션 컨텍스트](./SESSION_CONTEXT.md) — 최근 작업 맥락과 내부 체크포인트 메모

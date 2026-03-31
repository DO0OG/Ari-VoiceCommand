# Ari Marketplace

`market/` 폴더 안에 Ari 플러그인 마켓플레이스 구현물을 정리했습니다.

구성:

- `supabase/`: DB 마이그레이션, Storage 정책, Edge Functions
- `.github/workflows/`: 플러그인 검증 워크플로우
- `marketplace/scripts/`: GitHub Actions 검증 스크립트
- `web/`: Next.js 14 기반 프론트엔드
- `ari_integration/`: Ari 앱 연동용 Python 모듈과 설정창 패치 예시

주의:

- 실제 배포 시 GitHub Actions는 저장소 루트 `.github/workflows/` 로 옮겨야 동작합니다.
- `web/.env.local.example` 값을 채운 뒤 `npm install` 및 `npm run dev` 로 실행할 수 있습니다.
- Supabase Edge Functions 환경 변수는 `docs/ARI_MARKETPLACE_SPEC.md` 기준으로 별도 등록해야 합니다.
- 업로드 ZIP 규칙은 `main.py` 고정이 아니라 `plugin.json` 의 `entry` 필드를 따릅니다. 설치 시에는 entry 파일만 추출하고 로컬에는 플러그인명 기반 파일명으로 저장해 충돌을 피합니다.

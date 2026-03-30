# Ari Marketplace — 개발자 설정 가이드

> Supabase · GitHub OAuth · Vercel 배포까지 순서대로 따라하는 가이드입니다.

---

## 1단계 — Supabase 프로젝트 생성 + DB 초기화

1. [supabase.com](https://supabase.com) → `Sign In` → GitHub 계정으로 로그인
2. 대시보드 → `New project` 클릭
   - Name: `ari-marketplace` (자유)
   - Database Password: 강력한 비밀번호 생성 (저장해두기)
   - Region: `Northeast Asia (Seoul)` 선택
   - **Enable automatic RLS: ON**
   - **Enable Data API: ON**
3. `Create new project` → 약 1분 대기
4. 좌측 메뉴 → `SQL Editor` → `New query`
5. `market/supabase/migrations/001_init.sql` 전체 내용 붙여넣기 → `Run` (경고 무시하고 실행)
6. 좌측 메뉴 → `SQL Editor` → `New query`
7. `market/supabase/storage/buckets.sql` 전체 내용 붙여넣기 → `Run`

---

## 2단계 — GitHub OAuth App 등록

1. GitHub 로그인 → 우상단 프로필 → `Settings`
2. 좌측 맨 아래 `Developer settings` → `OAuth Apps` → `New OAuth App`
   - Application name: `Ari Marketplace`
   - Homepage URL: `https://ari-marketplace.vercel.app` (아직 없어도 일단 입력)
   - Authorization callback URL:
     ```
     https://<프로젝트ID>.supabase.co/auth/v1/callback
     ```
     > 프로젝트 ID는 Supabase 대시보드 URL에서 확인: `supabase.com/dashboard/project/abcdefgh` → `abcdefgh` 부분
3. `Register application` → `Client ID` 복사해두기
4. `Generate a new client secret` → `Client Secret` 복사해두기

**Supabase에 연동:**

5. Supabase 대시보드 → `Authentication` → `Providers`
6. `GitHub` 클릭 → `Enable` 토글 ON
7. Client ID / Client Secret 붙여넣기 → `Save`

---

## 3단계 — GitHub Actions Secrets 등록

1. GitHub에서 `DO0OG/Ari-VoiceCommand` 레포 이동
2. 상단 탭 `Settings` → 좌측 `Secrets and variables` → `Actions`
3. `New repository secret` 으로 아래 3개 등록:

| Name | Value 찾는 곳 |
|------|--------------|
| `SUPABASE_URL` | Supabase → `Settings` → `API` → **Project URL** |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase → `Settings` → `API` → **service_role** (secret 토글 눌러서 표시) |
| `GH_PAT` | 아래 4~7번 참고 |

**GH_PAT 발급:**

4. GitHub → `Settings` → `Developer settings` → `Personal access tokens` → `Tokens (classic)`
5. `Generate new token (classic)`
   - Note: `ari-marketplace-workflow`
   - Expiration: 적당히 (90일 or No expiration)
   - Scope: **`workflow`** 체크
6. `Generate token` → 토큰 값 복사 (한 번만 보여줌)
7. 위 표의 `GH_PAT`에 붙여넣기

---

## 4단계 — Supabase Edge Functions 환경변수 등록

**Resend API 키 발급:**

1. [resend.com](https://resend.com) → `Sign Up` (무료, 카드 불필요)
2. 로그인 후 좌측 `API Keys` → `Create API Key`
   - Name: `ari-marketplace`
   - Permission: `Sending access`
3. 키 복사해두기

**Supabase Edge Function 환경변수 등록:**

4. Supabase 대시보드 → `Edge Functions` → `Manage secrets`
5. 아래 항목들 하나씩 `Add new secret`:

| Key | Value |
|-----|-------|
| `SUPABASE_URL` | Supabase Settings → API → Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase Settings → API → service_role key |
| `GH_PAT` | 3단계에서 발급한 토큰 |
| `GH_REPO` | `DO0OG/Ari-VoiceCommand` |
| `RESEND_API_KEY` | 위에서 발급한 Resend 키 |
| `SITE_URL` | `https://ari-marketplace.vercel.app` |

---

## 5단계 — Supabase Edge Functions 배포

로컬 터미널에서:

```bash
# Supabase CLI 설치 (없으면)
npm install -g supabase

# 로그인
supabase login

# 프로젝트 연결 (프로젝트 ID는 2단계에서 확인한 값)
cd d:/Git/Ari-VoiceCommand
supabase link --project-ref <프로젝트ID>

# 전체 Edge Function 배포
supabase functions deploy --project-ref <프로젝트ID>

# 또는 변경한 함수만 개별 배포
supabase functions deploy upload-plugin --project-ref <프로젝트ID> --no-verify-jwt
supabase functions deploy notify-developer --project-ref <프로젝트ID> --no-verify-jwt
```

> 함수 코드(`market/supabase/functions/*`)를 수정한 경우에만 다시 배포하면 됩니다. 웹 프론트나 데스크톱 앱 코드만 바뀐 경우에는 재배포가 필요하지 않습니다.
> 예를 들어 `upload-plugin`, `notify-developer`만 수정했다면 그 함수들만 개별 배포하면 됩니다.

---

## 6단계 — Vercel 배포

1. [vercel.com](https://vercel.com) → `Sign Up` → GitHub 계정으로 로그인
2. 대시보드 → `Add New` → `Project`
3. `Import Git Repository` → `DO0OG/Ari-VoiceCommand` 선택
4. 설정 화면에서:
   - **Framework Preset**: `Next.js` (자동 감지됨)
   - **Root Directory**: `market/web` ← **이게 중요**
5. `Environment Variables` 섹션에서 아래 3개 추가:

| Key | Value |
|-----|-------|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase Settings → API → Project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase Settings → API → **anon** key |
| `NEXT_PUBLIC_SUPABASE_FUNCTIONS_URL` | `https://<프로젝트ID>.supabase.co/functions/v1` |

6. `Deploy` 클릭 → 배포 완료 후 도메인 확인 (예: `ari-marketplace.vercel.app`)

---

## 7단계 — .env.local 작성 (로컬 개발용)

`d:/Git/Ari-VoiceCommand/market/web/` 에 `.env.local` 파일 생성:

```env
NEXT_PUBLIC_SUPABASE_URL=https://<프로젝트ID>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon_key>
NEXT_PUBLIC_SUPABASE_FUNCTIONS_URL=https://<프로젝트ID>.supabase.co/functions/v1
```

> `.env.local`은 `.gitignore`에 포함되어 있어 GitHub에 올라가지 않습니다.

---

## 완료 후 확인

- `https://ari-marketplace.vercel.app/marketplace` 접속되는지 확인
- GitHub 로그인 → 대시보드 진입 확인
- 테스트 플러그인 ZIP 업로드 → GitHub Actions 탭에서 `Plugin Validation Pipeline` 워크플로 실행 여부 확인

# Ari 플러그인 마켓플레이스 — 구현 명세서

> **대상**: Codex 구현 / Claude Code 검증
> **기준 코드베이스**: `Ari-VoiceCommand-main`
> **핵심 연동 파일**: `VoiceCommand/core/plugin_loader.py`, `VoiceCommand/core/plugin_sandbox.py`, `docs/PLUGIN_GUIDE.md`

---

## 역할 구분 원칙

| 기호 | 담당자 | 설명 |
|------|--------|------|
| **[Codex]** | AI (코드 생성) | 파일 작성, 코드 구현, YAML/SQL/TSX 생성 |
| **[개발자]** | 사람 (수동 작업) | 계정 생성, 클릭, 시크릿 입력, 배포 확인 |

---

## 기술 스택 (전체 무료)

| 역할 | 기술 | 비용 |
|------|------|------|
| 인증 | GitHub OAuth (Supabase Auth) | **무료** |
| DB + Storage | Supabase 무료 티어 | **무료** (500MB DB, 1GB Storage) |
| 검증 자동화 | GitHub Actions | **무료** (퍼블릭 레포: 무제한, 프라이빗: 월 2,000분) |
| 보안 분석 | semgrep OSS + bandit + pylint | **무료** (오픈소스) |
| 바이러스 스캔 | ClamAV | **무료** (오픈소스) |
| 프론트엔드 | Next.js 14 + Tailwind CSS | **무료** |
| 배포 | Vercel 무료 티어 | **무료** |
| 이메일 알림 | Resend 무료 티어 | **무료** (하루 100건) |

> **AI 코드 리뷰는 semgrep OSS로 대체** — Claude API 없이 동등한 보안 수준 달성.
> semgrep은 OWASP Top 10, CWE 패턴, Python 보안 규칙을 무료로 제공합니다.

---

## 전제 조건 및 규격 제약

### plugin.json 필수 필드

기존 `plugin_loader.py`의 `_load_single_plugin()`이 `PLUGIN_INFO` 딕셔너리를 파싱한다.

```json
{
  "name": "my_plugin",
  "version": "0.1.0",
  "api_version": "1.0",
  "description": "플러그인 설명",
  "author": "github_login",
  "commands": ["날씨", "기온"],
  "permissions": ["internet"],
  "entry": "sit_toggle.py"
}
```

**제약사항**:
- `api_version`은 반드시 `"1.0"` (`plugin_loader.py`의 `_COMPATIBLE_API_VERSIONS = {"1.0"}` 기준)
- `name`은 파일명과 일치, LLM tool 이름 충돌 방지를 위해 `{author}_` 접두사 권장
- `entry` 파일은 ZIP 루트에 위치해야 함

### 플러그인 ZIP 구조

```
my_plugin.zip
├── plugin.json       ← 필수
├── sit_toggle.py     ← entry 파일 (필수, 파일명 자유)
└── ...               ← 기타 의존 파일
```

### 설치 경로

```
%AppData%\Ari\plugins\   (Windows EXE 환경)
VoiceCommand/plugins/    (개발 환경)
```

---

## 백엔드 구현

### Phase 1 — 기반 인프라

---

#### 1. Supabase DB 스키마

**[개발자]** Supabase 대시보드에서 새 프로젝트 생성 → SQL Editor에서 아래 파일 실행

**[Codex]** 파일 작성: `supabase/migrations/001_init.sql`

```sql
-- 개발자 테이블
CREATE TABLE developers (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  github_id    TEXT UNIQUE NOT NULL,
  github_login TEXT NOT NULL,
  email        TEXT,
  created_at   TIMESTAMPTZ DEFAULT now()
);

-- 플러그인 테이블
CREATE TABLE plugins (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  developer_id   UUID REFERENCES developers(id) ON DELETE CASCADE,
  name           TEXT NOT NULL,
  version        TEXT NOT NULL,
  api_version    TEXT NOT NULL DEFAULT '1.0',
  description    TEXT,
  commands       TEXT[],
  permissions    TEXT[],
  zip_url        TEXT,
  release_url    TEXT,
  status         TEXT DEFAULT 'pending',   -- pending | approved | rejected
  review_report  JSONB,
  install_count  INT DEFAULT 0,
  reviewed_at    TIMESTAMPTZ,
  created_at     TIMESTAMPTZ DEFAULT now()
);

-- 설치 이력
CREATE TABLE installs (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  plugin_id    UUID REFERENCES plugins(id) ON DELETE CASCADE,
  installed_at TIMESTAMPTZ DEFAULT now()
);

-- RLS 활성화
ALTER TABLE developers ENABLE ROW LEVEL SECURITY;
ALTER TABLE plugins ENABLE ROW LEVEL SECURITY;
ALTER TABLE installs ENABLE ROW LEVEL SECURITY;

-- 개발자는 자신의 플러그인만 수정 가능
CREATE POLICY "developers_own_plugins" ON plugins
  FOR ALL USING (developer_id = (
    SELECT id FROM developers WHERE github_id = auth.uid()::TEXT
  ));

-- 누구나 approved 플러그인 조회 가능
CREATE POLICY "public_read_approved" ON plugins
  FOR SELECT USING (status = 'approved');
```

**검증 포인트**:
- `api_version` 기본값이 `'1.0'`인지 확인
- RLS 정책이 올바르게 적용되는지 확인

---

#### 2. GitHub OAuth 연동

**[개발자]** 다음 순서로 직접 처리:
1. GitHub `Settings > Developer settings > OAuth Apps > New OAuth App` 등록
   - `Authorization callback URL`: `https://<supabase-project>.supabase.co/auth/v1/callback`
2. Supabase Dashboard → Authentication → Providers → GitHub 활성화 → Client ID / Secret 입력

**[Codex]** 파일 작성: `supabase/functions/auth-callback/index.ts`

```typescript
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

Deno.serve(async (req) => {
  const url = new URL(req.url);
  const code = url.searchParams.get("code");

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
  );

  const { data: { user } } = await supabase.auth.exchangeCodeForSession(code!);

  if (user) {
    await supabase.from("developers").upsert({
      github_id: user.user_metadata.provider_id,
      github_login: user.user_metadata.user_name,
      email: user.email,
    }, { onConflict: "github_id" });
  }

  return Response.redirect(`${Deno.env.get("SITE_URL")}/dashboard`);
});
```

---

#### 3. Supabase Storage 버킷 설정

**[개발자]** Supabase Dashboard → Storage → 아래 SQL 실행 (또는 UI로 버킷 직접 생성)

**[Codex]** 파일 작성: `supabase/storage/buckets.sql`

```sql
-- 업로드 버킷 (비공개, 검증 전)
INSERT INTO storage.buckets (id, name, public, file_size_limit)
VALUES ('plugin-uploads', 'plugin-uploads', FALSE, 5242880);  -- 5MB 제한

-- 릴리스 버킷 (공개, 승인된 플러그인)
INSERT INTO storage.buckets (id, name, public)
VALUES ('plugin-releases', 'plugin-releases', TRUE);

-- 업로드 정책: 인증된 사용자만
CREATE POLICY "auth_upload_only" ON storage.objects
  FOR INSERT TO authenticated
  USING (bucket_id = 'plugin-uploads');

-- 릴리스 정책: 누구나 다운로드
CREATE POLICY "public_download" ON storage.objects
  FOR SELECT USING (bucket_id = 'plugin-releases');
```

---

### Phase 2 — 플러그인 업로드 API

#### 4. 업로드 엔드포인트

**[Codex]** 파일 작성: `supabase/functions/upload-plugin/index.ts`

처리 흐름:
1. JWT 검증 → 개발자 신원 확인
2. `multipart/form-data`에서 ZIP 파일 추출
3. ZIP 내부 `plugin.json` 파싱 및 유효성 검사
4. Supabase Storage `plugin-uploads/`에 저장
5. `plugins` 테이블에 `status: 'pending'`으로 레코드 생성
6. GitHub Actions 워크플로우 트리거 (`workflow_dispatch`)

```typescript
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import * as zip from "https://deno.land/x/zipjs/index.js";

const REQUIRED_FIELDS = ["name", "version", "api_version", "description", "entry"];
const SUPPORTED_API_VERSIONS = ["1.0"];

Deno.serve(async (req) => {
  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
  );

  const token = req.headers.get("Authorization")?.replace("Bearer ", "");
  const { data: { user }, error: authError } = await supabase.auth.getUser(token!);
  if (authError || !user) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), { status: 401 });
  }

  const formData = await req.formData();
  const file = formData.get("plugin") as File;

  const pluginMeta = await extractPluginJson(file);
  const validationError = validatePluginMeta(pluginMeta, REQUIRED_FIELDS, SUPPORTED_API_VERSIONS);
  if (validationError) {
    return new Response(JSON.stringify({ error: validationError }), { status: 400 });
  }

  const filePath = `${user.id}/${pluginMeta.name}-${pluginMeta.version}.zip`;
  const { data: storageData } = await supabase.storage
    .from("plugin-uploads")
    .upload(filePath, file);

  const { data: plugin } = await supabase.from("plugins").insert({
    developer_id: (await getDeveloperId(supabase, user)).id,
    name: pluginMeta.name,
    version: pluginMeta.version,
    api_version: pluginMeta.api_version,
    description: pluginMeta.description,
    commands: pluginMeta.commands || [],
    permissions: pluginMeta.permissions || [],
    zip_url: storageData!.path,
    status: "pending",
  }).select().single();

  await triggerValidation(plugin!.id, user.id);

  return new Response(JSON.stringify({ plugin_id: plugin!.id, status: "pending" }));
});

async function triggerValidation(pluginId: string, developerId: string) {
  await fetch(
    `https://api.github.com/repos/${Deno.env.get("GH_REPO")}/actions/workflows/validate-plugin.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${Deno.env.get("GH_PAT")}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ref: "main",
        inputs: { plugin_id: pluginId, developer_id: developerId },
      }),
    }
  );
}
```

**[개발자]** GitHub PAT 발급: `Settings > Developer settings > Personal access tokens` → `workflow` 권한 포함 → Supabase Edge Function 환경변수에 `GH_PAT` 등록

---

### Phase 3 — 검증 파이프라인 (GitHub Actions)

#### 5. 메인 검증 워크플로우

**[Codex]** 파일 작성: `.github/workflows/validate-plugin.yml`

```yaml
name: Plugin Validation Pipeline

on:
  workflow_dispatch:
    inputs:
      plugin_id:
        required: true
        description: "Supabase plugins 테이블의 UUID"
      developer_id:
        required: true
        description: "Supabase auth.users의 UUID"

jobs:
  validate:
    runs-on: ubuntu-latest
    env:
      PLUGIN_ID: ${{ inputs.plugin_id }}
      DEVELOPER_ID: ${{ inputs.developer_id }}
      SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
      SUPABASE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}

    steps:
      - uses: actions/checkout@v4

      - name: Python 환경 설정
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: 의존성 설치
        run: |
          pip install supabase bandit pylint requests semgrep
          sudo apt-get install -y clamav clamav-daemon
          sudo freshclam

      - name: 플러그인 다운로드
        run: python marketplace/scripts/download_plugin.py

      # STEP 1: 바이러스 스캔
      - name: ClamAV 바이러스 스캔
        id: clamav
        run: |
          clamscan -r ./plugin/ --infected --no-summary \
            --log=clamav_result.txt || true
          python marketplace/scripts/check_clamav.py

      # STEP 2: 정적 분석 (bandit + pylint)
      - name: Bandit 보안 분석
        if: success()
        run: |
          bandit -r ./plugin/ -f json -o bandit_result.json \
            --severity-level medium || true

      - name: Pylint 코드 품질
        if: success()
        run: |
          pylint ./plugin/ --output-format=json \
            --disable=C,R > pylint_result.json || true

      - name: 정적 분석 판정
        if: success()
        run: python marketplace/scripts/check_static.py

      # STEP 3: semgrep 보안 규칙 스캔 (AI 리뷰 대체, 완전 무료)
      - name: semgrep 보안 스캔
        if: success()
        run: python marketplace/scripts/semgrep_review.py

      # 최종 판정 (항상 실행)
      - name: 결과 집계 & DB 반영
        if: always()
        run: python marketplace/scripts/finalize.py
```

**[개발자]** GitHub Secrets 등록: `레포지토리 Settings > Secrets and variables > Actions`

```
SUPABASE_URL              ← Supabase 프로젝트 URL
SUPABASE_SERVICE_ROLE_KEY ← Supabase Service Role Key
GH_PAT                    ← workflow_dispatch 트리거용 PAT
GH_REPO                   ← 예: DO0OG/Ari-VoiceCommand
```

> **주의**: `ANTHROPIC_API_KEY`는 불필요합니다. semgrep으로 대체했습니다.

---

#### 6. 플러그인 다운로드 스크립트

**[Codex]** 파일 작성: `marketplace/scripts/download_plugin.py`

```python
import os, io, json, zipfile, requests
from supabase import create_client

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

plugin = supabase.table("plugins") \
    .select("*") \
    .eq("id", os.environ["PLUGIN_ID"]) \
    .single() \
    .execute().data

signed = supabase.storage.from_("plugin-uploads") \
    .create_signed_url(plugin["zip_url"], 300)

r = requests.get(signed["signedURL"])
os.makedirs("./plugin", exist_ok=True)

with zipfile.ZipFile(io.BytesIO(r.content)) as z:
    z.extractall("./plugin/")

with open("plugin_meta.json", "w") as f:
    json.dump(plugin, f, ensure_ascii=False)

print(f"다운로드 완료: {plugin['name']} v{plugin['version']}")
```

---

#### 7. ClamAV 바이러스 스캔 스크립트

**[Codex]** 파일 작성: `marketplace/scripts/check_clamav.py`

```python
import sys, json

infected_files = []
with open("clamav_result.txt") as f:
    for line in f:
        if "FOUND" in line:
            infected_files.append(line.strip())

if infected_files:
    result = {
        "passed": False,
        "stage": "virus_scan",
        "reason": "virus_detected",
        "infected_files": infected_files,
    }
    with open("clamav_fail.json", "w") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"바이러스 감지: {len(infected_files)}개 파일")
    sys.exit(1)

print("바이러스 스캔 통과")
```

---

#### 8. 정적 분석 스크립트

**[Codex]** 파일 작성: `marketplace/scripts/check_static.py`

```python
import json, sys, glob, re

bandit_data = json.load(open("bandit_result.json"))
pylint_data = json.load(open("pylint_result.json"))

high_issues = [
    r for r in bandit_data.get("results", [])
    if r["issue_severity"] in ("HIGH", "CRITICAL")
]

errors = [r for r in pylint_data if r.get("type") == "error"]

# plugin_sandbox.py 우회 패턴 탐지 (exec/eval 직접 사용)
dangerous_patterns = []
DANGER_RE = re.compile(r'\b(exec|eval|compile|__import__)\s*\(')
for path in glob.glob("./plugin/**/*.py", recursive=True):
    with open(path) as f:
        for i, line in enumerate(f, 1):
            if DANGER_RE.search(line):
                dangerous_patterns.append({"file": path, "line": i, "content": line.strip()})

failed = len(high_issues) > 0 or len(errors) > 5 or len(dangerous_patterns) > 0

if failed:
    result = {
        "passed": False,
        "stage": "static_analysis",
        "reason": "static_analysis_failed",
        "bandit_high": high_issues,
        "pylint_errors": errors[:20],
        "dangerous_patterns": dangerous_patterns,
    }
    with open("static_fail.json", "w") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"정적 분석 실패 — bandit: {len(high_issues)}건, pylint: {len(errors)}건, 위험 패턴: {len(dangerous_patterns)}건")
    sys.exit(1)

print("정적 분석 통과")
```

---

#### 9. semgrep 보안 스캔 스크립트 (Claude API 대체 — 완전 무료)

**[Codex]** 파일 작성: `marketplace/scripts/semgrep_review.py`

semgrep OSS 규칙셋을 사용해 OWASP/CWE 수준의 보안 스캔을 수행합니다. API 키 불필요.

```python
"""
semgrep OSS 기반 보안 스캔.
사용 규칙셋:
  - p/python        : Python 일반 보안
  - p/secrets       : 하드코딩된 시크릿/API 키 탐지
  - p/owasp-top-ten : OWASP Top 10
규칙셋은 semgrep registry에서 자동 다운로드 (무료, 로그인 불필요).
"""
import json, subprocess, sys, os

RULESETS = ["p/python", "p/secrets", "p/owasp-top-ten"]

# semgrep 실행
cmd = [
    "semgrep", "--config", ",".join(RULESETS),
    "./plugin/", "--json", "--quiet",
    "--output", "semgrep_result.json",
]
proc = subprocess.run(cmd, capture_output=True, text=True)

# 결과 파싱
try:
    data = json.load(open("semgrep_result.json"))
except Exception:
    data = {"results": []}

findings = data.get("results", [])

# 심각도별 분류
critical_high = [f for f in findings if f.get("extra", {}).get("severity") in ("ERROR", "WARNING")]
low_info      = [f for f in findings if f.get("extra", {}).get("severity") in ("INFO",)]

# Ari 특화 추가 검사 (semgrep이 놓칠 수 있는 패턴)
import glob, re, ast

ari_issues = []

# 1. permissions 선언 vs 실제 코드 불일치 검사
meta = json.load(open("plugin_meta.json"))
declared_perms = set(meta.get("permissions", []))

for path in glob.glob("./plugin/**/*.py", recursive=True):
    src = open(path, encoding="utf-8", errors="replace").read()
    # internet 미선언인데 네트워크 사용
    if "internet" not in declared_perms:
        if re.search(r'\b(requests|urllib|httpx|aiohttp|socket)\b', src):
            ari_issues.append({
                "file": path, "severity": "high",
                "type": "permissions_mismatch",
                "description": "permissions에 'internet' 미선언이나 네트워크 코드 존재"
            })
    # 파일시스템 접근 (AppData\\Ari 외부)
    if re.search(r'open\s*\(\s*["\'][^"\']*(?:\.\.[\\/]|[A-Z]:\\(?!Users\\[^\\]+\\AppData\\Roaming\\Ari))', src):
        ari_issues.append({
            "file": path, "severity": "high",
            "type": "filesystem_escape",
            "description": "AppData\\Ari 외부 경로 파일 접근 의심"
        })

# 2. PLUGIN_INFO 딕셔너리 존재 여부
entry_file = os.path.join("./plugin", meta.get("entry", "main.py"))
if os.path.exists(entry_file):
    entry_src = open(entry_file, encoding="utf-8", errors="replace").read()
    if "PLUGIN_INFO" not in entry_src:
        ari_issues.append({
            "file": entry_file, "severity": "medium",
            "type": "missing_plugin_info",
            "description": "PLUGIN_INFO 딕셔너리가 없음"
        })
    if "def register(" not in entry_src:
        ari_issues.append({
            "file": entry_file, "severity": "high",
            "type": "missing_register",
            "description": "register(context) 함수가 없음"
        })

# 판정
all_issues = critical_high + ari_issues
fatal = [i for i in all_issues if i.get("extra", {}).get("severity") == "ERROR"
         or i.get("severity") in ("high", "critical")]

result = {
    "passed": len(fatal) == 0,
    "risk_level": "critical" if any(i.get("severity") == "critical" for i in ari_issues)
                  else "high" if fatal
                  else "medium" if all_issues
                  else "low",
    "semgrep_findings": len(critical_high),
    "ari_issues": ari_issues,
    "low_info_count": len(low_info),
    "summary": f"semgrep {len(critical_high)}건, Ari 특화 {len(ari_issues)}건 발견"
               if all_issues else "이슈 없음",
}

with open("semgrep_result_summary.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

if not result["passed"]:
    print(f"semgrep 스캔 실패: {result['risk_level']} — {result['summary']}")
    sys.exit(1)

print(f"semgrep 스캔 통과: risk={result['risk_level']}")
```

**검증 포인트**:
- `p/secrets` 규칙이 하드코딩된 API 키를 탐지하는지 확인
- `permissions` 불일치가 `ari_issues`에 기록되는지 확인
- `register(context)` 누락 시 `fatal` 목록에 포함되는지 확인

---

#### 10. 최종 판정 & DB 반영 스크립트

**[Codex]** 파일 작성: `marketplace/scripts/finalize.py`

```python
import json, os, io, requests
from supabase import create_client

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
plugin_id = os.environ["PLUGIN_ID"]

def load_json(path):
    try:
        return json.load(open(path))
    except Exception:
        return None

clamav_fail     = load_json("clamav_fail.json")
static_fail     = load_json("static_fail.json")
semgrep_result  = load_json("semgrep_result_summary.json")
meta            = load_json("plugin_meta.json")

stages = {
    "virus_scan":      {"passed": clamav_fail is None,   "detail": clamav_fail},
    "static_analysis": {"passed": static_fail is None,   "detail": static_fail},
    "semgrep_review":  {"passed": semgrep_result is not None and semgrep_result.get("passed", False),
                        "detail": semgrep_result},
}

all_passed = all(s["passed"] for s in stages.values())
status = "approved" if all_passed else "rejected"

report = {
    "status": status,
    "stages": stages,
    "summary": semgrep_result.get("summary", "") if semgrep_result else "",
}

update_data = {
    "status": status,
    "review_report": report,
    "reviewed_at": "now()",
}

if status == "approved":
    plugin = supabase.table("plugins").select("zip_url, name, version") \
        .eq("id", plugin_id).single().execute().data
    src_path = plugin["zip_url"]
    dst_path = f"{plugin['name']}-{plugin['version']}.zip"
    signed = supabase.storage.from_("plugin-uploads").create_signed_url(src_path, 60)
    content = requests.get(signed["signedURL"]).content
    supabase.storage.from_("plugin-releases").upload(dst_path, content)
    public_url = supabase.storage.from_("plugin-releases").get_public_url(dst_path)
    update_data["release_url"] = public_url

supabase.table("plugins").update(update_data).eq("id", plugin_id).execute()

supabase.functions.invoke("notify-developer", {
    "plugin_id": plugin_id,
    "status": status,
    "report": report,
})

icon = "✅" if status == "approved" else "❌"
print(f"{icon} 최종 판정: {status} → DB 반영 완료")
```

---

### Phase 4 — 마켓 API (Supabase Edge Functions)

#### 11. 플러그인 목록 조회 API

**[Codex]** 파일 작성: `supabase/functions/get-plugins/index.ts`

```typescript
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

Deno.serve(async (req) => {
  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
  );
  const url = new URL(req.url);
  const search = url.searchParams.get("search") || "";
  const sort = url.searchParams.get("sort") || "created_at";
  const page = parseInt(url.searchParams.get("page") || "1");
  const limit = 20;

  let query = supabase
    .from("plugins")
    .select("id, name, version, description, commands, install_count, created_at, developers(github_login)")
    .eq("status", "approved")
    .order(sort, { ascending: false })
    .range((page - 1) * limit, page * limit - 1);

  if (search) {
    query = query.or(`name.ilike.%${search}%,description.ilike.%${search}%`);
  }

  const { data, error } = await query;
  if (error) return new Response(JSON.stringify({ error }), { status: 500 });

  return new Response(JSON.stringify(data));
});
```

#### 12. 플러그인 상세 조회 API

**[Codex]** 파일 작성: `supabase/functions/get-plugin/index.ts`

- `plugin_id`로 상세 정보 + `review_report` 반환
- 비인증 요청도 `approved` 상태면 조회 가능

#### 13. 플러그인 설치 카운트 API

**[Codex]** 파일 작성: `supabase/functions/install-plugin/index.ts`

- `release_url` 반환 (공개 다운로드 URL)
- `installs` 테이블에 기록
- `plugins.install_count` 1 증가

#### 14. 개발자 대시보드 API

**[Codex]** 파일 작성: `supabase/functions/my-plugins/index.ts`

- JWT 검증 후 본인 플러그인 전체 반환 (`status` 무관)
- `review_report` 포함 (반려 사유 확인용)

#### 15. 개발자 알림 Edge Function

**[개발자]** Resend 계정 생성 (무료 티어, 신용카드 불필요) → API 키 발급 → Supabase Edge Function 환경변수 `RESEND_API_KEY` 등록

**[Codex]** 파일 작성: `supabase/functions/notify-developer/index.ts`

```typescript
import { Resend } from "https://esm.sh/resend";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

Deno.serve(async (req) => {
  const { plugin_id, status, report } = await req.json();
  const resend = new Resend(Deno.env.get("RESEND_API_KEY"));

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
  );
  const { data: plugin } = await supabase
    .from("plugins")
    .select("name, version, developers(email, github_login)")
    .eq("id", plugin_id)
    .single();

  const icon = status === "approved" ? "✅" : "❌";
  const subject = `${icon} [Ari Marketplace] "${plugin.name}" 심사 결과: ${status === "approved" ? "승인" : "반려"}`;

  const stageReport = Object.entries(report.stages)
    .map(([stage, result]: any) =>
      `${result.passed ? "✅" : "❌"} ${stage}: ${result.passed ? "통과" : JSON.stringify(result.detail, null, 2)}`
    ).join("\n\n");

  await resend.emails.send({
    from: "Ari Marketplace <noreply@your-domain.com>",
    to: plugin.developers.email,
    subject,
    text: `${plugin.developers.github_login}님의 플러그인 "${plugin.name} v${plugin.version}" 심사가 완료되었습니다.\n\n${stageReport}`,
  });

  return new Response(JSON.stringify({ sent: true }));
});
```

---

## 프론트엔드 구현

### Phase 1 — 프로젝트 세팅

#### 1. Next.js 프로젝트 생성

**[개발자]** 터미널에서 직접 실행:

```bash
npx create-next-app@latest ari-marketplace \
  --typescript --tailwind --app --src-dir
cd ari-marketplace
npm install @supabase/supabase-js @supabase/ssr jszip
```

**[Codex]** 디렉토리 구조 생성 및 파일 작성:

```
ari-marketplace/
├── src/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                    ← 루트 → /marketplace 리다이렉트
│   │   ├── auth/callback/route.ts      ← OAuth 콜백 처리
│   │   ├── marketplace/
│   │   │   ├── page.tsx                ← 마켓 메인
│   │   │   └── [id]/page.tsx           ← 플러그인 상세
│   │   └── dashboard/
│   │       ├── page.tsx                ← 개발자 대시보드
│   │       └── upload/page.tsx         ← 업로드 폼
│   ├── components/
│   │   ├── AuthProvider.tsx
│   │   ├── PluginCard.tsx
│   │   ├── PluginGrid.tsx
│   │   ├── SearchBar.tsx
│   │   ├── ReviewReport.tsx
│   │   └── UploadForm.tsx
│   └── lib/
│       └── supabase.ts
├── .env.local                          ← [개발자] 직접 작성
└── vercel.json
```

#### 2. Supabase 클라이언트 설정

**[Codex]** 파일 작성: `src/lib/supabase.ts`

```typescript
import { createBrowserClient } from "@supabase/ssr";

export const supabase = createBrowserClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
);

export const signInWithGitHub = () =>
  supabase.auth.signInWithOAuth({
    provider: "github",
    options: { redirectTo: `${window.location.origin}/auth/callback` },
  });
```

**[개발자]** `.env.local` 직접 작성:

```env
NEXT_PUBLIC_SUPABASE_URL=https://<project>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon_key>
```

---

### Phase 2 — 마켓 페이지

#### 3. 마켓 메인 페이지 & 카드 컴포넌트

**[Codex]** 파일 작성: `src/app/marketplace/page.tsx`, `src/components/PluginCard.tsx`, `src/components/PluginGrid.tsx`

```tsx
// PluginCard.tsx
export function PluginCard({ plugin }: { plugin: Plugin }) {
  return (
    <div className="border rounded-lg p-4 hover:shadow-md transition">
      <div className="flex items-start justify-between">
        <h3 className="font-semibold">{plugin.name}</h3>
        <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
          ✅ 검증 완료
        </span>
      </div>
      <p className="text-sm text-gray-500 mt-1 line-clamp-2">{plugin.description}</p>
      <div className="flex flex-wrap gap-1 mt-2">
        {plugin.commands?.map(cmd => (
          <span key={cmd} className="text-xs bg-gray-100 px-2 py-0.5 rounded">{cmd}</span>
        ))}
      </div>
      <div className="flex items-center justify-between mt-3 text-xs text-gray-400">
        <span>@{plugin.developers?.github_login}</span>
        <span>↓ {plugin.install_count.toLocaleString()}</span>
      </div>
    </div>
  );
}
```

#### 4. 검색 & 필터 컴포넌트

**[Codex]** 파일 작성: `src/components/SearchBar.tsx`

- 이름 / 설명 검색 (디바운스 300ms)
- 정렬 셀렉트: `최신순` / `인기순`

#### 5. 플러그인 상세 페이지

**[Codex]** 파일 작성: `src/app/marketplace/[id]/page.tsx`, `src/components/ReviewReport.tsx`

상세 페이지 표시 내용:
- 플러그인 전체 정보
- 검증 단계별 통과 뱃지
- 설치 방법 안내:

```
📥 설치 방법

1. 아래 "다운로드" 버튼을 클릭해 ZIP 파일을 받습니다.
2. 다운로드한 ZIP 파일을 아래 경로에 그대로 복사합니다:
   • 실행 파일(EXE): %AppData%\Ari\plugins\
   • 개발 환경:      VoiceCommand/plugins/
3. Ari를 재시작하거나, 설정창 > 확장 탭에서 "다시 적용"을 클릭합니다.
```

검증 리포트 시각화:
```
① 바이러스 스캔 (ClamAV)            ✅ 통과
② 정적 분석 (bandit+pylint)         ✅ 통과
③ semgrep 보안 스캔 (OWASP/CWE)     ✅ 통과  risk: low
```

반려 시:
```
③ semgrep 보안 스캔  ❌ 실패
   └ main.py:42  하드코딩된 API 키 탐지 (p/secrets)
   └ utils.py:17  exec() 직접 호출 감지
```

---

### Phase 3 — 개발자 포털

#### 6. 개발자 대시보드

**[Codex]** 파일 작성: `src/app/dashboard/page.tsx`, `src/components/MyPluginList.tsx`

- GitHub OAuth 로그인 필요 (미인증 시 리다이렉트)
- 내 플러그인 상태 표시:
  - `pending` → 🔄 검증 중
  - `approved` → ✅ 승인됨
  - `rejected` → ❌ 반려됨 (리포트 보기 버튼)

#### 7. 플러그인 업로드 폼

**[Codex]** 파일 작성: `src/app/dashboard/upload/page.tsx`, `src/components/UploadForm.tsx`

```tsx
export function UploadForm() {
  const [meta, setMeta] = useState<PluginMeta | null>(null);
  const [status, setStatus] = useState<"idle"|"uploading"|"pending"|"done">("idle");

  const onDrop = async (files: File[]) => {
    const zip = files[0];
    const parsed = await extractPluginJson(zip);  // JSZip 사용
    setMeta(parsed);

    if (parsed.api_version !== "1.0") {
      alert(`api_version "${parsed.api_version}"은 지원되지 않습니다. "1.0"으로 수정하세요.`);
      return;
    }
  };

  // 업로드 후 5초마다 status 폴링
  const pollStatus = (pluginId: string) => {
    const interval = setInterval(async () => {
      const { data } = await supabase
        .from("plugins").select("status").eq("id", pluginId).single();
      if (data?.status !== "pending") {
        setStatus("done");
        clearInterval(interval);
      }
    }, 5000);
  };
}
```

---

### Phase 4 — Ari 앱 연동

#### 8. 마켓플레이스 클라이언트 모듈

**[Codex]** 파일 작성: `VoiceCommand/core/marketplace_client.py`

```python
"""Ari 앱 내 마켓플레이스 연동 클라이언트."""
from __future__ import annotations

import io, json, logging, os, zipfile
import urllib.request
from typing import List, Dict

logger = logging.getLogger(__name__)

MARKETPLACE_API = "https://<supabase-project>.supabase.co/functions/v1"


def fetch_plugins(search: str = "", sort: str = "install_count") -> List[Dict]:
    """승인된 플러그인 목록 조회."""
    url = f"{MARKETPLACE_API}/get-plugins?sort={sort}&search={search}"
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def install_plugin(plugin_id: str, plugin_dir: str) -> bool:
    """플러그인 다운로드 후 plugin_dir에 설치."""
    url = f"{MARKETPLACE_API}/install-plugin"
    req = urllib.request.Request(
        url,
        data=json.dumps({"plugin_id": plugin_id}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())

    release_url = data.get("release_url")
    if not release_url:
        logger.error("release_url 없음")
        return False

    with urllib.request.urlopen(release_url) as r:
        content = r.read()

    os.makedirs(plugin_dir, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        # entry 파일(.py)만 추출 (경로 탐색 방지)
        for member in z.namelist():
            if member.endswith(".py") and "/" not in member:
                z.extract(member, plugin_dir)

    logger.info(f"플러그인 설치 완료: {plugin_id} → {plugin_dir}")
    return True
```

#### 9. 설정창 확장 탭에 마켓 버튼 추가

**[Codex]** 파일 수정: `VoiceCommand/ui/settings_dialog.py`

```python
# 기존 설정창의 확장 탭 내부에 추가
market_btn = QPushButton("🛍️ 마켓플레이스 열기")
market_btn.clicked.connect(
    lambda: QDesktopServices.openUrl(QUrl("https://ari-marketplace.vercel.app"))
)
plugin_tab_layout.addWidget(market_btn)
```

---

## 환경 변수 목록

### [개발자] 직접 등록해야 하는 값

| 위치 | 키 | 획득 방법 |
|------|----|-----------|
| Supabase Edge Functions | `SUPABASE_URL` | Supabase 대시보드 → Settings → API |
| Supabase Edge Functions | `SUPABASE_SERVICE_ROLE_KEY` | 위와 동일 |
| Supabase Edge Functions | `GH_PAT` | GitHub Settings → Personal access tokens (workflow 권한) |
| Supabase Edge Functions | `GH_REPO` | 직접 입력: `DO0OG/Ari-VoiceCommand` |
| Supabase Edge Functions | `RESEND_API_KEY` | resend.com 무료 가입 → API Keys |
| Supabase Edge Functions | `SITE_URL` | 직접 입력: `https://ari-marketplace.vercel.app` |
| GitHub Actions Secrets | `SUPABASE_URL` | 위와 동일 |
| GitHub Actions Secrets | `SUPABASE_SERVICE_ROLE_KEY` | 위와 동일 |
| Next.js `.env.local` | `NEXT_PUBLIC_SUPABASE_URL` | Supabase 대시보드 |
| Next.js `.env.local` | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase 대시보드 → Settings → API → anon key |
| Next.js `.env.local` | `NEXT_PUBLIC_SUPABASE_FUNCTIONS_URL` | `https://<project>.supabase.co/functions/v1` |

> **`ANTHROPIC_API_KEY` 불필요** — semgrep OSS로 AI 리뷰를 완전 대체합니다.

---

## 전체 구현 순서 체크리스트

### [개발자] 수동 작업 (계정/설정)

- [ ] Supabase 프로젝트 생성 (supabase.com)
- [ ] GitHub OAuth App 등록 (`Settings > Developer settings > OAuth Apps`)
- [ ] Supabase Auth → GitHub Provider 활성화 + Client ID/Secret 입력
- [ ] GitHub PAT 발급 (workflow 권한 포함)
- [ ] GitHub Actions Secrets 등록 (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`)
- [ ] Resend 무료 계정 생성 + API 키 발급 → Supabase 환경변수 등록
- [ ] Vercel 계정 연결 + 환경변수 설정 후 배포 확인
- [ ] Supabase SQL Editor에서 `001_init.sql` 실행
- [ ] Supabase Storage 버킷 생성 (`plugin-uploads`, `plugin-releases`)

### [Codex] 코드 작성 (파일 생성)

**백엔드**
- [ ] `supabase/migrations/001_init.sql`
- [ ] `supabase/storage/buckets.sql`
- [ ] `supabase/functions/auth-callback/index.ts`
- [ ] `supabase/functions/upload-plugin/index.ts`
- [ ] `.github/workflows/validate-plugin.yml`
- [ ] `marketplace/scripts/download_plugin.py`
- [ ] `marketplace/scripts/check_clamav.py`
- [ ] `marketplace/scripts/check_static.py`
- [ ] `marketplace/scripts/semgrep_review.py`
- [ ] `marketplace/scripts/finalize.py`
- [ ] `supabase/functions/get-plugins/index.ts`
- [ ] `supabase/functions/get-plugin/index.ts`
- [ ] `supabase/functions/install-plugin/index.ts`
- [ ] `supabase/functions/my-plugins/index.ts`
- [ ] `supabase/functions/notify-developer/index.ts`

**프론트엔드**
- [ ] `src/lib/supabase.ts`
- [ ] `src/components/AuthProvider.tsx`
- [ ] `src/app/marketplace/page.tsx`
- [ ] `src/components/PluginCard.tsx` + `PluginGrid.tsx`
- [ ] `src/components/SearchBar.tsx`
- [ ] `src/app/marketplace/[id]/page.tsx`
- [ ] `src/components/ReviewReport.tsx`
- [ ] `src/app/dashboard/page.tsx`
- [ ] `src/components/UploadForm.tsx`
- [ ] `vercel.json`

**Ari 앱 연동**
- [ ] `VoiceCommand/core/marketplace_client.py`
- [ ] `VoiceCommand/ui/settings_dialog.py` (마켓 버튼 추가)

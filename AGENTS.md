# AGENTS.md — Ari-VoiceCommand 작업 규칙

AI 에이전트(Claude Code, Codex 등)가 이 저장소에서 작업할 때 반드시 따라야 하는 규칙입니다.

---

## 커밋 메시지

Header, Body, Footer는 빈 행으로 구분한다.

```
타입(스코프): 주제

본문

바닥글
```

### 타입

| 타입 | 내용 |
|------|------|
| `feat` | 새로운 기능에 대한 커밋 |
| `fix` | 버그 수정에 대한 커밋 |
| `build` | 빌드 관련 파일 수정 / 모듈 설치 또는 삭제에 대한 커밋 |
| `chore` | 그 외 자잘한 수정에 대한 커밋 |
| `ci` | CI 관련 설정 수정에 대한 커밋 |
| `docs` | 문서 수정에 대한 커밋 |
| `style` | 코드 스타일 혹은 포맷 등에 관한 커밋 |
| `refactor` | 코드 리팩토링에 대한 커밋 |
| `test` | 테스트 코드 수정에 대한 커밋 |
| `perf` | 성능 개선에 대한 커밋 |

### 규칙

- **Header는 필수**, 스코프는 생략 가능
- **제목 맨 앞글자는 대문자**
- Body는 Header에서 표현할 수 없는 상세한 내용 — 충분하면 생략 가능
- Footer는 이슈 참조 등 — 생략 가능 (`Issues #1234`)
- **`Co-Authored-By`, `Signed-off-by` 등 다른 계정 트레일러 절대 금지**
- `v4` 같은 임의 버전 표기 금지 (실제 릴리즈 태그가 아닌 경우)
- 한국어로 작성

### 예시

```
fix(execution): 파일 작업 실패 시 마지막 백업을 자동 복구

실패 후 안내 텍스트만 생성하던 방식에서
restore_last_backup()을 직접 호출하도록 변경.

Issues #76
```

```
docs: 에이전트 작업 규칙 문서 추가
```

---

## 이슈

- 작업 시작 전 이슈 먼저 생성
- **생성 전 기존 이슈 목록 확인** — 중복 이슈 금지
- 제목 형식: `Fix: ...` / `Feat: ...` / `Docs: ...` + 한국어 설명

---

## 브랜치 명명

```
{이슈번호}-{타입}-{설명-kebab-case}
예: 76-fix-품질-보안-라우팅-즉시-개선-1차
    74-fix-tts-listening-indicator-race
```

---

## PR

- **제목**: 이슈 제목과 동일
- **base**: `main`
- **본문 형식**:

```markdown
## Summary

- 변경사항 bullet list

## Test plan

- [x] 검증 항목

Closes #이슈번호
```

---

## GitHub API (gh CLI 없는 환경)

`gh` CLI가 PATH에 없을 경우 git credential + Python urllib으로 직접 호출:

```bash
GH_TOKEN=$(printf "protocol=https\nhost=github.com\n" | git credential fill | grep "^password=" | cut -d= -f2-)
```

한글 본문은 **유니코드 이스케이프(`\uXXXX`)** 로 변환 후 전달:

```bash
py -3.11 -c "print('한글 텍스트'.encode('unicode_escape').decode())"
```

---

## 코드 품질

- **Codacy 이슈 발생하지 않도록** 코드 작성
  - 미사용 임포트(F401), 미정의 이름(F821) 사전 방지
- `py -3.11 VoiceCommand/validate_repo.py --compile-only` 통과 확인 후 커밋
- 관련 unittest 통과 확인 후 커밋

---

## 계정

- author: `DO0OG` (MAD_DOGGO) 계정만
- `Co-Authored-By`, `Signed-off-by` 등 다른 계정 트레일러 **절대 금지**

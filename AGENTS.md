# AGENTS.md — Ari-VoiceCommand 작업 규칙

AI 에이전트(Claude Code, Codex 등)가 이 저장소에서 작업할 때 반드시 따라야 하는 규칙입니다.

---

## 커밋 메시지 (Lore Commit Protocol)

```
<제목: 왜 변경했는지 한 줄 요약>

<본문: 맥락 설명>

Constraint: 외부 제약
Rejected: 검토했으나 거절한 대안 | 거절 이유
Confidence: low|medium|high
Scope-risk: narrow|moderate|broad
Directive: 향후 수정자들을 위한 경고
Tested: 검증된 내용
Not-tested: 미검증 부분
```

### 규칙

- **제목은 "왜"를 설명** — "무엇을"은 diff가 이미 보여줌
- 프리픽스: `Fix:`, `Feat:`, `Docs:`, `Revert:` 등
- 한국어로 작성
- 트레일러는 가치 있을 때만 포함, 없으면 생략 가능
- **`Co-Authored-By` 절대 금지** — contributors에 DO0OG(MAD_DOGGO) 계정만 남아야 함
- 커밋 메시지에 `v4` 같은 임의 버전 표기 금지 (실제 릴리즈 태그가 아닌 경우)

### 예시

```
파일 작업 실패 시 마지막 백업을 자동 복구

실패 후 안내 텍스트만 생성하던 방식에서,
restore_last_backup()을 직접 호출하도록 변경.

Confidence: high
Scope-risk: narrow
Tested: test_execution_engine 통과
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

`gh` CLI가 PATH에 없을 경우 git credential + curl / Python urllib으로 직접 호출:

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
  - `Co-Authored-By` 트레일러 금지 (위 커밋 규칙과 동일)
- `py -3.11 VoiceCommand/validate_repo.py --compile-only` 통과 확인 후 커밋
- 관련 unittest 통과 확인 후 커밋

---

## 계정

- author: `DO0OG` (MAD_DOGGO) 계정만
- `Co-Authored-By`, `Signed-off-by` 등 다른 계정 트레일러 **절대 금지**

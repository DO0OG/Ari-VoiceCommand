설정에서 로컬 MCP 서버를 켜면 (`mcp_server_enabled`) `http://127.0.0.1:8765/mcp` 에서 JSON-RPC 요청을 받습니다.
포트는 설정의 `mcp_server_port` 값으로 바꿀 수 있습니다.

## 필수 환경 변수

서버는 설정만 켜서는 요청을 처리하지 않습니다. 아래 두 환경 변수를 먼저 지정해야 합니다.

| 변수 | 역할 | 미설정 시 |
|------|------|-----------|
| `ARI_MCP_TOKEN` | 인증 토큰. 모든 요청의 `Authorization` 헤더와 대조합니다. | 모든 요청이 **503**으로 거부됩니다. |
| `ARI_MCP_ALLOWED_PATHS` | 파일 도구가 접근할 수 있는 루트 경로 목록. Windows에서는 세미콜론(`;`)으로 구분합니다. | `ari_read_file` / `ari_write_file` 이 모든 경로를 거부합니다. |

PowerShell에서 현재 세션에만 적용:

```powershell
$env:ARI_MCP_TOKEN = "직접-생성한-긴-임의-문자열"
$env:ARI_MCP_ALLOWED_PATHS = "C:\Users\me\Documents;D:\work"
```

로그인 계정에 영구 적용 (새 터미널부터 반영):

```powershell
setx ARI_MCP_TOKEN "직접-생성한-긴-임의-문자열"
setx ARI_MCP_ALLOWED_PATHS "C:\Users\me\Documents;D:\work"
```

토큰은 소스나 설정 파일에 적지 말고 환경 변수로만 두세요.

## 요청 형식

모든 요청에 `Authorization: Bearer <ARI_MCP_TOKEN>` 헤더가 필요합니다.

```powershell
$body = '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8765/mcp" `
  -Headers @{ Authorization = "Bearer $env:ARI_MCP_TOKEN" } `
  -ContentType "application/json" -Body $body
```

파일 읽기 예시:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "ari_read_file",
    "arguments": { "path": "C:\\Users\\me\\Documents\\memo.txt", "start_line": 1, "end_line": 50 }
  }
}
```

## 접근 제어

서버는 로컬 전용입니다. 다음 조건을 모두 만족해야 요청이 처리됩니다.

- `Host` 헤더가 `127.0.0.1`, `localhost`, `[::1]` 중 하나이고 설정된 포트와 일치해야 합니다. 아니면 **403**.
- `Origin` 헤더를 보낸다면 위 호스트의 `http://` 주소와 일치해야 합니다. 아니면 **403**.
- `Authorization` 헤더의 토큰이 `ARI_MCP_TOKEN` 과 일치해야 합니다. 아니면 **401**.
- 파일 도구의 경로는 `ARI_MCP_ALLOWED_PATHS` 의 루트 중 하나 아래에 있어야 합니다. 벗어나면 `File path is outside MCP allowed paths` 오류가 납니다.

## 지원 도구

| 도구 | 설명 |
|------|------|
| `ari_tts` | 전달한 텍스트를 Ari 음성으로 읽습니다. |
| `ari_notify` | 로컬 알림을 표시합니다. |
| `ari_open_app` | 로컬 애플리케이션을 실행합니다. |
| `ari_take_screenshot` | 스크린샷을 찍어 base64로 반환합니다. |
| `ari_get_system_info` | CPU, 메모리, 실행 중 앱 목록을 반환합니다. |
| `ari_read_file` | 로컬 파일 내용을 읽습니다 (`start_line`/`end_line` 범위 지정 가능). 허용 경로 안에서만 동작합니다. |
| `ari_write_file` | 로컬 파일에 내용을 씁니다 (`overwrite` 또는 `append` 모드). 허용 경로 안에서만 동작합니다. |

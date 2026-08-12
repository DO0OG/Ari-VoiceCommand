로컬 MCP 서버는 설정에서 활성화하면 `http://127.0.0.1:8765/mcp` 로 JSON-RPC 요청을 받습니다.
포트는 설정의 `mcp_server_port` 값으로 변경할 수 있습니다.

## 지원 도구

| 도구 | 설명 |
|------|------|
| `ari_tts` | 전달한 텍스트를 Ari 음성으로 읽습니다. |
| `ari_notify` | 로컬 알림을 표시합니다. |
| `ari_open_app` | 로컬 애플리케이션을 실행합니다. |
| `ari_take_screenshot` | 스크린샷을 찍어 base64로 반환합니다. |
| `ari_get_system_info` | CPU, 메모리, 실행 중 앱 목록을 반환합니다. |
| `ari_read_file` | 로컬 파일 내용을 읽습니다 (`start_line`/`end_line` 범위 지정 가능). |
| `ari_write_file` | 로컬 파일에 내용을 씁니다 (`overwrite` 또는 `append` 모드). |

# API 키 보관

키를 읽는 순서는 **프로세스 환경변수 → 런타임 폴더의 `.env` → 암호화 저장소 →
기존 설정 파일**이다. 일반 설정과 비밀정보를 분리하며 기존 설정 페이지를 그대로
사용할 수 있다. 설정 페이지 저장도 `ConfigManager`를 통해 암호화 저장소에 반영한다.

| 기존 설정 이름 | 환경변수 이름 |
|---|---|
| groq_api_key | ARI_GROQ_API_KEY |
| openai_api_key | ARI_OPENAI_API_KEY |
| anthropic_api_key | ARI_ANTHROPIC_API_KEY |
| mistral_api_key | ARI_MISTRAL_API_KEY |
| gemini_api_key | ARI_GEMINI_API_KEY |
| openrouter_api_key | ARI_OPENROUTER_API_KEY |
| nvidia_nim_api_key | ARI_NVIDIA_NIM_API_KEY |
| google_client_secret | ARI_GOOGLE_CLIENT_SECRET |
| fish_api_key | ARI_FISH_API_KEY |
| fish_reference_id | ARI_FISH_REFERENCE_ID |
| telegram_bot_token | ARI_TELEGRAM_BOT_TOKEN |
| openai_tts_api_key | ARI_OPENAI_TTS_API_KEY |
| openai_compat_tts_api_key | ARI_OPENAI_COMPAT_TTS_API_KEY |
| elevenlabs_api_key | ARI_ELEVENLABS_API_KEY |

기존 `SENSITIVE_SETTINGS_KEYS`의 14개 항목을 사용한다. API 인증값 외에 기존에
민감값으로 분류한 `fish_reference_id`도 포함한다.

설정의 LLM 페이지에서 추가한 OpenAI 호환 제공자의 키는 `custom_<id>_api_key`
이름으로 같은 암호화 저장소에 들어간다. 환경변수로 넣으려면
`ARI_CUSTOM_<ID>_API_KEY`(id는 `ari_settings.json`의 `custom_llm_providers` 키)를
쓴다. 제공자를 삭제하면 그 키도 저장소에서 지운다.

PowerShell에서 현재 터미널로 실행하는 앱에만 키를 전달하려면 다음과 같이 설정한다.

```powershell
$env:ARI_GROQ_API_KEY = '발급받은-키'
VoiceCommand/.venv/Scripts/python.exe VoiceCommand/Main.py
```

또는 `ari_settings.json`과 같은 런타임 폴더에 `.env`를 직접 만든다.

```dotenv
ARI_GROQ_API_KEY=발급받은-키
ARI_OPENAI_API_KEY=발급받은-키
```

기본 런타임 폴더는 소스 실행 시 `VoiceCommand/.ari_runtime/`, 배포 실행 시
`%AppData%/Ari/`다. `ARI_APP_DATA_DIR`을 지정했다면 해당 경로를 사용한다.
임의의 현재 작업 폴더나 상위 폴더에서 `.env`를 탐색하지 않는다.
`.env`는 최초 설정 로드 및 저장 시 다시 읽고 변수 치환은 하지 않는다.
비어 있는 값은 다음 저장소로 넘긴다. 환경변수는 실행 중에도 우선한다.
`.env`의 값은 프로세스 환경에 복사하지 않는다.
[python-dotenv 문서](https://bbc2.github.io/python-dotenv/reference/)

## Google Calendar/Gmail 연결

Google Cloud에서 OAuth 클라이언트를 **데스크톱 앱** 유형으로 만들고 Calendar API와 Gmail API를 사용 설정한다.
앱 설정의 에이전트 페이지에 Client ID와 Client Secret을 입력한 뒤 **Google 계정 연결**을 누른다.
브라우저에서 Google 계정과 권한을 확인하면 앱이 이 PC의 임시 주소(`127.0.0.1`)로 결과를 받아 인증을 마친다.
같은 화면의 **Google Calendar/Gmail 도구 사용**이 꺼져 있으면 연결돼 있어도 캘린더·메일 도구는 동작하지 않는다.
인증 토큰은 연결에 쓴 Client ID·Secret과 함께 런타임 폴더의 `google_token.dpapi`에 Windows 사용자 계정에 묶인 DPAPI로 보호해 저장한다.
이전 버전의 평문 `google_token.json`이 있으면 처음 읽을 때 보호 저장으로 옮기고 지운다.
**연결 해제**를 누르면 Google에 토큰 폐기를 요청하고 저장된 토큰 파일을 지운다.
OAuth 동의 화면이 **테스트** 게시 상태이면 갱신 토큰은 7일 뒤 만료되므로 다시 연결해야 한다.

## Windows 저장과 마이그레이션

런타임 폴더의 `ari_secrets.dpapi`에는 사용자 계정에 묶인 DPAPI 암호문만 기록한다.
머신 전체 공유 플래그를 사용하지 않는다. 일반적으로 암호화한 Windows 사용자와
컴퓨터에서 복호화하며, 로밍 프로필 등 예외는 Windows 정책을 따른다.
[Microsoft DPAPI 설명](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)

처음 기존 설정을 읽을 때 다음 순서로 자동 이전한다.

1. 원본 설정 파일 전체를 암호화한 `ari_settings.pre-secrets.<해시>.dpapi` 백업을 만든다.
2. 암호화·복호화 일치를 확인하고 키 저장소를 원자적으로 기록한다.
3. 일반 설정 파일을 모든 비밀 키 항목이 제거된 JSON으로 원자적으로 교체한다.

이미 저장소에 있는 키가 기존 평문 값보다 우선한다. 설정 저장 시 명시적으로 입력한
키는 갱신하며 빈 값은 저장소에서 삭제한다. 환경변수와 동일한 값은 환경 설정으로
간주해 저장소에 복사하지 않는다. 환경변수가 있으면 UI에서 저장한 값보다 계속
우선하므로 저장소의 새 값을 쓰려면 환경 설정을 제거해야 한다.

백업 또는 암호화에 실패하면 원본을 지우지 않는다. 공개 설정 파일 교체만 실패하면
새 키는 이미 암호화 저장되었을 수 있으며, 원본과 백업을 유지하고 실패를 반환한다.
두 파일을 한 트랜잭션으로 교체하지 않으므로 이 순서로 키 소실을 방지한다.
복호화가 실패하면 해당 키를 없는 것으로 취급하고 환경 설정은 계속 사용할 수 있다.
읽을 수 없는 저장소를 덮어쓰지 않는다. 저장 실패 시 설정 창은 입력값을 유지한다.

백업을 복구해야 한다면 같은 Windows 사용자로 DPAPI 복호화를 수행하고 필요한 값을
복원한다. 백업은 원본 전체이므로 외부에 공유하지 않는다. 복원 목적으로 평문을 파일로
만들었다면 사용 후 안전하게 관리해야 한다. 앱은 백업을 자동으로 재주입하지 않는다.

## 비Windows 및 암호화 기능을 사용할 수 없는 환경

환경변수와 사용자가 관리하는 `.env`를 사용한다. 새 키를 앱에서 평문 저장하는
대체 경로는 없다. 암호화가 필요한 저장은 실패를 반환한다. 비밀값이 없는 새 일반
설정 저장은 가능하다.

기존 평문 설정이 있으면 중단을 줄이기 위해 해당 값을 메모리에서 읽되 이전이
보류되었다는 경고를 남긴다. 암호화 백업을 만들 수 없으므로 원본을 유지하며 해당
파일의 저장도 거부한다. Windows에서 이전을 완료하거나, 키를 환경 설정으로 옮기고
기존 원본을 별도로 보관한 뒤 평문 항목을 제거해야 한다. 기존 파일을 자동으로
평문 백업에 복제하지 않는다.

`.env`는 사용자가 선택한 평문 입력 파일이므로 설정 파일과 함께 공유하거나 공개
저장소에 넣지 않는다. 암호화 저장소, 백업, `.env`는 Git 제외 대상이다.
암호화는 디스크의 평문 노출을 줄이며, 같은 사용자 권한으로 실행되는 프로그램이나
실행 중 메모리를 보호하는 경계는 아니다.

## 임베딩 원격 사용 선택

전략·스킬·실행 에피소드의 의미 검색은 로컬 ONNX 임베더를 기본으로 사용합니다.
모델 파일은 필요할 때 내려받아 로컬에서 실행합니다. OpenAI 임베딩으로 바꾸려면
설정 → `에이전트` → `전략 검색`에서 **OpenAI 임베딩 사용 (전략 텍스트 외부 전송)**을
켜세요. `embedding_remote_enabled`의 기본값은 `false`입니다.

이 옵션을 켜고 OpenAI API 키가 설정되어 있으면 `text-embedding-3-small` 요청에
임베더를 호출한 텍스트가 포함됩니다. 여기에는 전략 검색어 외에 작업 목표, 스킬 목표,
작업 에피소드의 목표·요약, 대상 도메인·창·경로, 상태 변경·정책 문맥이 포함될 수 있습니다.
사용자 프로필과 기억 사실은 이 임베딩 경로의 입력에 포함되지 않습니다.
이 경로는 `openai_api_key`를
사용하며 키는 위 표와 같이 암호화 저장소 또는 `ARI_OPENAI_API_KEY` 환경변수에 둡니다.
키가 없으면 원격 임베딩을 사용할 수 없습니다.

## 손상된 설정 백업

손상된 JSON 설정 파일의 원본 바이트는 `SecretStore.backup()`으로 암호화해 `ari_settings.pre-secrets.<hash>.dpapi`에 보관합니다. 복구할 때는 같은 Windows 사용자 계정에서 `unprotect_bytes()`로 복호화한 뒤 `ari_settings.json`에 기록합니다.

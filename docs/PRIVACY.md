# Privacy policy

This document lists what Ari sends over the network, to whom, when, whether it is on by default, and how to turn it off. It was written from the source code of this repository. Third-party services that Ari connects to have their own privacy policies, which this document does not cover.

Ari is a Windows desktop program. The project does not run a server that collects user data, and Ari has no user accounts. The source code was searched for analytics, telemetry, and crash-reporting code (for example Sentry, PostHog, Mixpanel, and Google Analytics) and none was found.

## Data stored on your PC

- Installed builds keep settings and history in `%AppData%\Ari`. When Ari is run from source, they are kept in `VoiceCommand/.ari_runtime` instead. The `ARI_APP_DATA_DIR` environment variable can point to another folder.
- This includes settings, conversation history, the memory database, logs, the text-to-speech audio cache, downloaded embedding models, generated images, and an audit log of agent actions (`audit_log_enabled`, on by default).
- API keys and tokens are stored in a separate file (`ari_secrets.dpapi`) encrypted with the Windows user account (DPAPI).
- Uninstalling Ari does not delete `%AppData%\Ari`. Delete the folder yourself to remove the data.

## What leaves your PC

Features marked "on by default" are active in a new installation. Features that need an API key or a sign-in send nothing until you set that up.

### Update check

- Sends: an HTTPS request to `github.com` for the update manifest (`update.json`, or `update-beta.json` on the beta channel). The request carries a `User-Agent` of `Ari/<version> (Windows)`. GitHub also sees your IP address. Ari does not download or run installers by itself; release notes open in your browser when you choose.
- When: in installed release builds, about once a day. Builds run from source do not check.
- Default: on.
- Turn off: Settings, "Automatically check for updates" (`update_check_enabled`), or clear "Check for updates automatically" on the installer's privacy options page.

### Plugin marketplace

- Sends: requests to the marketplace API (a Supabase Edge Functions endpoint) to list plugins (with your search text and sort order) and to get plugin details. Installing a plugin also sends the plugin ID to the `install-plugin` function, and then downloads the plugin ZIP from the release URL the API returns.
- When: the list is requested when the plugin page of the settings window is created; the other requests happen when you install a plugin.
- Default: no setting turns the list request off. The endpoint can be changed with the `ARI_MARKETPLACE_API` environment variable.

### Language model (LLM)

- Sends: to the provider you select, your messages, recent conversation history, the character and system prompt settings, tool definitions, and the results of tools the model called. Images are sent when an image-analysis tool is used (`vision_enabled`, on by default). A separate request that asks the model to suggest memories from your message is also sent (`fact_extraction_suggestions_enabled`, on by default).
- Providers: Groq, OpenAI, Anthropic, Mistral AI, Google Gemini, OpenRouter, NVIDIA NIM, Ollama (a server on your own PC, `http://localhost:11434` by default), and OpenAI-compatible servers you add yourself.
- Default: the default provider is Groq, which requires an API key. Without a key, no LLM request is made. With a key, a lightweight connection warm-up request (a model list request, no message content) may be sent to the provider when listening starts (`llm_prewarm_enabled`).
- Turn off: do not enter API keys, or choose Ollama for processing on your own PC.

### Speech recognition

- Default provider: Google (`stt_provider`). Ari sends recorded speech audio to Google's speech recognition web service through the SpeechRecognition library.
- When: when Ari is listening for a command. While wake-word detection is on (`wake_word_enabled`, on by default), audio segments that pass a length and loudness check are also transcribed, so with Google they are sent to Google.
- Turn off: choose Whisper as the recognizer. Whisper runs on your PC. Wake-word detection can be turned off in the speech settings. Clearing "Use online speech services" on the installer's privacy options page also switches the recognizer to Whisper.
- Whisper models are downloaded from Hugging Face by the faster-whisper library the first time they are needed, for example with the "Download model" button in the speech settings.

### Speech synthesis

- Default: `tts_mode` is Fish Audio, which needs an API key. Without a key, Ari uses Edge TTS instead. Edge TTS sends the text to be spoken to Microsoft's online speech service through the edge-tts library. Fixed short messages are also synthesized in advance in the background and cached on your PC.
- With a key: Fish Audio (`api.fish.audio`), OpenAI, ElevenLabs, or an OpenAI-compatible server you configure receive the text to be spoken. Voice cloning features upload the reference audio file you choose to ElevenLabs or to the server you configure.
- Turn off: choose local CosyVoice3 as the speech engine. It runs on your PC. Installing it downloads the CosyVoice source code from GitHub, Python packages, and a model from Hugging Face. Clearing "Use online speech services" on the installer's privacy options page stops Edge TTS, including the background pre-synthesis; Ari then shows replies as text bubbles without sound until you choose another engine.

### Text embeddings (memory and skill search)

- Default: a local model. Ari downloads the `Xenova/paraphrase-multilingual-MiniLM-L12-v2` model files from Hugging Face the first time they are needed (a start-up warm-up does this), and then computes embeddings on your PC.
- Remote embeddings: when `embedding_remote_enabled` is turned on and an OpenAI API key is set, text is sent to OpenAI's embedding API instead.
- Default: remote embeddings are off.

### Telegram

- Sends: Ari polls the Telegram Bot API (`api.telegram.org`) for new messages and sends back replies, edited messages, and images that tools created.
- Default: off (`telegram_enabled`). It also needs a bot token and an allow-list of chat IDs; without both, nothing runs.
- Turn off: set `telegram_enabled` to `false` in `ari_settings.json`. The bot token is entered in the settings window or through an environment variable.

### Tools Ari can run on request

These run only when you ask for something that needs them.

- Weather: when no city is named, your approximate location is looked up from your IP address with `ipapi.co`. City names that Ari does not know are looked up with Open-Meteo's geocoding API. The forecast is requested from `api.open-meteo.com` with coordinates.
- Web search: the search text is sent through the `ddgs` web-search library. This document does not list which search engine receives a given query.
- Web pages: Ari can fetch public web pages you or the model choose, and can drive a browser to visit sites. Requests to local or private addresses are refused.
- Image generation: off by default (`image_generation_enabled`). When on, the prompt is sent to OpenAI with your API key.
- Google Calendar and Gmail: off by default (`google_calendar_enabled`). When you connect a Google account, Ari signs in with OAuth in your browser and calls Google's Calendar and Gmail APIs when you ask for them. Use the disconnect action in the agent settings to sign out.

### Downloads you start

- Local LLM setup downloads the Ollama installer from `ollama.com`. Ollama then downloads models itself.
- Local speech setup downloads from GitHub and Hugging Face, as described above.
- Installing a skill from GitHub downloads the repository as a ZIP from `codeload.github.com`.

### Local only

The optional MCP server (`mcp_server_enabled`, off by default) listens on `127.0.0.1` only.

## Contact

Questions and privacy concerns can be raised in the [issue tracker](https://github.com/DO0OG/Ari-VoiceCommand/issues). For security vulnerabilities, use the private "Report a vulnerability" option in the repository's Security tab (see [Release verification and antivirus notes](./SECURITY.md)).

<details>
<summary>한국어</summary>

# 개인정보 처리 방침

이 문서는 Ari가 네트워크로 무엇을, 누구에게, 언제 보내는지, 기본으로 켜져 있는지, 어떻게 끄는지를 정리합니다. 이 저장소의 소스 코드를 바탕으로 작성했습니다. Ari가 연결하는 외부 서비스에는 각자의 개인정보 처리 방침이 있으며, 이 문서는 그 내용을 다루지 않습니다.

Ari는 Windows 데스크톱 프로그램입니다. 이 프로젝트는 사용자 데이터를 수집하는 서버를 운영하지 않으며, Ari에는 사용자 계정이 없습니다. 소스 코드에서 분석·원격 측정·충돌 보고 코드(예: Sentry, PostHog, Mixpanel, Google Analytics)를 검색했으며 찾지 못했습니다.

## PC에 저장되는 데이터

- 설치본은 설정과 기록을 `%AppData%\Ari`에 둡니다. 소스에서 실행하면 `VoiceCommand/.ari_runtime`에 둡니다. `ARI_APP_DATA_DIR` 환경변수로 다른 폴더를 지정할 수 있습니다.
- 설정, 대화 기록, 기억 데이터베이스, 로그, 음성 합성 오디오 캐시, 내려받은 임베딩 모델, 생성한 이미지, 에이전트 동작 감사 기록(`audit_log_enabled`, 기본 켜짐)이 여기에 들어갑니다.
- API 키와 토큰은 Windows 사용자 계정으로 암호화(DPAPI)한 별도 파일(`ari_secrets.dpapi`)에 저장합니다.
- Ari를 제거해도 `%AppData%\Ari`는 지워지지 않습니다. 데이터를 없애려면 폴더를 직접 삭제하세요.

## PC 밖으로 나가는 것

"기본 켜짐"으로 적은 기능은 새로 설치한 상태에서 동작합니다. API 키나 로그인이 필요한 기능은 직접 설정하기 전에는 아무것도 보내지 않습니다.

### 업데이트 확인

- 보내는 것: `github.com`으로 업데이트 manifest(`update.json`, 베타 채널은 `update-beta.json`)를 받는 HTTPS 요청입니다. 요청의 `User-Agent`는 `Ari/<버전> (Windows)`이며, GitHub는 IP 주소도 볼 수 있습니다. Ari가 설치 파일을 직접 내려받거나 실행하지는 않으며, 릴리스 노트는 사용자가 선택할 때 브라우저로 열립니다.
- 시점: 설치된 릴리스 빌드에서 하루에 한 번 정도입니다. 소스에서 실행하면 확인하지 않습니다.
- 기본값: 켜짐.
- 끄는 방법: 설정의 "새 버전을 자동으로 확인합니다"(`update_check_enabled`) 또는 설치 프로그램의 개인정보 관련 선택에서 "자동 업데이트 확인"을 해제하세요.

### 플러그인 마켓플레이스

- 보내는 것: 마켓플레이스 API(Supabase Edge Functions 주소)에 플러그인 목록(검색어와 정렬 기준 포함)과 상세 정보를 요청합니다. 플러그인을 설치하면 `install-plugin` 함수에 플러그인 ID도 보내고, API가 알려 준 릴리스 주소에서 플러그인 ZIP을 내려받습니다.
- 시점: 설정 창의 플러그인 페이지가 만들어질 때 목록을 요청하고, 나머지 요청은 플러그인을 설치할 때 합니다.
- 기본값: 목록 요청을 끄는 설정은 없습니다. 주소는 `ARI_MARKETPLACE_API` 환경변수로 바꿀 수 있습니다.

### 언어 모델(LLM)

- 보내는 것: 선택한 제공자에게 사용자 메시지, 최근 대화 기록, 캐릭터·시스템 프롬프트 설정, 도구 정의, 모델이 호출한 도구의 결과를 보냅니다. 이미지 분석 도구를 쓰면 이미지도 보냅니다(`vision_enabled`, 기본 켜짐). 메시지에서 기억할 내용을 제안받는 별도 요청도 보냅니다(`fact_extraction_suggestions_enabled`, 기본 켜짐).
- 제공자: Groq, OpenAI, Anthropic, Mistral AI, Google Gemini, OpenRouter, NVIDIA NIM, Ollama(내 PC의 서버, 기본 `http://localhost:11434`), 직접 추가한 OpenAI 호환 서버.
- 기본값: 기본 제공자는 Groq이며 API 키가 필요합니다. 키가 없으면 LLM 요청을 하지 않습니다. 키가 있으면 듣기를 시작할 때 연결 예열 요청(모델 목록 요청, 메시지 내용 없음)을 제공자에게 보낼 수 있습니다(`llm_prewarm_enabled`).
- 끄는 방법: API 키를 입력하지 않거나, 내 PC에서 처리하는 Ollama를 선택하세요.

### 음성 인식

- 기본 제공자: Google(`stt_provider`). Ari는 SpeechRecognition 라이브러리를 통해 녹음한 음성 오디오를 Google 음성 인식 웹 서비스로 보냅니다.
- 시점: 명령을 듣고 있을 때입니다. 웨이크워드 감지가 켜져 있으면(`wake_word_enabled`, 기본 켜짐) 길이와 소리 크기 검사를 통과한 오디오 구간도 인식하므로, Google을 쓰면 그 오디오도 Google로 갑니다.
- 끄는 방법: 인식기로 Whisper를 고르세요. Whisper는 내 PC에서 실행됩니다. 웨이크워드 감지는 음성 설정에서 끌 수 있습니다. 설치 프로그램의 개인정보 관련 선택에서 "온라인 음성 서비스 사용"을 해제해도 인식기가 Whisper로 바뀝니다.
- Whisper 모델은 처음 필요할 때 faster-whisper 라이브러리가 Hugging Face에서 내려받습니다(예: 음성 설정의 "모델 다운로드" 버튼).

### 음성 합성

- 기본값: `tts_mode`는 Fish Audio이며 API 키가 필요합니다. 키가 없으면 Ari는 Edge TTS를 씁니다. Edge TTS는 edge-tts 라이브러리를 통해 읽을 텍스트를 Microsoft 온라인 음성 서비스로 보냅니다. 고정된 짧은 메시지는 백그라운드에서 미리 합성해 PC에 캐시합니다.
- 키가 있을 때: Fish Audio(`api.fish.audio`), OpenAI, ElevenLabs, 직접 설정한 OpenAI 호환 서버가 읽을 텍스트를 받습니다. 음성 복제 기능은 선택한 참조 오디오 파일을 ElevenLabs나 설정한 서버로 올립니다.
- 끄는 방법: 음성 엔진으로 로컬 CosyVoice3를 고르세요. 내 PC에서 실행됩니다. 설치할 때 GitHub에서 CosyVoice 소스 코드를, Python 패키지를, Hugging Face에서 모델을 내려받습니다. 설치 프로그램의 개인정보 관련 선택에서 "온라인 음성 서비스 사용"을 해제하면 Edge TTS(백그라운드 사전 합성 포함)를 쓰지 않으며, 다른 엔진을 고르기 전까지 응답은 소리 없이 말풍선 글자로만 나옵니다.

### 텍스트 임베딩(기억·스킬 검색)

- 기본값: 로컬 모델입니다. 처음 필요할 때(시작 시 예열이 이를 수행) Hugging Face에서 `Xenova/paraphrase-multilingual-MiniLM-L12-v2` 모델 파일을 내려받고, 이후 임베딩은 내 PC에서 계산합니다.
- 원격 임베딩: `embedding_remote_enabled`를 켜고 OpenAI API 키를 설정하면 텍스트를 OpenAI 임베딩 API로 보냅니다.
- 기본값: 원격 임베딩은 꺼짐.

### Telegram

- 보내는 것: Ari가 Telegram Bot API(`api.telegram.org`)에서 새 메시지를 가져오고, 답장·수정된 메시지·도구가 만든 이미지를 보냅니다.
- 기본값: 꺼짐(`telegram_enabled`). 봇 토큰과 허용 채팅 ID 목록이 모두 있어야 하며, 없으면 동작하지 않습니다.
- 끄는 방법: `ari_settings.json`에서 `telegram_enabled`를 `false`로 두세요. 봇 토큰은 설정 창이나 환경변수로 입력합니다.

### 요청하면 실행하는 도구

필요한 일을 요청했을 때만 실행됩니다.

- 날씨: 도시를 말하지 않으면 `ipapi.co`로 IP 주소에서 대략적인 위치를 조회합니다. Ari가 모르는 도시 이름은 Open-Meteo 지오코딩 API로 조회하고, 예보는 좌표로 `api.open-meteo.com`에 요청합니다.
- 웹 검색: 검색어를 `ddgs` 웹 검색 라이브러리를 통해 보냅니다. 어떤 검색 엔진이 질의를 받는지는 이 문서에 적지 않았습니다.
- 웹 페이지: 사용자나 모델이 고른 공개 웹 페이지를 가져오고, 브라우저를 조작해 사이트를 방문할 수 있습니다. 로컬·사설 주소 요청은 거부합니다.
- 이미지 생성: 기본 꺼짐(`image_generation_enabled`). 켜면 프롬프트를 사용자의 API 키로 OpenAI에 보냅니다.
- Google 캘린더와 Gmail: 기본 꺼짐(`google_calendar_enabled`). Google 계정을 연결하면 브라우저에서 OAuth로 로그인하고, 요청할 때 Google 캘린더·Gmail API를 호출합니다. 에이전트 설정에서 연결 해제로 로그아웃할 수 있습니다.

### 사용자가 시작하는 내려받기

- 로컬 LLM 설정은 `ollama.com`에서 Ollama 설치 파일을 내려받습니다. 모델은 Ollama가 직접 내려받습니다.
- 로컬 음성 설정은 위에서 설명한 대로 GitHub와 Hugging Face에서 내려받습니다.
- GitHub에서 스킬을 설치하면 `codeload.github.com`에서 저장소를 ZIP으로 내려받습니다.

### 로컬 전용

선택 사항인 MCP 서버(`mcp_server_enabled`, 기본 꺼짐)는 `127.0.0.1`에서만 연결을 받습니다.

## 문의

질문과 개인정보 관련 우려는 [이슈 트래커](https://github.com/DO0OG/Ari-VoiceCommand/issues)에 남겨 주세요. 보안 취약점은 저장소 Security 탭의 비공개 신고 "Report a vulnerability"를 이용해 주세요([릴리스 파일 확인과 백신 검출 안내](./SECURITY.md) 참고).

</details>

<details>
<summary>日本語</summary>

# プライバシーポリシー

この文書は、Ari がネットワークを通じて何を、誰に、いつ送るのか、初期状態でオンかどうか、どうすればオフにできるかをまとめたものです。このリポジトリのソースコードをもとに作成しました。Ari が接続する外部サービスにはそれぞれのプライバシーポリシーがあり、この文書ではそれらを扱いません。

Ari は Windows 用のデスクトッププログラムです。このプロジェクトはユーザーデータを収集するサーバーを運用しておらず、Ari にはユーザーアカウントがありません。ソースコードで分析・テレメトリ・クラッシュレポートのコード(例: Sentry、PostHog、Mixpanel、Google Analytics)を検索しましたが、見つかりませんでした。

## お使いの PC に保存されるデータ

- インストール版は設定と履歴を `%AppData%\Ari` に保存します。ソースから実行した場合は `VoiceCommand/.ari_runtime` に保存します。環境変数 `ARI_APP_DATA_DIR` で別のフォルダーを指定できます。
- 設定、会話履歴、記憶データベース、ログ、音声合成のオーディオキャッシュ、ダウンロードした埋め込みモデル、生成した画像、エージェント動作の監査ログ(`audit_log_enabled`、初期状態でオン)が含まれます。
- API キーとトークンは、Windows のユーザーアカウントで暗号化(DPAPI)した別ファイル(`ari_secrets.dpapi`)に保存します。
- Ari をアンインストールしても `%AppData%\Ari` は削除されません。データを消すにはフォルダーを自分で削除してください。

## PC の外に出るもの

「初期状態でオン」と書いた機能は、新規インストール直後から動作します。API キーやサインインが必要な機能は、自分で設定するまで何も送りません。

### 更新の確認

- 送るもの: `github.com` に更新マニフェスト(`update.json`、ベータチャンネルは `update-beta.json`)を取得する HTTPS リクエストです。リクエストの `User-Agent` は `Ari/<バージョン> (Windows)` で、GitHub には IP アドレスも見えます。Ari がインストーラーを自動でダウンロードしたり実行したりすることはなく、リリースノートは選択したときにブラウザーで開きます。
- 時期: インストールされたリリースビルドで、1日に1回程度です。ソースから実行した場合は確認しません。
- 初期設定: オン。
- オフにする方法: 設定の「新しいバージョンを自動で確認する」(`update_check_enabled`)、またはインストーラーの「プライバシーに関する選択」で「更新を自動的に確認する」をオフにします。

### プラグインマーケットプレイス

- 送るもの: マーケットプレイス API(Supabase Edge Functions のエンドポイント)に、プラグイン一覧(検索語と並べ替え順を含む)と詳細情報を要求します。プラグインをインストールすると、`install-plugin` 関数にプラグイン ID も送り、API が返したリリース URL からプラグインの ZIP をダウンロードします。
- 時期: 設定ウィンドウのプラグインページが作成されるときに一覧を要求し、それ以外のリクエストはプラグインをインストールするときに行います。
- 初期設定: 一覧の要求をオフにする設定はありません。エンドポイントは環境変数 `ARI_MARKETPLACE_API` で変更できます。

### 言語モデル(LLM)

- 送るもの: 選択したプロバイダーに、ユーザーのメッセージ、最近の会話履歴、キャラクターとシステムプロンプトの設定、ツール定義、モデルが呼び出したツールの結果を送ります。画像解析ツールを使うと画像も送ります(`vision_enabled`、初期状態でオン)。メッセージから記憶する内容の候補を提案させる別のリクエストも送ります(`fact_extraction_suggestions_enabled`、初期状態でオン)。
- プロバイダー: Groq、OpenAI、Anthropic、Mistral AI、Google Gemini、OpenRouter、NVIDIA NIM、Ollama(お使いの PC 上のサーバー、初期値は `http://localhost:11434`)、自分で追加した OpenAI 互換サーバー。
- 初期設定: 既定のプロバイダーは Groq で、API キーが必要です。キーがなければ LLM へのリクエストは行いません。キーがある場合、聞き取りの開始時に接続のウォームアップ用リクエスト(モデル一覧の取得、メッセージ内容なし)をプロバイダーに送ることがあります(`llm_prewarm_enabled`)。
- オフにする方法: API キーを入力しないか、お使いの PC で処理する Ollama を選んでください。

### 音声認識

- 既定のプロバイダー: Google(`stt_provider`)。Ari は SpeechRecognition ライブラリを通じて、録音した音声を Google の音声認識ウェブサービスに送ります。
- 時期: コマンドを聞き取っているときです。ウェイクワード検出がオンの間(`wake_word_enabled`、初期状態でオン)は、長さと音量の検査を通過した音声区間も認識するため、Google を使う場合はその音声も Google に送られます。
- オフにする方法: 認識エンジンとして Whisper を選んでください。Whisper はお使いの PC で動作します。ウェイクワード検出は音声設定でオフにできます。インストーラーの「プライバシーに関する選択」で「オンライン音声サービスを使用する」をオフにしても、認識エンジンが Whisper に切り替わります。
- Whisper のモデルは、初めて必要になったときに faster-whisper ライブラリが Hugging Face からダウンロードします(例: 音声設定の「モデルをダウンロード」ボタン)。

### 音声合成

- 初期設定: `tts_mode` は Fish Audio で、API キーが必要です。キーがない場合、Ari は Edge TTS を使います。Edge TTS は edge-tts ライブラリを通じて、読み上げるテキストを Microsoft のオンライン音声サービスに送ります。定型の短いメッセージは、バックグラウンドで事前に合成して PC にキャッシュします。
- キーがある場合: Fish Audio(`api.fish.audio`)、OpenAI、ElevenLabs、自分で設定した OpenAI 互換サーバーが読み上げるテキストを受け取ります。音声クローン機能は、選択した参照音声ファイルを ElevenLabs または設定したサーバーにアップロードします。
- オフにする方法: 音声エンジンとしてローカルの CosyVoice3 を選んでください。お使いの PC で動作します。インストール時には、GitHub から CosyVoice のソースコードを、Python パッケージを、Hugging Face からモデルをダウンロードします。インストーラーの「プライバシーに関する選択」で「オンライン音声サービスを使用する」をオフにすると、Edge TTS(バックグラウンドの事前合成を含む)を使わず、別のエンジンを選ぶまで応答は音声なしで吹き出しの文字だけになります。

### テキスト埋め込み(記憶とスキルの検索)

- 初期設定: ローカルモデルです。初めて必要になったとき(起動時のウォームアップがこれを行います)に Hugging Face から `Xenova/paraphrase-multilingual-MiniLM-L12-v2` のモデルファイルをダウンロードし、以後の埋め込みはお使いの PC で計算します。
- リモート埋め込み: `embedding_remote_enabled` をオンにして OpenAI の API キーを設定すると、テキストを OpenAI の埋め込み API に送ります。
- 初期設定: リモート埋め込みはオフ。

### Telegram

- 送るもの: Ari は Telegram Bot API(`api.telegram.org`)から新着メッセージを取得し、返信、編集したメッセージ、ツールが作成した画像を送ります。
- 初期設定: オフ(`telegram_enabled`)。ボットトークンと許可するチャット ID のリストの両方が必要で、どちらかがなければ動作しません。
- オフにする方法: `ari_settings.json` で `telegram_enabled` を `false` にしてください。ボットトークンは設定ウィンドウまたは環境変数で入力します。

### 依頼に応じて実行するツール

必要な依頼をしたときだけ実行されます。

- 天気: 都市名を指定しない場合、`ipapi.co` で IP アドレスからおおよその位置を調べます。Ari が知らない都市名は Open-Meteo のジオコーディング API で調べ、予報は座標を使って `api.open-meteo.com` に要求します。
- ウェブ検索: 検索語を `ddgs` ウェブ検索ライブラリを通じて送ります。どの検索エンジンがクエリを受け取るかは、この文書には記載していません。
- ウェブページ: ユーザーやモデルが選んだ公開ウェブページを取得し、ブラウザーを操作してサイトを訪問することがあります。ローカルアドレスやプライベートアドレスへのリクエストは拒否します。
- 画像生成: 初期状態でオフ(`image_generation_enabled`)。オンにすると、プロンプトをユーザーの API キーで OpenAI に送ります。
- Google カレンダーと Gmail: 初期状態でオフ(`google_calendar_enabled`)。Google アカウントを接続すると、ブラウザーで OAuth によりサインインし、依頼に応じて Google のカレンダーと Gmail の API を呼び出します。エージェント設定の接続解除でサインアウトできます。

### ユーザーが開始するダウンロード

- ローカル LLM のセットアップでは、`ollama.com` から Ollama のインストーラーをダウンロードします。モデルは Ollama が自分でダウンロードします。
- ローカル音声のセットアップでは、上で説明したとおり GitHub と Hugging Face からダウンロードします。
- GitHub からスキルをインストールすると、`codeload.github.com` からリポジトリを ZIP としてダウンロードします。

### ローカル専用

オプションの MCP サーバー(`mcp_server_enabled`、初期状態でオフ)は `127.0.0.1` でのみ接続を受け付けます。

## お問い合わせ

質問やプライバシーに関する懸念は[イシュートラッカー](https://github.com/DO0OG/Ari-VoiceCommand/issues)にお寄せください。セキュリティ上の脆弱性は、リポジトリの Security タブの非公開報告 "Report a vulnerability" を利用してください([リリースファイルの確認とウイルス対策ソフトの検出について](./SECURITY.md)を参照)。

</details>

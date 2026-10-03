# 🎙️ Ari — Windows 向けオープンソース AI 音声アシスタント

<div align="center">
  <img src="docs/assets/ari-idle.gif" width="180" alt="Ari デスクトップアシスタントのキャラクター" />
  <p><strong>声をかけると聞き取り、答え、PC の作業を代わりにこなすデスクトップアシスタント。</strong></p>
  <p>
    <a href="https://github.com/DO0OG/Ari-VoiceCommand/releases/latest"><img src="https://img.shields.io/github/v/release/DO0OG/Ari-VoiceCommand?display_name=tag&sort=semver" alt="最新リリース" /></a>
    <a href="https://github.com/DO0OG/Ari-VoiceCommand/stargazers"><img src="https://img.shields.io/github/stars/DO0OG/Ari-VoiceCommand?style=flat&logo=github" alt="GitHub Stars" /></a>
    <a href="https://app.codacy.com/gh/DO0OG/Ari-VoiceCommand/dashboard"><img src="https://img.shields.io/codacy/grade/b30dee6110a44335b36a1cdf47f0566f/main?logo=codacy&label=Codacy" alt="Codacy コード品質グレード" /></a>
    <img src="https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4?logo=windows&logoColor=white" alt="Windows 10 / 11" />
    <img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white" alt="Python 3.11" />
    <img src="https://img.shields.io/badge/Local%20LLM-Ollama-black" alt="Ollama ローカル LLM 対応" />
    <img src="https://img.shields.io/badge/Protocol-MCP-7C3AED" alt="Model Context Protocol 対応" />
    <img src="https://img.shields.io/badge/Languages-KO%20%7C%20EN%20%7C%20JA-orange" alt="韓国語、英語、日本語" />
    <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License" />
  </p>
  <p><a href="./README.md">English</a> · <a href="./README.ko.md">한국어</a> · <strong>日本語</strong></p>
  <p>
    <a href="https://github.com/DO0OG/Ari-VoiceCommand/releases/latest"><img src="https://img.shields.io/badge/ダウンロード-最新リリース-blue?style=for-the-badge" alt="最新の Ari をダウンロード" /></a>
    <a href="https://ari-voice-command.vercel.app"><img src="https://img.shields.io/badge/訪問-ホームページ-6c5ce7?style=for-the-badge" alt="Ari ホームページ" /></a>
    <a href="./docs/USAGE.md"><img src="https://img.shields.io/badge/読む-使い方ガイド-20a779?style=for-the-badge" alt="使い方ガイド" /></a>
  </p>
</div>

---

Ari は Windows で声をかけて使う**オープンソースの AI 音声アシスタント**です。ウェイクワードやショートカットで呼ぶか、デスクトップのキャラクターをクリックして話しかけると、聞き取って答え、PC 上の作業を代わりに行います。簡単なコマンドは PC 内ですぐに処理し、手順の多い作業は計画を立ててツールを使い、結果を確認しながら進めます。

> [!NOTE]
> Ari は **Windows 10/11 (64-bit)** 専用です。

## できること

| 分野 | 説明 |
| :--- | :--- |
| **音声会話** | ウェイクワード、ショートカット、キャラクターのクリックで話しかけます。返事は文ごとにすぐ読み上げ、途中で止めることもできます。 |
| **PC 操作** | 音量、スクリーンショット、アプリの起動といったコマンドから、複数の手順にわたるデスクトップ作業まで処理します。 |
| **すばやい応答** | よく使うコマンドは LLM を待たずに PC 内で判定して実行します。 |
| **モデルの選択** | Ollama のローカルモデル、ホスティングプロバイダー、OpenAI 互換サーバーから選べます。 |
| **音声エンジン** | 音声認識は Google とオフラインの Whisper、音声合成は Edge、ローカルの CosyVoice3、OpenAI、ElevenLabs、Fish Audio などに対応しています。 |
| **記憶** | 会話で知ったことを覚えておき、必要なときに使います。「覚えて」「忘れて」で自分でも管理できます。 |
| **拡張** | プラグイン、`SKILL.md` スキル、MCP サーバーで機能を追加できます。 |
| **リモートコマンド** | 許可した Telegram アカウントからコマンドを送れます。既定ではオフです。 |
| **キャラクター** | デスクトップのキャラクターが状態や気分を表し、状況に合わせて話しかけます。 |
| **言語** | 韓国語、英語、日本語 |

## こう話しかけてみてください

```text
「今何時？」
「音量を30%にして。」
「スクリーンショットを撮って。」
「実行中のアプリを教えて。」
「短い返事が好きだと覚えておいて。」
「さっき言った好みは忘れて。」
```

もっと複雑な依頼は、エージェントが計画を立てて順に処理します。実際にできることは、有効にした機能と選んだモデルによって変わります。

## インストール

### 動作環境

- Windows 10/11 (64-bit)
- RAM 8GB 推奨
- GPU でローカルモデルを動かす場合は VRAM 4GB 推奨
- ソースから実行する場合は Python 3.11

### インストーラー

**[GitHub Releases](https://github.com/DO0OG/Ari-VoiceCommand/releases/latest)** から `Ari-Setup-<version>.exe` をダウンロードして実行してください。既定のインストール先は `Program Files\Ari` で、設定と履歴は `%AppData%\Ari` に保存されます。

### ソースから実行

```bat
git clone https://github.com/DO0OG/Ari-VoiceCommand.git
cd Ari-VoiceCommand\VoiceCommand
setup.bat
Ari.vbs
```

ローカルの CosyVoice3 も入れる場合は `setup.bat --with-tts` を使ってください。起動しないときは `Ari.bat` で実行するとエラーを確認できます。

## プライバシーとローカル構成

LLM を Ollama、音声認識を Whisper、音声合成を CosyVoice3、記憶の検索をローカル埋め込みにすると、これらの処理は PC の中で完結します。どのデータが外部に送られるかは、有効にしたプロバイダーと機能によって変わります。

- リモート埋め込みと Telegram 連携は既定でオフです。
- プラグインは承認したものだけを読み込みます。承認したプラグインは隔離されずアプリの権限で動くため、信頼できるものだけを承認してください。

## ドキュメント

以下のドキュメントは韓国語で書かれています。

- **[利用ガイド](./docs/USAGE.md)** — 設定、プロバイダーと音声エンジン、スキル、自動化の例
- **[ドキュメント一覧](./docs/README.md)** — 全ドキュメントの索引、動作構造、ローカル判定の評価結果
- **[リリースノート](https://github.com/DO0OG/Ari-VoiceCommand/releases)** — バージョンごとの変更点
- 開発者向け: [プラグイン](./docs/PLUGIN_GUIDE.md) · [MCP サーバーとツール](./docs/MCP_SERVER.md) · [自律エージェント](./docs/AGENT_ADVANCED.md) · [ローカル判定エンジン](./docs/LOCAL_DECISION_ENGINE.md) · [テーマ](./docs/THEME_CUSTOMIZATION.md) · [認証情報](./docs/CREDENTIALS.md) · [コントリビューションガイド](./docs/CONTRIBUTING.md)

コントリビューションはいつでも歓迎します。

## アセットとクレジット

- デフォルトキャラクター画像 — **JAraTang**: <https://www.pixiv.net/users/78194943>
- `DNFBitBitv2` フォント — 公式配布元: <https://df.nexon.com/data/font/dnfbitbitv2>

プロジェクト外で再配布・再利用する場合は、フォントの利用条件も確認してください。

## ライセンス

Copyright © 2026 [DO0OG (MAD_DOGGO)](https://github.com/DO0OG).

Ari は **MIT License** で公開されています。

# Ari (アリ) — AI音声アシスタント

[한국어](./README.md) | [English](./README.en.md) | **日本語**

> Windows専用の多言語（韓国語・英語・日本語）対応AI音声アシスタント。
> Shimejiスタイルのキャラクターウィジェット + 複数のLLM/TTSプロバイダーをサポート。
> ユーザーのパターンを学習し、自ら進化する自己改善ループを搭載。

- キャラクターモデル制作 : [Jaratang](https://www.pixiv.net/users/78194943)

![preview](https://github.com/user-attachments/assets/fc8de4b7-57ca-4c22-812c-e5dcc7b45cdd)

---

## 主な機能

### 1. 対話と音声
- **ウェイクワード**: 「アリや」などの呼びかけを待機。エコーキャンセルと正規化により誤認識を抑制。
- **音声認識**: オンライン (Google STT) ・ オフライン (faster-whisper) 対応。
- **AIチャット**: Groq, OpenAI, Anthropic, Mistral, Gemini, OpenRouter, NVIDIA NIM, **Ollama (ローカルLLM)** をサポート。
- **多言語対応**: UI全体とプロンプトを韓国語、英語、日本語に最適化。
- **TTS (音声合成)**: Fish Audio, CosyVoice3 (ローカル), OpenAI, ElevenLabs, Edge TTS による高品質な音声。
- **感情表現**: AIが生成した感情タグ（例: `(喜び)`）に基づき、キャラクターがアニメーション。

### 2. 実行と自動化
- **自律実行エージェント**: Python/Shellコードを生成・実行し、エラー時は自動修正(Self-Fix)。
- **多段階プランニング**: Plan → Execute → Verify のループとDAGによる並列実行。
- **ブラウザ自動化**: ログイン解析、DOM状態の追跡、次のアクションの提案。
- **ビジョン検証**: OCRによる画面テキスト認識とLLMによる4段階の検証。

### 3. 学習と記憶
- **スキルライブラリ**: 成功した作業パターンを自動的に抽出し、再利用。
- **自己改善**: 検証済みのスキルをPythonコードにコンパイルし、LLMなしで即座に実行。
- **記憶システム**: 長期記憶 (FACT/BIO/PREF) と SQLite FTS5 による全文検索。
- **ユーザープロファイル**: 専門分野や回答の好みを学習し、パーソナライズされた対話を提供。

---

## クイックスタート

### 推奨環境
- **Python**: 3.11
- **OS**: Windows 10/11
- **RAM**: 4 GB (8 GB以上推奨)
- **GPU**: ローカルTTS/LLM使用時はCUDA対応GPU推奨。

### インストール
```bash
# 1. リポジトリをクローン
git clone https://github.com/DO0OG/Ari-VoiceCommand.git
cd Ari-VoiceCommand

# 2. 依存関係のインストール
pip install -r VoiceCommand/requirements.txt

# 3. 実行
cd VoiceCommand
py -3.11 Main.py
```

### 言語設定の変更
1. トレイアイコンを右クリックし、「設定」を選択します。
2. 「デバイス設定 (Device)」タブに移動します。
3. 「言語設定 (Language)」セクションで日本語を選択します。
4. 「保存」をクリックし、アプリを再起動してください。

---

## ドキュメント
- [プログラム使用ガイド](./docs/USAGE.md)
- [プラグインガイド](./docs/PLUGIN_GUIDE.md)
- [キャラクター画像ガイド](./docs/CHARACTER_IMAGES.md)

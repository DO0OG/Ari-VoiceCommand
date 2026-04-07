# 🎙️ Ari (アリ) — 次世代 AI 音声アシスタント

<div align="center">
  <img src="https://github.com/user-attachments/assets/fc8de4b7-57ca-4c22-812c-e5dcc7b45cdd" width="200" alt="Ari Logo" />
  <p align="center">
    <strong>Windows 専用 多言語対応音声 AI アシスタント</strong><br />
    ユーザーのパターンを学習し、自ら進化する自律実行エージェント。
  </p>

  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white" alt="Python Version" />
    <img src="https://img.shields.io/badge/Platform-Windows-0078D4?logo=windows&logoColor=white" alt="Platform" />
    <img src="https://img.shields.io/badge/License-MIT-green" alt="License" />
    <img src="https://img.shields.io/badge/i18n-KO%20%7C%20EN%20%7C%20JA-orange" alt="i18n" />
  </p>

  <p align="center">
    <a href="./README.md">한국어</a> | <a href="./README.en.md">English</a> | <strong>日本語</strong>
  </p>
</div>

---

## 🌟 核心理念

Ari は単なる音声認識プログラムを超え、ユーザーの作業スタイルを理解し、繰り返される業務を自ら自動化する**知能型自律エージェント**を目指しています。

- **自律性:** 目標を伝えるだけで Python/Shell コードを直接生成・実行し、エラーを自ら修正します。
- **パーソナライズ:** 対話を通じてユーザーの専門分野や好みを学習し、最適化された応答を提供します。
- **プライバシー:** Ollama と CosyVoice3 を使用することで、インターネット接続なしでローカル環境で LLM と TTS を稼働させることができます。

---

## 🚀 主な機能

### 1. 知能型インタラクション
- **多言語完全サポート:** UI、システムプロンプト、TTS 音声が韓国語・英語・日本語に最適化されています。
- **感情エンジン:** AI の応答に含まれる感情タグを分析し、キャラクターがリアルタイムでアニメーションします。
- **ハイブリッド音声エンジン:** オンライン (Google) とオフライン (faster-whisper) の STT を状況に合わせて選択可能です。

### 2. 自律実行と学習
- **エージェントワークフロー:** 複雑な目標に対して実行計画を策定し、DAG に基づいて並列実行します。
- **スキルライブラリ:** 成功した作業パターンを自動的に抽出し、Python コードにコンパイルしてパフォーマンスを最大化します。
- **ビジョン検証:** OCR と LLM を組み合わせて、実行結果を画面上で直接検証します。

### 3. 強力な拡張性
- **プラグインシステム:** メニュー、コマンド、LLM ツールを動的に追加できるプラグインフックを提供します。
- **マーケットプレイス:** 設定画面内で他のユーザーが作成したプラグインを検索し、即座にインストールできます。

---

## 🛠️ クイックスタート

### 要求仕様
- **OS:** Windows 10/11 (64-bit)
- **Python:** 3.11
- **Hardware:** RAM 8GB 以上推奨 (ローカルモデル稼働時は GPU VRAM 4GB 以上推奨)

### インストールと実行
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

---

## 🏗️ システムアーキテクチャ

```mermaid
graph TD
    A[ユーザーの発話] --> B{ウェイクワード}
    B -- "アリや" --> C[STT エンジン]
    C --> D[コマンドレジストリ]
    D -- "複合目標" --> E[自律エージェントループ]
    E --> F[プランナー / 実行機]
    F --> G[結果検証 / 学習]
    G --> H[Strategy Memory / スキル化]
    D -- "チャット / ツール" --> I[LLM Provider]
    I --> J[TTS 応答]
    H -.-> F
```

---

## 📚 ドキュメント

- 📖 **[ユーザーガイド](./docs/USAGE.md)**: 詳細設定と使い方
- 🔌 **[プラグイン制作](./docs/PLUGIN_GUIDE.md)**: 自分だけの機能を追加する
- 🎨 **[テーマカスタマイズ](./docs/THEME_CUSTOMIZATION.md)**: UI デザインの変更
- 👩‍💻 **[貢献する](./docs/CONTRIBUTING.md)**: プロジェクト参加ガイド

---

## ⚖️ License

Copyright © 2026 [DO0OG (MAD_DOGGO)](https://github.com/DO0OG).
This project is licensed under the **MIT License**.

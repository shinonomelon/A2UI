# Quiz Tutor (A2UI + A2A) サンプル

このサンプルは、LLM が生成した「選択式クイズ問題データ」を元に、A2UI(v0.8) のUIを返す A2A エージェントです。

## 概要

Quiz Tutor は A2UI の特徴を活かしたデモアプリケーションです：

- **動的 UI 生成**: クイズの内容に応じて UI コンポーネントを動的に生成
- **LLM 連携**: Gemini/GPT などの LLM でクイズ問題を自動生成
- **インタラクティブ体験**: 設定 → 問題 → フィードバック → 結果 の4フェーズで進行

## アーキテクチャ

```
┌─────────────────┐    A2A Protocol    ┌─────────────────┐
│   Lit Shell     │◄──────────────────►│  Quiz Agent     │
│  (Frontend)     │                    │   (Python)      │
│                 │                    │                 │
│ - quiz.ts       │    WebSocket/HTTP  │ - agent.py      │
│ - A2UI v0.8     │                    │ - quiz_gen.py   │
└─────────────────┘                    └────────┬────────┘
                                                │
                                                ▼
                                       ┌─────────────────┐
                                       │   LLM (Gemini)  │
                                       │  問題生成・JSON   │
                                       └─────────────────┘
```

## 前提

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- LLM へのアクセス（例: Gemini / OpenAI など）と API Key

## 起動

### 方法 1: デモスクリプト（推奨）

```bash
cd samples/client/lit

# Gemini を使う場合
export GEMINI_API_KEY="your_api_key_here"

npm run demo:quiz
```

Shell と Agent が同時に起動し、`http://localhost:5173/?app=quiz` で利用できます。

### 方法 2: 個別起動

```bash
# Terminal 1: Quiz Agent
cd samples/agent/adk/quiz_tutor
export GEMINI_API_KEY="your_api_key_here"
uv run .
# → http://localhost:10004

# Terminal 2: Lit Shell
cd samples/client/lit
npm run serve:shell
# → http://localhost:5173/?app=quiz
```

## クイズフロー

### Phase 1: Settings（設定画面）

```
┌────────────────────────────────┐
│ 🎯 クイズ設定                   │
├────────────────────────────────┤
│ トピック: [日本の歴史________] │
│ 難易度:   ───●───────── (3/5)  │
│ 問題数:   ─────●───── (5問)    │
│                                │
│         [クイズを始める]        │
└────────────────────────────────┘
```

**使用コンポーネント**: `Card`, `TextField`, `Slider`, `Button`

### Phase 2: Question（出題画面）

```
┌────────────────────────────────┐
│ 問題 1 / 5                     │
├────────────────────────────────┤
│ 鎌倉幕府を開いた人物は？        │
│                                │
│ ○ 源頼朝                       │
│ ○ 平清盛                       │
│ ○ 足利尊氏                     │
│ ○ 徳川家康                     │
│                                │
│           [回答する]           │
└────────────────────────────────┘
```

**使用コンポーネント**: `Card`, `Text`, `MultipleChoice`, `Button`

### Phase 3: Feedback（フィードバック画面）

```
┌────────────────────────────────┐
│ ✅ 正解！                      │
├────────────────────────────────┤
│ 源頼朝は1185年に鎌倉幕府を...   │
│                                │
│          [次の問題へ]          │
└────────────────────────────────┘
```

**使用コンポーネント**: `Card`, `Text`, `Button`

### Phase 4: Results（結果画面）

```
┌────────────────────────────────┐
│ 🎉 クイズ完了！                 │
├────────────────────────────────┤
│ スコア: 4 / 5 (80%)            │
│                                │
│ 問題1: ✅ 源頼朝 (正解)         │
│ 問題2: ❌ 平清盛 (正解: 北条時宗)│
│ ...                            │
│                                │
│        [もう一度挑戦]          │
└────────────────────────────────┘
```

**使用コンポーネント**: `Card`, `Text`, `List`, `Button`

## UIイベント（userAction.name）

| イベント名 | トリガー | 説明 |
|-----------|---------|------|
| `start_quiz` | 設定画面の「開始」 | クイズ生成を開始 |
| `submit_answer` | 回答の「送信」 | 選択した回答を送信 |
| `next_question` | フィードバックの「次へ」 | 次の問題を表示 |
| `restart_quiz` | 結果画面の「再挑戦」 | 設定画面に戻る |

## 使用 A2UI コンポーネント (v0.8)

| コンポーネント | 用途 |
|--------------|------|
| `Card` | 各画面のコンテナ |
| `Text` | 問題文、説明、結果表示 |
| `TextField` | トピック入力 |
| `Slider` | 難易度・問題数の選択 |
| `MultipleChoice` | 選択肢の表示と選択 |
| `Button` | アクション実行 |
| `List` | 結果一覧の表示 |

## ファイル構成

```
quiz_tutor/
├── __main__.py          # エントリーポイント
├── agent.py             # ADK Agent (ツール定義)
├── agent_executor.py    # A2A エージェント実行
├── quiz_generator.py    # LLM クイズ生成ロジック
├── pyproject.toml       # 依存関係
└── README.md            # このファイル
```

## カスタマイズ

### LLM モデルの変更

`quiz_generator.py` の `model` パラメータを変更:

```python
# Gemini (デフォルト)
model = "gemini/gemini-2.5-flash"

# OpenAI
model = "gpt-4o-mini"
```

### 問題数の上限変更

`agent.py` の `Slider` 定義を変更:

```python
Slider(name="quiz_count", min=1, max=20, ...)  # maxを変更
```

## トラブルシューティング

### LLM API エラー

```
Error: API key not found
```

→ 環境変数 `GEMINI_API_KEY` または `OPENAI_API_KEY` を設定してください。

### ポートが使用中

```
ERROR: Address already in use
```

→ 既存のプロセスを終了するか、別のポートを指定してください。

## 関連ドキュメント

- [A2UI Protocol Specification](../../../../packages/types/A2UI_SPEC.md)
- [A2A SDK Documentation](../../../../a2a_agents/python/a2a_sdk/README.md)
- [Lit Renderer Components](../../../../renderers/lit/README.md)
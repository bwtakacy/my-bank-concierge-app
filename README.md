# 銀行窓口コンシェルジュ AI エージェント デモ

`docs/ARCHITECTURE.md` の設計ドキュメントに基づく、階層型マルチエージェント
構成（フロントエージェント＋商品/マニュアル別専門エージェント＋検証エージェント
＋人間エスカレーション）を可視化するデモアプリです。

**これは実運用システムではありません。** 実際の勘定系・商品マスタとの接続、
本人確認・認証、実際の契約手続きは一切行いません。金利・手数料等の数値は
すべてモックデータ（`knowledge/product_master.json`）です。

## デモで見せているもの

- フロント / 専門 / 検証の3種のエージェントが、実際に Agent-as-Tool
  （Claudeの tool use）で連携する様子
- 高リスク意図（相続・解約・苦情）に対する**決定的ルーティング**（正規表現、
  LLM不使用）と、通常照会に対する**LLM動的ルーティング**の使い分け
- 専門エージェントが返した数値（金利・手数料）を、検証エージェントが
  `product_master.json` と機械的に照合し、不一致を検出・訂正する様子
- 投資信託・NISA領域での適合性原則ガードレール（断定的な推奨をせず、
  人間の窓口担当者へエスカレーションする）
- 会話の裏側で何が起きているかを見せる「エージェントトレース」パネル
  （Streamlit UIのサイドバー）

## セットアップ

### 1. 依存関係のインストール

このプロジェクトは [uv](https://docs.astral.sh/uv/) で依存関係・仮想環境を管理しています。
[uvのインストール手順](https://docs.astral.sh/uv/getting-started/installation/)に従って
uvを導入した後、以下を実行してください。

```bash
uv sync
```

`.venv` が作成され、依存関係（`pyproject.toml` / `uv.lock`）がインストールされます。
以降のコマンドは `uv run <コマンド>` で実行するか、`source .venv/bin/activate` で
仮想環境を有効化してから実行してください。

### 2. 環境変数の設定

```bash
cp .env.example .env
```

`.env` を開き、`ANTHROPIC_API_KEY` に有効なAPIキーを設定してください。
モデルIDはデフォルト値（`.env.example` 参照）のままで動作しますが、
必要に応じて変更できます。

```
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
ANTHROPIC_MODEL_FRONT=claude-sonnet-5
ANTHROPIC_MODEL_SPECIALIST=claude-sonnet-5
```

### 3. アプリの起動

```bash
uv run streamlit run app.py
```

ブラウザで `http://localhost:8501` が開き、チャットUIとエージェント
トレースパネルが表示されます。

## 試してみる質問例

| 質問例 | 想定される経路 |
|---|---|
| 普通預金の口座開設に必要な書類を教えて | `consult_basic_banking` 呼び出し、通常回答 |
| 住宅ローンの変動金利は？ | `consult_housing_loan` 呼び出し、検証OK（0.475%と一致） |
| NISAと保険、どっちがいいですか？ | `consult_nisa_toshin` 呼び出し、適合性原則により推奨せずエスカレーション |
| 祖父から相続した口座を解約したい | 決定的ルーターが即座にヒットし、専門エージェントを呼ばず直接エスカレーション |
| 苦情があります、納得できません | 決定的ルーターが即座にヒットし、直接エスカレーション |

いずれの質問でも、右側（サイドバー）のエージェントトレースパネルで、
どのエージェントが何を判断したかを確認できます。

## テストの実行

```bash
uv run pytest
```

## Lintの実行

```bash
uv run ruff check .
```

ルーティング・検証ロジックのユニットテストに加え、`tests/test_scenarios.py`
に設計ドキュメント7章の受け入れテストシナリオ5件を実装しています。うち
実際にAnthropic APIを呼び出すシナリオ（通常照会・数値照会・適合性原則の3件）
は `ANTHROPIC_API_KEY` が未設定の環境では自動的にスキップされます。
決定的ルーティングと検証ロジック単体のシナリオ（相続エスカレーション、
数値不一致の検出・訂正）はAPIキーなしでも常に実行されます。

## ディレクトリ構成

```
bank-concierge-demo/
├── app.py                        # Streamlitエントリポイント（チャットUI＋トレースパネル）
├── agents/
│   ├── front_agent.py            # フロントエージェント（Agent-as-Tool、動的ルーティング）
│   ├── specialist_agent.py       # 専門エージェント共通実装（Scout-then-act）
│   ├── verify_agent.py           # 検証エージェント（ルールベースの数値照合）
│   └── deterministic_router.py   # 高リスク意図の決定的ルーティング
├── knowledge/
│   ├── products/*.md             # 商品マニュアル（Markdown、キーワード検索対象）
│   └── product_master.json       # 金利・手数料等の構造化マスタ（モック、数値の「正」）
├── tools/
│   ├── manual_search.py          # マニュアル検索（キーワード一致）
│   └── master_lookup.py          # 商品マスタ参照
├── core/
│   ├── schemas.py                # dataclass定義
│   ├── audit_log.py              # 監査ログ（エージェントトレースの記録元）
│   └── escalation.py             # 人間エスカレーションのスタブ
├── tests/                        # pytest（ルーター・検証エージェント・受け入れシナリオ）
└── docs/
    └── ARCHITECTURE.md           # 設計ドキュメント（本実装の元仕様）
```

詳細な設計方針は `docs/ARCHITECTURE.md` を参照してください。

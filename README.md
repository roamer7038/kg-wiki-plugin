# kg-wiki

Markdown で書かれた知識ページ群を真のソースとし、そこから検索可能な構造（index・ナレッジグラフ・コミュニティ要約）を決定論的に生成する Claude Code プラグイン。CLI・Skill・サブエージェント・hook で構成される。

セッションをまたいで蓄積された知識に、Claude が必要な分だけアクセスするための仕組みである。

## 概要

kg-wiki の設計は次の 3 点に集約される。

### 1. グラフ構造による知識蓄積

知識は独立したメモの集合ではなく、ページを節点・関係を辺とするグラフとして蓄積される。各ページは frontmatter に型付き関係（`is_a` / `part_of` / `uses` / `contradicts` / `supersedes` など）を持ち、`kg build` がこれを走査して KG トリプル・隣接リスト・コミュニティを生成する。

この構造により、単発の検索では答えられない問いを扱える。

- **関係**: 2 つの概念はどう繋がるか（`kg path`）
- **近傍**: ある概念の周辺には何があるか（`kg traverse`）
- **俯瞰**: この分野の全体像は何か（`kg community`）
- **矛盾・陳腐化**: `contradicts` / `supersedes` により、知識どうしの衝突を明示的に表現する

規模が増えてもグラフは劣化しない。`kg validate` がリンク切れ・スキーマ違反・派生物の陳腐化を検出し、`kg move` はページの移動時に被参照をすべて書き換える。

### 2. ヒューマンリーダブルと AI リーダブルの両立

真のソースは `pages/**.md` に置かれた Markdown ページのみである。人間が読み書きでき、git で差分が読め、エディタで直接編集できる。

機械可読な形式は、この Markdown から派生生成される。

```
pages/**.md  ──  kg build  ──▶  _derived/
                                ├── index.jsonl / index.md
                                ├── graph.tsv       (KG トリプル)
                                ├── adjacency.json
                                └── communities/
```

`_derived/` は生成物であり、いつ削除しても `kg build --full` で復元できる。知識がバイナリ index の中に閉じ込められることはなく、可読性・可搬性は最後まで Markdown 側に残る。

Claude 側は、この派生物を通して知識にアクセスする。UserPromptSubmit hook が関連ページの ref のみを軽量に注入し、本文が必要になった時点で Skill が CLI 経由で引く。ページ全文をコンテキストに常駐させない。

### 3. LLM の確率的挙動を減らす工夫

構造の管理はすべて決定論的なスクリプトが担う。LLM が担うのはページ内容の執筆と、検索プリミティブの選択だけである。

| 層 | 担い手 | 性質 |
|---|---|---|
| 構造（build / validate / move / 派生物生成） | CLI（Python） | 決定論的・冪等・増分 |
| 検索プリミティブ（search / traverse / path / community / pack） | CLI（Python） | 決定論的 |
| 戦略（どのプリミティブをどう組み合わせるか） | Claude（Skill） | 確率的 |
| 内容（ページ本文の執筆） | 人間 または Claude | 確率的 |

同じ入力からは常にバイト単位で同じ派生物が得られ、増分ビルドと全再生成の結果は一致する。ベクトル検索は自前実装せず外部ツール [qmd](https://www.npmjs.com/package/@tobilu/qmd) に委譲することで、非決定的な要素を境界の外へ隔離している。

結果として、Claude の出力が揺れても知識ベースの構造は壊れない。壊れた場合は `kg validate` が機械的に検出する。

## インストール

```bash
claude --plugin-dir /path/to/kg-wiki-plugin
```

CLI の実体は `${CLAUDE_PLUGIN_ROOT}/bin/kg`。hook と Skill からは絶対パスで参照される。CLI は Python 3.10+ の標準ライブラリのみで動作し、追加依存はない。

## クイックスタート

```bash
kg init --layer global --topic llm     # グローバル層を topic llm で初期化
kg new llm/concepts/rag --title RAG    # frontmatter 準備済みページを生成
$EDITOR ~/.kg-wiki/topics/llm/pages/concepts/rag.md
kg build                               # 派生物を生成
kg search "GraphRAG"                   # 語彙検索
```

Claude 上では Skill 経由で同じ操作ができる（「wiki を初期化して」「この記事を wiki に入れて」など）。

## 概念

**ref** — ページの一意な識別子。`<topic>/<type>/<slug>` の形をとる（例: `llm/concepts/graphrag`）。ファイルは `topics/<topic>/pages/<type>/<slug>.md` に置かれ、slug とファイル名は一致する。

**層** — 知識の置き場所は 2 層ある。

| 層 | 場所 | 範囲 |
|---|---|---|
| グローバル層 | `~/.kg-wiki`（`KG_WIKI_ROOT` で変更可） | 全プロジェクト共通 |
| プロジェクト層 | `<project>/.kg-wiki` | そのプロジェクトのみ |

同じ ref が両層に存在する場合、プロジェクト層が優先される。

## ページ形式

```markdown
---
title: GraphRAG
type: concepts
slug: graphrag
summary: コミュニティ検出+要約で俯瞰質問に答える RAG 拡張
keywords: [GraphRAG, グラフRAG]
relations:
  - rel: is_a
    to: llm/concepts/rag
  - rel: uses
    to: llm/concepts/knowledge-graph
sources:
  - url: https://example.com/graphrag
    title: GraphRAG 解説
    accessed: 2026-07-02
updated: 2026-07-02
---

[[llm/concepts/rag]] をコミュニティ検出と要約で拡張する手法。
```

| キー | 必須 | 内容 |
|---|---|---|
| `title` | ○ | ページ表題 |
| `type` | ○ | config の `types` にある値。ディレクトリ名と一致させる |
| `slug` | ○ | ファイル名（拡張子を除く）と一致させる |
| `summary` | | 省略時は本文の最初の段落から 120 字で自動生成 |
| `keywords` | | 文字列リスト。検索スコアに反映される |
| `relations` | | `rel`（config の `relations` にある値）と `to`（正準形 ref）の組 |
| `sources` | | `url` は必須。`title` / `accessed`（YYYY-MM-DD）は任意 |
| `updated` | ○ | ISO 日付 |

本文中の `[[<topic>/<type>/<slug>]]` は `mentions` エッジとして KG に取り込まれる。`mentions` は本文リンク専用の予約語であり、frontmatter には書けない。

**既定の type**: `concepts` / `entities` / `articles` / `papers` / `queries` / `decisions`

**既定の relation**: `is_a` / `part_of` / `uses` / `relates_to` / `contradicts` / `supersedes` / `derived_from` / `evaluated_by`

いずれも各層の `config.yml` で変更できる。

## ディレクトリ構成

```
~/.kg-wiki/                          # グローバル層（<project>/.kg-wiki も同一構造）
├── config.yml                       # topics / types / relations / qmd 設定
├── log.md                           # 構造操作の追記ログ（手で編集しない）
└── topics/<topic>/
    ├── pages/<type>/<slug>.md       # 真のソース
    └── _derived/                    # kg build の生成物（手で編集しない）
        ├── index.jsonl / index.md
        ├── graph.tsv
        ├── adjacency.json
        └── communities/
```

## コマンド

### 作成・更新

| コマンド | 用途 |
|---|---|
| `kg init --layer <global\|project> --topic <name>` | 層の初期化（冪等）。`--with-qmd` で qmd 連携も設定 |
| `kg new <ref> --title <title>` | テンプレートからページを生成 |
| `kg build` | 派生物の再生成（増分・冪等）。`--full` で全再生成 |
| `kg move <from-ref> <to-ref>` | ページの移動・改名。被参照をすべて書き換える |
| `kg log ingest <ref> --source <url\|path>` | 取り込み操作を `log.md` に記録 |

### 検索・走査

| コマンド | 用途 |
|---|---|
| `kg search <query>` | 語彙検索 |
| `kg traverse <ref> --hops 2` | n-hop 近傍の取得 |
| `kg path <from-ref> <to-ref>` | 2 ページ間の関係経路列挙 |
| `kg community <ref>` | 所属コミュニティと俯瞰要約の取得 |
| `kg pack <query>\|<ref...>` | 関連ページ本文を束ねたコンテキストパックの生成 |
| `kg vsearch <query>` / `kg hybrid <query>` | ベクトル / ハイブリッド検索（qmd 連携が必要） |

### 保守

| コマンド | 用途 |
|---|---|
| `kg validate` | 構造・鮮度の検査（リンク切れ、stale な派生物、スキーマ違反） |
| `kg skillgen topic:<topic>` | topic やコミュニティから Skill を生成 |
| `kg hook-context` | UserPromptSubmit hook 用の軽量注入（hook から呼ばれる） |

共通オプション: `--layer`（`global` / `project` / `all`）と `--root` は全コマンド共通。`--json` は `pack` / `skillgen` を除く各コマンドに、`--limit` は検索・走査系（`search` / `traverse` / `vsearch` / `hybrid` / `community`）にのみある。

`kg move` と `kg skillgen --install` は `--dry-run` で差分を確認できる。

**終了コード**: `0` 正常 / `1` エラー / `2` 検証失敗 / `3` 使い方の誤り / `4` 機能無効（qmd 未設定など）

## Claude Code 統合

### Skill

Claude が依頼内容に応じて自動選択する。

| Skill | 発火する依頼の例 |
|---|---|
| `kg-init` | 「wiki を初期化して」 |
| `kg-new` | 「wiki にページを作って」 |
| `kg-ingest` | 「この記事を wiki に入れて」 |
| `kg-query` | 「wiki を調べて」「知識ベースから答えて」 |
| `kg-build` | 「wiki をビルドして」 |
| `kg-lint` | 「wiki を検査して」「リンク切れを確認して」 |
| `kg-move` | 「ページを移動して」「slug を変えたい」 |
| `kg-pack` | 「関連ページをまとめて」 |
| `kg-skillgen` | 「この topic から Skill を作って」 |
| `kg-routing` | 検索プリミティブの使い分け指針。他 Skill が参照する手順書であり、単体では発火しない |

### サブエージェント

いずれも本体のコンテキストを消費しないよう、調査・下処理を隔離して実行し、結果のみを返す。

| エージェント | 役割 |
|---|---|
| `kg-researcher` | 多ホップ・複数 topic 横断の調査。出典 ref 付きの結論を返す |
| `kg-curator` | 大規模な取り込みの下処理。ページ草稿と関係候補を作る（配置は承認後） |
| `kg-auditor` | 矛盾・陳腐化・欠落概念の検出。`contradicts` / `supersedes` の付与を提案する |

### hook

`hooks/hooks.json` を同梱している。

| イベント | 実行内容 |
|---|---|
| UserPromptSubmit | `kg hook-context` — プロンプトに関連するページの ref を注入する。本文は注入しない。0.5 秒で自己打ち切りし、常に正常終了する |
| SessionStart | `kg validate --quick` — 派生物の鮮度を 1 行で報告する |

## 設定

設定は環境変数と各層の `config.yml` で行う。

| 環境変数 | 既定 | 用途 |
|---|---|---|
| `KG_WIKI_ROOT` | `~/.kg-wiki` | グローバル層のルート（コマンド単位では `--root` が優先） |
| `KG_WIKI_HOOK_CONTEXT` | 未設定（＝有効） | `false` で UserPromptSubmit の注入を無効化 |
| `KG_WIKI_ENABLE_QMD` | 未設定 | qmd 連携の上書き。通常は `kg init --with-qmd` で `config.yml` に設定する |

グローバル層を既定以外の場所に置く場合は、シェルの設定ファイル（`.zshrc` 等）に `KG_WIKI_ROOT` を記述する。hook もこの環境変数を読む。未設定のまま既定以外の場所を使った場合、hook は何もせず正常終了するが、注入は機能しない。

`plugin.json` の `userConfig` は使用しない。`userConfig` の値は hook プロセスにしか渡らず、Skill やサブエージェントが `kg` を実行する Bash ツールの環境には届かないためである。

### permissions

サブエージェントの Bash は規約上 `kg` の実行に限定しているが、機構としても最小権限にする場合は `settings.json` の permissions を併用する。

```json
{
  "permissions": {
    "allow": [
      "Bash(kg *)",
      "Bash(*/bin/kg *)"
    ]
  }
}
```

### qmd 連携（任意）

`kg vsearch` / `kg hybrid` はベクトル検索を [qmd](https://www.npmjs.com/package/@tobilu/qmd) に委譲する。未設定でも他のコマンドには影響せず、この 2 つのみが終了コード 4 で有効化手順を案内する。

```bash
npm install -g @tobilu/qmd    # Node.js 22+
kg init --with-qmd            # コレクション登録・埋め込み生成まで実行
```

qmd 2.5.3 で動作確認済み。CPU 環境では 1 クエリあたり 10〜45 秒を要する（クエリ拡張とリランカーの LLM 推論を含むため）。曖昧・意味的なクエリに対する recall@10 は、`kg search` 0.85 に対し `kg vsearch` 0.95 / `kg hybrid` 0.90。

## 開発

```bash
python3 -m unittest discover tests                                # 全テスト
(cd tests && KG_PERF=1 python3 -m unittest test_perf)             # 性能スモーク
(cd tests && KG_UPDATE_GOLDEN=1 python3 -m unittest test_golden)  # golden 再生成
claude plugin validate --strict .                                 # プラグイン検証
```

出力書式を変更する場合は、同じコミットで golden の更新を伴わせること。

## ライセンス

MIT License. 詳細は [LICENSE](LICENSE) を参照。

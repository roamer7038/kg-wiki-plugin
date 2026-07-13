# kg-wiki

Markdown の知識リポジトリと、そこから決定論的に生成されるナレッジグラフ（KG）で
Claude Code の知識を管理するプラグイン。

真のソースは人間が読み書きする Markdown ページで、index・KG トリプル・隣接リストは
すべて `kg build` の派生物です。検索・走査・検証・移動は単一の CLI `kg` に閉じており、
Claude は Skill とサブエージェント経由でこの CLI を使います。

- **2 層構造** — グローバル層（`~/.kg-wiki`、全プロジェクト共通）とプロジェクト層
  （`<project>/.kg-wiki`）。同じ ref があればプロジェクト層が優先されます。
- **決定論** — 同じ入力からは常にバイト単位で同じ派生物が生成されます。増分ビルドと
  全再生成の結果は一致します。
- **追加依存なし** — CLI は Python 3.10+ の標準ライブラリのみで動きます。

## インストール

```bash
claude --plugin-dir /path/to/kg-wiki-plugin
```

CLI の実体は `${CLAUDE_PLUGIN_ROOT}/bin/kg` です。hook・Skill からは絶対パスで参照します。

## クイックスタート

```bash
kg init --layer global --topic llm     # グローバル層を topic llm で初期化
kg new llm/concepts/rag --title RAG    # frontmatter 準備済みページを生成
$EDITOR ~/.kg-wiki/topics/llm/pages/concepts/rag.md
kg build                               # index・KG・隣接リストを生成
kg search "GraphRAG"                   # 語彙検索
```

Claude 上では Skill 経由でも同じ操作ができます（`/kg-wiki:kg-init` など）。

## ページの書き方

ページは `<topic>/<type>/<slug>` で一意に参照されます（これを **ref** と呼びます）。
ファイルは `topics/<topic>/pages/<type>/<slug>.md` に置き、slug とファイル名は一致させます。

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
| `summary` | | 省略時は本文の最初の段落から 120 字で自動生成される |
| `keywords` | | 文字列リスト。検索スコアに効く |
| `relations` | | `rel`（config の `relations` にある値）と `to`（正準形 ref）の組 |
| `sources` | | `url` は必須。`title` / `accessed`（YYYY-MM-DD）は任意 |
| `updated` | ○ | ISO 日付 |

本文中の `[[<topic>/<type>/<slug>]]` は `mentions` エッジとして KG に取り込まれます
（`mentions` は本文リンク専用の予約語で、frontmatter には書けません）。

**既定の type**: `concepts` / `entities` / `articles` / `papers` / `queries` / `decisions`
**既定の relation**: `is_a` / `part_of` / `uses` / `relates_to` / `contradicts` / `supersedes` / `derived_from` / `evaluated_by`

いずれも各層の `config.yml` で変更できます。

## ディレクトリ構成

```
~/.kg-wiki/                          # グローバル層（<project>/.kg-wiki も同じ構造）
├── config.yml                       # topics / types / relations / qmd 設定
├── log.md                           # 構造操作の追記ログ（手で編集しない）
└── topics/<topic>/
    ├── pages/<type>/<slug>.md       # 真のソース
    └── _derived/                    # kg build の生成物（手で編集しない）
        ├── index.jsonl / index.md
        ├── graph.tsv                # KG トリプル
        ├── adjacency.json
        └── communities/
```

## コマンド

**作成・更新**

| コマンド | 用途 |
|---|---|
| `kg init --layer <global\|project> --topic <name>` | 層の初期化。`--with-qmd` で qmd 連携も設定 |
| `kg new <ref> --title <title>` | テンプレートからページを生成 |
| `kg build` | 派生物の再生成（増分・冪等）。`--full` で全再生成 |
| `kg move <from-ref> <to-ref>` | ページの移動・改名。被参照もすべて書き換える |
| `kg log ingest <ref> --source <url\|path>` | 取り込み操作を log.md に記録 |

**検索・走査**

| コマンド | 用途 |
|---|---|
| `kg search <query>` | 語彙検索 |
| `kg traverse <ref> --hops 2` | 隣接ノードの走査 |
| `kg path <from-ref> <to-ref>` | 2 ページ間の最短経路 |
| `kg community <ref>` | 所属コミュニティと俯瞰要約 |
| `kg pack <query>\|<ref...>` | 関連ページ本文を束ねたコンテキストパック |
| `kg vsearch <query>` / `kg hybrid <query>` | ベクトル / ハイブリッド検索（要 qmd） |

**保守**

| コマンド | 用途 |
|---|---|
| `kg validate` | 構造検査（リンク切れ・stale な派生物・スキーマ違反など） |
| `kg skillgen topic:<topic>` | topic やコミュニティから Skill を生成 |
| `kg hook-context` | UserPromptSubmit hook 用の軽量注入（hook から呼ばれる） |

共通オプション: `--layer`（global / project / all）、`--root`、`--json`、`--limit`。

`kg move` と `kg skillgen --install` は `--dry-run` で差分を確認してから適用します。

**終了コード**: `0` 正常 / `1` エラー / `2` 検証失敗 / `3` 使い方の誤り /
`4` 機能無効（qmd 未設定など）。

## Skill

Claude が自動で選択します。ユーザは通常のことばで依頼するだけです。

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
| `kg-routing` | 検索プリミティブの使い分け指針（他 Skill が参照する手順書。単体では発火しない） |

## サブエージェント

いずれも本体のコンテキストを汚さないために調査・下処理を隔離して行い、結果のみを返します。

| エージェント | 役割 |
|---|---|
| `kg-researcher` | 多ホップ・複数 topic 横断の調査。出典 ref 付きの結論だけを返す |
| `kg-curator` | 大規模な取り込みの下処理。ページ草稿と関係候補を作る（配置は承認後） |
| `kg-auditor` | 矛盾・陳腐化・欠落概念の検出。`contradicts` / `supersedes` の付与を提案する |

## hook

`hooks/hooks.json` を同梱しています。

- **UserPromptSubmit** → `kg hook-context`: プロンプトに関連するページの ref を軽量に注入します
  （本文は注入しません。0.5 秒で自己打ち切りし、常に正常終了します）。
- **SessionStart** → `kg validate --quick`: 派生物の鮮度を 1 行で報告します。

## 設定

設定は**環境変数**と**各層の `config.yml`** で行います。

| 環境変数 | 既定 | 用途 |
|---|---|---|
| `KG_WIKI_ROOT` | `~/.kg-wiki` | グローバル層のルート（コマンド単位の指定は `--root` が優先） |
| `KG_WIKI_HOOK_CONTEXT` | 未設定（＝有効） | `false` で UserPromptSubmit の注入を無効化 |
| `KG_WIKI_ENABLE_QMD` | 未設定 | qmd 連携の上書き。通常は `kg init --with-qmd` で `config.yml` に設定する |

グローバル層を既定以外の場所に置く場合は、シェルの設定（`.zshrc` 等）に `KG_WIKI_ROOT`
を書いてください。hook もこの環境変数を読みます。未設定のまま既定以外の場所を使うと、
hook は安全に何もせず終了しますが、注入は機能しません。

なお `plugin.json` の `userConfig` は使いません。`userConfig` の値は hook プロセスにしか
渡らず、Skill やエージェントが `kg` を実行する Bash ツールの環境には届かないためです
（設定しても効かない、という失敗を避けています）。

### 推奨 permissions

サブエージェントの Bash は規約で `kg` の実行に限定していますが、機構としても最小権限に
するには `settings.json` の permissions を併用します。

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

`kg vsearch` / `kg hybrid` は [qmd](https://www.npmjs.com/package/@tobilu/qmd) に委譲します。
未設定でも他のコマンドには一切影響せず、この 2 つだけが終了コード 4 で有効化手順を案内します。

```bash
npm install -g @tobilu/qmd    # Node.js 22+
kg init --with-qmd            # コレクション登録・埋め込み生成まで行う
```

qmd 2.5.3 で動作確認しています。CPU 環境では 1 クエリあたり 10〜45 秒かかります
（クエリ拡張とリランカーの LLM 推論を含むため）。曖昧・意味的なクエリでの recall@10 は
`kg search` の 0.85 に対し `kg vsearch` 0.95 / `kg hybrid` 0.90 でした。

## 開発

```bash
python3 -m unittest discover tests                                # 全テスト
(cd tests && KG_PERF=1 python3 -m unittest test_perf)             # 性能スモーク
(cd tests && KG_UPDATE_GOLDEN=1 python3 -m unittest test_golden)  # golden 再生成
claude plugin validate --strict .                                 # プラグイン検証
```

出力書式を変える変更は、同じコミットで golden の更新を伴わせてください。

## ライセンス

MIT License. 詳細は [LICENSE](LICENSE) を参照してください。

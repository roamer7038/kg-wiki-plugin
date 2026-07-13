# kg-wiki

Markdown 知識リポジトリ + 派生ナレッジグラフによる Claude Code 知識管理プラグイン。
設計文書は [kg-wiki-specs](../kg-wiki-specs) を参照（本リポジトリは Phase 1 実装）。

## 構成

- 真のソースは frontmatter 付き Markdown ページ（`<topic>/<type>/<slug>`）
- `kg build` が index / KG トリプル / 隣接リストを決定論的に生成（増分・冪等）
- 検索・走査・検証・移動はすべて単一 CLI `bin/kg` のサブコマンド
- 知識はグローバル層（`~/kg-wiki`）とプロジェクト層（`<project>/.kg-wiki`）の 2 層

## インストール（開発中）

```bash
claude --plugin-dir /path/to/kg-wiki-plugin
```

初期化と基本操作:

```bash
/kg-wiki:kg-init            # 層の初期化（スキル経由）
kg init --layer global --topic llm   # CLI 直接（Bash から）
kg new llm/concepts/rag --title RAG
kg build
kg search "GraphRAG"
kg traverse llm/concepts/rag --hops 2
kg path llm/concepts/a llm/concepts/b
kg validate
kg move llm/concepts/rag llm/concepts/vanilla-rag --dry-run
```

CLI の実体は `${CLAUDE_PLUGIN_ROOT}/bin/kg`（Python 3.10+ 標準ライブラリのみ、
追加インストール不要）。hook・スキルからは絶対パス参照を使う。

## 推奨 permissions 設定

サブエージェント（kg-researcher / kg-curator / kg-auditor）の Bash は規約で
`kg` の実行に限定しているが、機構的な最小権限化には settings.json の
permissions を併用する（方式設計 02 §6.5）:

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

## ユーザ設定（plugin.json userConfig）

| キー | 既定 | 用途 |
|---|---|---|
| `wiki_root` | `~/kg-wiki` | グローバル層ルート（環境変数 `KG_WIKI_ROOT` でも指定可） |
| `enable_hook_context` | true | UserPromptSubmit 軽量注入（Phase 3 で有効化） |
| `enable_qmd` | false | qmd 委譲のベクトル検索（Phase 2 で有効化） |

## テスト

```bash
python3 -m unittest discover tests            # 全テスト
KG_PERF=1 python3 -m unittest tests.test_perf # 性能スモーク（NFR-5）
KG_UPDATE_GOLDEN=1 python3 -m unittest tests.test_golden  # golden 再生成
claude plugin validate --strict .             # プラグイン検証
```

## Phase 対応状況

Phase 1（コア）を実装済み: init / build / search / traverse / path / validate /
move / new / log + スキル 7 種 + サブエージェント 3 種。
`vsearch` / `hybrid` / `community`（Phase 2）、`pack` / `skillgen` /
`hook-context`（Phase 3）は exit 4（機能無効）を返す。hooks.json は Phase 3 で
同梱する（未実装コマンドのノイズ回避。方式設計 02 §6.6）。

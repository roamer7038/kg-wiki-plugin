# kg-wiki

Markdown 知識リポジトリ + 派生ナレッジグラフによる Claude Code 知識管理プラグイン。
設計文書は [kg-wiki-specs](../kg-wiki-specs) を参照（本リポジトリは Phase 1・2 実装）。

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
kg community llm/concepts/rag        # 所属コミュニティと俯瞰要約
kg vsearch "曖昧な意味のクエリ"      # 要 qmd（無効・不在時は exit 4）
kg hybrid "曖昧な意味のクエリ"       # 要 qmd
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
| `enable_hook_context` | true | UserPromptSubmit 軽量注入（Phase 3 で実装予定） |
| `enable_qmd` | false | qmd 委譲のベクトル/ハイブリッド検索（`kg init --with-qmd` が設定する。環境変数 `CLAUDE_PLUGIN_OPTION_ENABLE_QMD` が優先） |

## テスト

```bash
python3 -m unittest discover tests            # 全テスト
(cd tests && KG_PERF=1 python3 -m unittest test_perf)  # 性能スモーク（NFR-5）
(cd tests && KG_UPDATE_GOLDEN=1 python3 -m unittest test_golden)  # golden 再生成
claude plugin validate --strict .             # プラグイン検証
```

## Phase 対応状況

- **Phase 1（コア）**: init / build / search / traverse / path / validate /
  move / new / log + スキル 7 種 + サブエージェント 3 種。
- **Phase 2（拡張検索）**: コミュニティ検出（CNM・決定論）と `kg community`、
  qmd 委譲の `kg vsearch` / `kg hybrid`（qmd 無効・不在時は exit 4、他機能は
  無影響）、`kg init --with-qmd`。検索品質の計測記録は
  `docs/phase2-search-eval.md`（qmd 2.5.3 実機での recall@10: 曖昧・意味系で
  search 0.85 に対し vsearch 0.95 / hybrid 0.90）。
- **Phase 3**: `pack` / `skillgen` / `hook-context` は exit 4（機能無効）。
  hooks.json は Phase 3 で同梱する（未実装コマンドのノイズ回避。02 §6.6）。

qmd を使う場合: `npm install -g @tobilu/qmd`（Node.js 22+）ののち
`kg init --with-qmd`（コレクション登録・埋め込み生成まで行う）。
qmd 2.5.3 で実機確認済み（詳細設計 04 §8.4）。CPU 環境では vsearch / hybrid は
1 クエリ 10〜45 秒程度かかる（クエリ拡張・リランカーの LLM 推論を含むため）。

# kg-wiki

Markdown 知識リポジトリ + 派生ナレッジグラフによる Claude Code 知識管理プラグイン。
設計文書は [kg-wiki-specs](../kg-wiki-specs) を参照（本リポジトリは Phase 1〜3 実装）。

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
kg pack "GraphRAG" --max-bytes 20000        # 関連ページ本文の束（コンテキストパック）
kg pack llm/papers/lightrag --hops 2        # 起点 ref + 近傍を束ねる
kg skillgen topic:llm                       # 生成 Skill の骨格を staging へ出力
kg skillgen topic:llm --install --dry-run   # 差分提示（承認ゲート）→ 承認後に --install
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
| `enable_hook_context` | true | UserPromptSubmit での関連ページポインタ注入（環境変数 `CLAUDE_PLUGIN_OPTION_ENABLE_HOOK_CONTEXT=false` で無効化） |
| `enable_qmd` | false | qmd 委譲のベクトル/ハイブリッド検索（`kg init --with-qmd` が設定する。環境変数 `CLAUDE_PLUGIN_OPTION_ENABLE_QMD` が優先） |

**hook 注入と `wiki_root` の注意**: Claude Code の制約により、hook プロセスは userConfig の値を
受け取れない（`${user_config.KEY}` は hook コマンドで展開されず、`CLAUDE_PLUGIN_OPTION_*` も
hook プロセスには渡らない。詳細設計 04 §10）。そのため **UserPromptSubmit の注入は `wiki_root`
の設定を見ない**（既定 `~/kg-wiki` を対象とする）。既定以外の場所にグローバル層を置く場合は、
シェル環境に `KG_WIKI_ROOT` を設定すること。未設定でも hook は空出力・exit 0 で安全に終わるが、
注入は機能しない（無言で何も起きない状態になる）。

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
  無影響）、`kg init --with-qmd`。検索品質の計測記録は kg-wiki-specs の
  `reports/phase2-search-eval.md`（qmd 2.5.3 実機での recall@10: 曖昧・意味系で
  search 0.85 に対し vsearch 0.95 / hybrid 0.90）。
- **Phase 3（供給・自動化）**: `kg pack`（関連ページ本文の束。ページ境界でのみ打ち切り）、
  `kg skillgen`（topic / コミュニティから Skill を生成。staging → 執筆 → 検証 →
  **ユーザ承認** → `--install`）、`kg validate --skills`（未執筆・stale な生成 Skill の検出）、
  `kg hook-context`（UserPromptSubmit への軽量注入。常に exit 0）。hooks.json を同梱
  （`UserPromptSubmit` → `hook-context`、`SessionStart` → `validate --quick`）。
  スキル 3 種（kg-ingest / kg-pack / kg-skillgen）を追加。
  生成 Skill は全プロジェクトで自動発火し得るため、配置には必ず人間のゲートを挟む
  （`--install --dry-run` の差分提示 → 承認 → `--install`。FR-4.2）。

qmd を使う場合: `npm install -g @tobilu/qmd`（Node.js 22+）ののち
`kg init --with-qmd`（コレクション登録・埋め込み生成まで行う）。
qmd 2.5.3 で実機確認済み（詳細設計 04 §8.4）。CPU 環境では vsearch / hybrid は
1 クエリ 10〜45 秒程度かかる（クエリ拡張・リランカーの LLM 推論を含むため）。

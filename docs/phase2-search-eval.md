# Phase 2 検索品質計測（search vs vsearch/hybrid）

Phase 2 完了条件（要件定義 01 §9）の「固定クエリセットでの再現率比較・記録」の
記録文書。合否ではなく傾向確認のための計測（基本設計 03 §7.3）。

## 計測資材

- クエリセット: `tests/fixtures/eval-queries.json`（20 問。lexical 10 / semantic 10）
- 対象コーパス: `tests/fixtures/wiki-mini`（2 層・22 ページ）
- 計測スクリプト: `tests/perf/compare_recall.py`

## 手順

```bash
cp -r tests/fixtures/wiki-mini /tmp/eval-wiki
export CLAUDE_PROJECT_DIR=/tmp/eval-wiki/project
bin/kg build --layer global  --root /tmp/eval-wiki/global
bin/kg build --layer project --root /tmp/eval-wiki/global
# qmd 導入 + 有効化（vsearch/hybrid を計測する場合）
#   npm install -g @tobilu/qmd
#   bin/kg init --layer global --root /tmp/eval-wiki/global --with-qmd
python3 tests/perf/compare_recall.py --root /tmp/eval-wiki/global
```

## 計測記録

### 2026-07-13（search ベースライン。qmd 未導入のため vsearch/hybrid は無効）

| 種別 | search | vsearch | hybrid |
|---|---|---|---|
| lexical（10 問） | 1.00 | 無効 | 無効 |
| semantic（10 問） | 0.85 | 無効 | 無効 |
| 全体 | 0.93 | 無効 | 無効 |

- 環境: kg-wiki 0.2.0 / recall@10
- semantic の取りこぼし: #12（community-detection が上位 10 に入らず 0.50）、
  #16（old-search 0.50）、#20（graphrag-bench 0.50）— いずれも語彙一致に乏しい
  俯瞰・意図系クエリで、vsearch/hybrid の優位が見込まれる箇所。
- **vsearch / hybrid の計測は qmd 実機確認（04 §8.4）後に追記する。**
  「曖昧系での優位を確認」という完了条件はこの追記をもって充足となる。

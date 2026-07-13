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

### 2026-07-13（qmd 2.5.3 導入・実機確認後の本計測）

| 種別 | search | vsearch | hybrid |
|---|---|---|---|
| lexical（10 問） | 1.00 | 1.00 | 1.00 |
| semantic（10 問） | 0.85 | **0.95** | **0.90** |
| 全体 | 0.93 | 0.97 | 0.95 |

- 環境: kg-wiki 0.2.0 / qmd 2.5.3（CPU 実行）/ recall@10
- **曖昧・意味系での vsearch / hybrid の優位を確認**（Phase 2 完了条件を充足）。
  - #15「クエリを言い換えながら繰り返し探す」・#20「どんなときにグラフ検索が
    有効か」で search の取りこぼしを vsearch / hybrid が回収（0.50 → 1.00）。
  - #12「知識の全体像を俯瞰して要約したい」は 3 方式とも 0.50
    （community-detection が届かない。俯瞰系は本来 `kg community` の担当であり、
    ルーティング表の設計と整合する結果）。
  - #13 は hybrid のみ 0.50 とわずかに劣化（リランカーの揺れ）。
- lexical は 3 方式とも 1.00 — 既知キーワードには `kg search` で十分であり、
  「まず search」を既定とするルーティング指針（02 §6.4）を裏づける。
- 所要時間の目安: search は 0.1 秒/問、vsearch / hybrid は CPU 環境で
  10〜45 秒/問（クエリ拡張・リランカーの LLM 推論を含む）。

### 2026-07-13（参考: qmd 未導入時の search ベースライン）

| 種別 | search | vsearch | hybrid |
|---|---|---|---|
| lexical（10 問） | 1.00 | 無効 | 無効 |
| semantic（10 問） | 0.85 | 無効 | 無効 |
| 全体 | 0.93 | 無効 | 無効 |

（vsearch / hybrid 無効時は exit 4 の縮退動作。search の値は本計測と一致 =
決定論の傍証）

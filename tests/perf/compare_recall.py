#!/usr/bin/env python3
"""search vs vsearch/hybrid の再現率比較。

固定クエリセット（tests/fixtures/eval-queries.json）で recall@k を計測し、
Markdown 表を stdout に出す。合否ではなく傾向確認のための計測スクリプト。
vsearch / hybrid が無効（qmd 未導入）の場合はその列を「無効」と表示する。

使い方:
  1. wiki-mini を任意の場所へ複製し、両層を kg build する
  2. python3 tests/perf/compare_recall.py --root <global層root> [--k 10]
     （プロジェクト層は CLAUDE_PROJECT_DIR または cwd の上方探索で解決）
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
BIN_KG = PLUGIN_ROOT / "bin" / "kg"
QUERIES = PLUGIN_ROOT / "tests" / "fixtures" / "eval-queries.json"
REF_RE = re.compile(r"\[\[([a-z0-9/-]+)\]\]")


def run_search(mode, query, root, k):
    proc = subprocess.run(
        [sys.executable, str(BIN_KG), mode, query, "--limit", str(k),
         "--root", str(root)],
        capture_output=True, text=True)
    if proc.returncode == 4:
        return None  # 機能無効
    if proc.returncode != 0:
        print(f"warn: kg {mode} '{query}' exit {proc.returncode}: "
              f"{proc.stderr.strip()}", file=sys.stderr)
        return []
    return [m.group(1) for line in proc.stdout.splitlines()
            if (m := REF_RE.search(line))]


def recall(hits, expected):
    if hits is None:
        return None
    return len(set(hits) & set(expected)) / len(expected)


def fmt(value):
    return "無効" if value is None else f"{value:.2f}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()

    data = json.loads(QUERIES.read_text(encoding="utf-8"))
    rows = []
    for entry in data["queries"]:
        row = {"id": entry["id"], "kind": entry["kind"], "query": entry["query"]}
        for mode in ("search", "vsearch", "hybrid"):
            row[mode] = recall(run_search(mode, entry["query"], args.root, args.k),
                               entry["expected"])
        rows.append(row)

    print(f"# search vs vsearch/hybrid recall@{args.k}\n")
    print("| # | 種別 | クエリ | search | vsearch | hybrid |")
    print("|---|---|---|---|---|---|")
    for row in rows:
        print(f"| {row['id']} | {row['kind']} | {row['query']} "
              f"| {fmt(row['search'])} | {fmt(row['vsearch'])} "
              f"| {fmt(row['hybrid'])} |")
    print()
    for kind in ("lexical", "semantic", None):
        subset = [r for r in rows if kind is None or r["kind"] == kind]
        label = kind or "all"
        means = []
        for mode in ("search", "vsearch", "hybrid"):
            values = [r[mode] for r in subset]
            if any(v is None for v in values):
                means.append("無効")
            else:
                means.append(f"{sum(values) / len(values):.2f}")
        print(f"mean recall ({label}): search={means[0]} "
              f"vsearch={means[1]} hybrid={means[2]}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""1,000 ページ規模の決定論的フィクスチャ生成（NFR-5 の性能計測用。03 §7.1）。

固定シードで生成し、出力はコミットしない。
使い方: python3 tests/perf/gen_fixture.py --pages 1000 --root /tmp/kg-perf
計測例:
  time bin/kg build --root /tmp/kg-perf --layer global          # 全再生成
  （1 ページ変更後）time bin/kg build ...                        # 増分 < 5 秒
  time bin/kg search "ベクトル 検索" --root /tmp/kg-perf         # < 1 秒
"""

import argparse
import random
from pathlib import Path

TYPES = ["concepts", "entities", "articles", "papers", "queries", "decisions"]
RELS = ["is_a", "part_of", "uses", "relates_to", "derived_from", "evaluated_by"]
WORDS = ["検索", "グラフ", "知識", "推論", "要約", "埋め込み", "評価", "増分",
         "retrieval", "graph", "knowledge", "agent", "index", "community"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=1000)
    parser.add_argument("--root", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--edges-per-page", type=int, default=3)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.yml").write_text(
        "version: 1\n"
        "topics:\n  - name: perf\n"
        f"types: [{', '.join(TYPES)}]\n"
        "relations: [is_a, part_of, uses, relates_to, contradicts, supersedes, "
        "derived_from, evaluated_by]\n",
        encoding="utf-8")
    (root / "log.md").write_text("", encoding="utf-8")

    refs = []
    for i in range(args.pages):
        ptype = TYPES[i % len(TYPES)]
        slug = f"page-{i:04d}"
        refs.append((f"perf/{ptype}/{slug}", ptype, slug))

    for i, (ref, ptype, slug) in enumerate(refs):
        keywords = rng.sample(WORDS, 3)
        relations = []
        for _ in range(rng.randrange(args.edges_per_page + 1)):
            target = refs[rng.randrange(len(refs))][0]
            if target != ref:
                relations.append((rng.choice(RELS), target))
        body_links = [refs[rng.randrange(len(refs))][0] for _ in range(2)]
        lines = [
            "---",
            f"title: ページ {i:04d} {keywords[0]}",
            f"type: {ptype}",
            f"slug: {slug}",
            f"summary: {keywords[0]}と{keywords[1]}に関する自動生成ページ",
            f"keywords: [{', '.join(keywords)}]",
        ]
        if relations:
            lines.append("relations:")
            seen = set()
            for rel, to in relations:
                if (rel, to) in seen:
                    continue
                seen.add((rel, to))
                lines += [f"  - rel: {rel}", f"    to: {to}"]
        lines += ["updated: 2026-07-01", "---", "",
                  f"{keywords[2]} に関する本文。" + " ".join(keywords), ""]
        for link in body_links:
            if link != ref:
                lines.append(f"[[{link}]] も参照。")
        path = root / "topics" / "perf" / "pages" / ptype / f"{slug}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"generated {len(refs)} pages under {root}")


if __name__ == "__main__":
    main()

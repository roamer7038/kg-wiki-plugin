"""KG エッジ抽出・graph.tsv・adjacency.json・実行時マージ（03 §3.4〜3.5、04 §4.1）。"""

import json

from . import pages as pages_mod
from . import refs
from .layers import GLOBAL

SRC_FRONTMATTER = "frontmatter"
SRC_BODY = "body"
MENTIONS = "mentions"
ADJ_SCHEMA_VERSION = 1


def extract_edges(page):
    """1 ページのエッジ集合 [(from, rel, to, src)]（重複正規化・辞書順。03 §3.4）。

    本文リンクは正準形のもののみエッジ化する（逸脱は kg validate の ref-format が
    検出する）。
    """
    edges = set()
    for relation in page.relations:
        edges.add((page.ref, relation.rel, relation.to, SRC_FRONTMATTER))
    for link in pages_mod.extract_body_links(page.body):
        if refs.is_canonical(link) and link != page.ref:
            edges.add((page.ref, MENTIONS, link, SRC_BODY))
    return sorted(edges)


def graph_tsv_text(edges) -> str:
    """エッジ列 → TSV（(from, rel, to, src) 一意・辞書順・末尾改行）。空なら空文字列。"""
    unique = sorted(set(edges))
    return "".join("\t".join(edge) + "\n" for edge in unique)


def parse_graph_tsv(text: str):
    edges = []
    for line in text.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) == 4:
            edges.append(tuple(parts))
    return edges


def adjacency_data(edges, index_refs) -> dict:
    """topic の graph エッジ + index の全 ref から adjacency を構築する（03 §3.5）。"""
    nodes = set(index_refs)
    out = {}
    inn = {}
    for from_ref, rel, to_ref, _src in edges:
        nodes.add(from_ref)
        nodes.add(to_ref)
        out.setdefault(from_ref, set()).add((rel, to_ref))
        inn.setdefault(to_ref, set()).add((rel, from_ref))
    return {
        "in": {ref: [list(pair) for pair in sorted(pairs)] for ref, pairs in sorted(inn.items())},
        "nodes": sorted(nodes),
        "out": {ref: [list(pair) for pair in sorted(pairs)] for ref, pairs in sorted(out.items())},
        "schema_version": ADJ_SCHEMA_VERSION,
    }


def adjacency_json_text(adj: dict) -> str:
    return json.dumps(adj, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def load_adjacency(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def merge_adjacencies(layer_adjs, shadow):
    """実行時マージ（04 §4.1）。layer_adjs = [(kind, adj_dict), ...]。

    from 基準規則: from（in 方向はエントリの相手 = from）が shadow ref に属する
    グローバル層のエッジは捨て、それ以外は和集合。(out, in, nodes) を返す。
    """
    out = {}
    inn = {}
    nodes = set()
    for kind, adj in layer_adjs:
        if adj is None:
            continue
        nodes.update(adj.get("nodes", []))
        for ref, pairs in adj.get("out", {}).items():
            if kind == GLOBAL and ref in shadow:
                continue  # shadow された from の出エッジは捨てる
            out.setdefault(ref, set()).update((rel, other) for rel, other in pairs)
        for ref, pairs in adj.get("in", {}).items():
            for rel, from_ref in pairs:
                if kind == GLOBAL and from_ref in shadow:
                    continue  # in 方向にも from 基準を適用（03 §2.3）
                inn.setdefault(ref, set()).add((rel, from_ref))
    out_sorted = {ref: sorted(pairs) for ref, pairs in out.items() if pairs}
    in_sorted = {ref: sorted(pairs) for ref, pairs in inn.items() if pairs}
    return out_sorted, in_sorted, sorted(nodes)


def get_neighbors(out, inn, node_ref, direction="both", rel_filter=None):
    """BFS 用の決定論的隣接列挙（04 §4.2。out → in、各 (rel, 相手) 辞書順）。"""
    neighbors = []
    if direction in ("both", "out"):
        for rel, to_ref in out.get(node_ref, ()):
            if rel_filter is None or rel in rel_filter:
                neighbors.append((rel, to_ref, "out"))
    if direction in ("both", "in"):
        for rel, from_ref in inn.get(node_ref, ()):
            if rel_filter is None or rel in rel_filter:
                neighbors.append((rel, from_ref, "in"))
    return neighbors

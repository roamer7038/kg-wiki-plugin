"""kg traverse: adjacency 上の決定論 BFS。"""

from . import graph as graph_mod
from . import layers as layers_mod
from .errors import KgError

MISSING = "(missing)"


def load_merged_graph(layer_list, topics):
    """対象層・topic の adjacency を実行時マージする。(out, in, nodes, index, shadow)。

    --topic はエッジの出所 topic の絞り込みであり、到達ノードは他 topic
    の ref でもよい。したがって adjacency のみ topic で絞り、index（起点解決・
    タイトル/要約の表示）は常に全 topic から引く。
    """
    layer_records = [(ly.kind, layers_mod.load_index_records(ly, topics=None))
                     for ly in layer_list]
    merged_index, shadow = layers_mod.merge_index(layer_records)
    layer_adjs = []
    for ly in layer_list:
        for topic in (topics if topics is not None else layers_mod.fs_topics(ly.root)):
            path = layers_mod.derived_dir(ly.root, topic) / "adjacency.json"
            if path.is_file():
                adj = graph_mod.load_adjacency(path)
                if adj is not None:
                    layer_adjs.append((ly.kind, adj))
    out, inn, nodes = graph_mod.merge_adjacencies(layer_adjs, shadow)
    return out, inn, nodes, merged_index, shadow


def bfs(out, inn, start: str, max_hops: int, direction: str, rel_filter):
    """決定論 BFS。[(ref, hop, parent, rel, direction)] を返す。"""
    from collections import deque

    queue = deque([(start, 0, None, None, None)])
    visited = {start}
    results = []
    while queue:
        ref, hop, parent, rel, direc = queue.popleft()
        if hop > 0:
            results.append((ref, hop, parent, rel, direc))
        if hop == max_hops:
            continue
        for n_rel, n_ref, n_dir in graph_mod.get_neighbors(out, inn, ref,
                                                           direction, rel_filter):
            if n_ref not in visited:
                visited.add(n_ref)
                queue.append((n_ref, hop + 1, ref, n_rel, n_dir))
    results.sort(key=lambda r: (r[1], r[0]))  # hop 昇順 → ref 昇順
    return results


def run_traverse(ref: str, layer_list, topics, hops: int, rel_filter,
                 direction: str, limit: int):
    out, inn, _nodes, merged_index, _shadow = load_merged_graph(layer_list, topics)
    if ref not in merged_index:
        raise KgError(f"起点ページが両層に不在: {ref}（kg build 済みか確認する）")
    results = bfs(out, inn, ref, hops, direction, rel_filter)[:limit]
    return results, merged_index


def format_row(row, merged_index) -> str:
    ref, hop, parent, rel, direc = row
    rec = merged_index.get(ref)
    if rec is None:
        desc = MISSING
    else:
        desc = f"{rec.get('title', '')} — {rec.get('summary', '')}"
    via = f"via [[{parent}]] -{rel}->" if direc == "out" else f"via [[{parent}]] <-{rel}-"
    return f"{hop}\t[[{ref}]]\t{desc}\t{via}"


def row_record(row, merged_index) -> dict:
    ref, hop, parent, rel, direc = row
    rec = merged_index.get(ref)
    data = dict(rec) if rec is not None else {"ref": ref}
    data["hop"] = hop
    data["via"] = {"direction": direc, "parent": parent, "rel": rel}
    return data

"""kg path: 距離誘導 DFS による最短経路の有界列挙（03 §4.6、04 §4.3、A-16）。"""

from collections import deque

from . import graph as graph_mod
from .errors import KgError


def bfs_distances(out, inn, start: str, max_hops: int) -> dict:
    """無向視点（out/in 両方向）の BFS 距離（max_hops 上限）。"""
    dist = {start: 0}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        d = dist[node]
        if d == max_hops:
            continue
        for _rel, other, _dir in graph_mod.get_neighbors(out, inn, node, "both", None):
            if other not in dist:
                dist[other] = d + 1
                queue.append(other)
    return dist


def enumerate_paths(out, inn, ref1: str, ref2: str, max_paths: int, max_hops: int):
    """最短経路を先頭 K 本（ステップ組辞書順）列挙する。経路 = [(ref, rel, dir)]。"""
    d2 = bfs_distances(out, inn, ref2, max_hops)
    if ref1 not in d2:
        return None  # 経路なし
    L = d2[ref1]
    paths = []

    def dfs(u, t, steps):
        if len(paths) == max_paths:
            return
        if t == L:
            paths.append(steps)
            return
        cand = [(v, rel, d) for rel, v, d in graph_mod.get_neighbors(out, inn, u,
                                                                     "both", None)
                if d2.get(v) == L - t - 1]
        cand.sort(key=lambda s: (s[0], s[1], 0 if s[2] == "out" else 1))
        for v, rel, d in cand:
            if len(paths) == max_paths:
                return
            dfs(v, t + 1, steps + [(v, rel, d)])

    dfs(ref1, 0, [])
    return paths


def run_path(ref1: str, ref2: str, layer_list, topics, max_paths: int, max_hops: int):
    from .traverse import load_merged_graph

    out, inn, _nodes, merged_index, _shadow = load_merged_graph(layer_list, topics)
    for endpoint in (ref1, ref2):
        if endpoint not in merged_index:
            raise KgError(f"端点ページが両層に不在: {endpoint}（kg build 済みか確認する）")
    return enumerate_paths(out, inn, ref1, ref2, max_paths, max_hops)


def format_path(ref1: str, steps) -> str:
    parts = [f"[[{ref1}]]"]
    for ref, rel, direc in steps:
        if direc == "out":
            parts.append(f"-{rel}-> [[{ref}]]")
        else:
            parts.append(f"<-{rel}- [[{ref}]]")
    return f"{len(steps)}\t" + " ".join(parts)


def path_record(ref1: str, steps) -> dict:
    return {
        "from": ref1,
        "len": len(steps),
        "steps": [{"direction": d, "ref": r, "rel": rel} for r, rel, d in steps],
    }

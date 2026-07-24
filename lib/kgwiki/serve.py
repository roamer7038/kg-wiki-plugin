"""kg serve: ローカル・読み取り専用の Web ビューワ（05）。

HTTP に触れるのは §6 のアダプタのみ。検索・グラフ・層マージのロジックは
既存モジュールに委譲し、本モジュールでは再実装しない（05 §5.1）。
"""

from dataclasses import dataclass

from . import graph as graph_mod
from . import hashing
from . import layers as layers_mod
from . import manifest as manifest_mod
from . import traverse as traverse_mod


@dataclass
class ViewContext:
    layer_list: list
    topics: list = None


def load_merged_index(ctx):
    layer_records = [(ly.kind, layers_mod.load_index_records(ly, ctx.topics))
                     for ly in ctx.layer_list]
    return layers_mod.merge_index(layer_records)


def find_page(ctx, ref):
    """ref → (layer, path)。プロジェクト層優先（DR-2）。無ければ (None, None)。"""
    found = (None, None)
    for layer in ctx.layer_list:            # select_layers は global→project 順
        path = layers_mod.page_path(layer, ref)
        if path.is_file():
            found = (layer, path)
    return found


def page_state(layer, ref, path):
    """05 §6.2 の 4 状態のうち、当該ページの状態を返す。"""
    topic = ref.split("/")[0]
    derived = layers_mod.derived_dir(layer.root, topic)
    data = manifest_mod.load(derived)
    if not manifest_mod.is_current(data):
        return "unbuilt"
    recorded = (data.get("pages") or {}).get(ref)
    if recorded is None:
        return "new"
    return "ok" if recorded == hashing.page_hash(path) else "stale"


def backlinks(ctx, ref):
    """自ページを参照している (rel, from_ref) の一覧。辞書順。"""
    out, inn, _nodes, _index, _shadow = traverse_mod.load_merged_graph(
        ctx.layer_list, ctx.topics)
    rows = [(rel, other)
            for rel, other, direction in graph_mod.get_neighbors(
                out, inn, ref, direction="in")
            if direction == "in"]
    return sorted(set(rows))


def topic_stats(ctx):
    """ホーム用のトピック統計（05 §3.2）。

    ref 単位で重複を除去する（層マージ相当。shadow は 1 回のみ数える）。
    プロジェクト層優先（DR-2）は layer_list の走査順（global→project）に
    委ね、後勝ちの上書きで採用する。未 build のトピックも表示するため
    ファイルシステム走査は維持し、index には頼らない。
    """
    topic_names = set()
    entries = {}  # ref -> (topic, type_dir, layer, path)
    for layer in ctx.layer_list:
        topics = ctx.topics if ctx.topics is not None else layers_mod.fs_topics(layer.root)
        topic_names.update(topics)
        for topic in topics:
            for type_dir, slug, path in layers_mod.iter_page_paths(layer.root, topic):
                ref = "%s/%s/%s" % (topic, type_dir, slug)
                entries[ref] = (topic, type_dir, layer, path)

    stats = {name: {"topic": name, "count": 0, "types": {}, "stale": 0}
              for name in topic_names}
    for ref, (topic, type_dir, layer, path) in entries.items():
        entry = stats[topic]
        entry["count"] += 1
        entry["types"][type_dir] = entry["types"].get(type_dir, 0) + 1
        if page_state(layer, ref, path) != "ok":
            entry["stale"] += 1
    return [stats[name] for name in sorted(stats)]

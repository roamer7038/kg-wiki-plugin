"""kg build パイプライン。

topic 単位の純関数パイプライン。派生物を書き終えてから manifest を最後に
アトミック書き込みする（収束規約）。
"""

from dataclasses import dataclass, field

from . import config as config_mod
from . import graph, hashing, indexer, layers, manifest, fsio
from . import pages as pages_mod
from .errors import KgError, UsageError
from .output import sort_issues


@dataclass
class TopicResult:
    topic: str
    ok: bool
    pages: int = 0
    added: int = 0
    changed: int = 0
    removed: int = 0
    issues: list = field(default_factory=list)

    def summary_line(self) -> str:
        return (f"built {self.topic}: {self.pages} pages "
                f"(+{self.added} ~{self.changed} -{self.removed})")

    def summary_record(self) -> dict:
        return {"added": self.added, "changed": self.changed, "pages": self.pages,
                "removed": self.removed, "topic": self.topic}


def build_topic(layer, cfg, topic: str, full: bool) -> TopicResult:
    root = layer.root
    derived = layers.derived_dir(root, topic)
    result = TopicResult(topic=topic, ok=True)

    # (1)(2) 現況スキャンと manifest 差分検出（コンテンツハッシュ。mtime 不使用）
    current = {}  # ref -> (path, type_dir, hash)
    for type_dir, slug, path in layers.iter_page_paths(root, topic):
        ref = f"{topic}/{type_dir}/{slug}"
        current[ref] = (path, type_dir, hashing.page_hash(path))

    man = manifest.load(derived)
    old_pages = man.get("pages") if man and isinstance(man.get("pages"), dict) else {}
    incremental = (not full) and manifest.is_current(man)

    added = sorted(r for r in current if r not in old_pages)
    changed = sorted(r for r in current if r in old_pages and old_pages[r] != current[r][2])
    removed = sorted(r for r in old_pages if r not in current)

    old_records = {}
    old_edges_by_from = {}
    if incremental:
        idx_path = derived / "index.jsonl"
        graph_path = derived / "graph.tsv"
        if idx_path.is_file() and graph_path.is_file():
            for ref, rec in layers.load_index_records(layer, topics=[topic]).items():
                old_records[ref] = rec
            for edge in graph.parse_graph_tsv(graph_path.read_text(encoding="utf-8")):
                old_edges_by_from.setdefault(edge[0], []).append(edge)
        else:
            incremental = False  # 派生物が欠落 → 全再生成

    to_parse = set(added) | set(changed)
    layer_changed = []
    if incremental:
        for ref in current:
            if ref in to_parse:
                continue
            rec = old_records.get(ref)
            if rec is None or rec.get("hash") != current[ref][2]:
                to_parse.add(ref)  # index 側の欠落・乖離 → 再抽出
            elif rec.get("layer") != layer.kind:
                to_parse.add(ref)  # 層の複製 → 変更扱い
                layer_changed.append(ref)
            elif rec.get("type") not in cfg.types or any(
                    rel != graph.MENTIONS and rel not in cfg.relations
                    for _f, rel, _t, _s in old_edges_by_from.get(ref, ())):
                # config 変更（使用中 type/rel の削除等）→ 再検証して全再生成と
                # 同じ中断挙動にする（増分・全再生成一致）
                to_parse.add(ref)
    else:
        to_parse = set(current)

    # (1) frontmatter パース + スキーマ検証（違反ページがあれば topic 全体を中断）
    parsed = {}
    halting = []
    for ref in sorted(to_parse):
        path, type_dir, _h = current[ref]
        page, issues = pages_mod.load_page(path, layer.kind, topic, type_dir, cfg)
        halting.extend(i for i in issues if i.halts)
        if page is not None:
            parsed[ref] = page
    if halting:
        result.ok = False
        result.issues = sort_issues(halting)
        return result

    # (3)(4) index / graph / adjacency の再構成
    records = {}
    edges = []
    for ref in current:
        if ref in parsed:
            records[ref] = indexer.page_record(parsed[ref])
            edges.extend(graph.extract_edges(parsed[ref]))
        else:
            records[ref] = old_records[ref]
            edges.extend(old_edges_by_from.get(ref, []))

    adj = graph.adjacency_data(edges, records.keys())

    # (5) コミュニティ検出（増分でも毎回グラフ全体で再計算する）
    from . import community
    weights = community.build_weights(edges, set(records))
    communities = community.detect(weights)
    ids = community.assign_ids(communities, community.load_assignment(derived))
    assignment = community.assignment_data(communities, ids)
    md_texts = {}
    for idx, member_list in enumerate(communities):
        cid = ids[idx]
        md_path = derived / "communities" / f"{cid}.md"
        existing_summary = None
        if md_path.is_file():
            existing_summary = community.summary_region(
                md_path.read_text(encoding="utf-8"))
        md_texts[cid] = community.community_md_text(
            topic, cid, member_list, records, edges, existing_summary)

    # (7) 書き込み（派生物 → manifest の順。各ファイルはアトミック）
    fsio.atomic_write_text(derived / "index.jsonl", indexer.index_jsonl_text(records))
    fsio.atomic_write_text(derived / "index.md", indexer.index_md_text(topic, records))
    fsio.atomic_write_text(derived / "graph.tsv", graph.graph_tsv_text(edges))
    fsio.atomic_write_text(derived / "adjacency.json", graph.adjacency_json_text(adj))
    fsio.atomic_write_text(derived / "communities" / "assignment.json",
                           community.assignment_json_text(assignment))
    for cid, text in md_texts.items():
        fsio.atomic_write_text(derived / "communities" / f"{cid}.md", text)
    manifest.write(derived, manifest.build_manifest(
        {r: v[2] for r, v in current.items()}, community.ALGORITHM))

    result.pages = len(current)
    result.added = len(added)
    result.changed = len(changed) + len(layer_changed)
    result.removed = len(removed)
    return result


def build_layer(layer, topics_filter=None, full=False):
    """層の全 topic（または指定 topic）を build する。[TopicResult] を返す。

    config 不在は KgError（exit 1、kg init を案内）。config スキーマ違反は
    TopicResult ではなく config issue のリストを ok=False で返す。
    """
    cfg, cfg_issues, exists = config_mod.load_config(layer.root)
    if not exists:
        raise KgError(f"config.yml がない: {layer.root}（kg init で初期化する）")
    if cfg_issues:
        fail = TopicResult(topic="", ok=False)
        fail.issues = sort_issues(cfg_issues)
        return [fail]
    topic_names = cfg.topic_names()
    if topics_filter is not None:
        unknown = [t for t in topics_filter if t not in topic_names]
        if unknown:
            raise UsageError(f"config 未定義の topic: {', '.join(unknown)}")
        topic_names = [t for t in topic_names if t in topics_filter]
    return [build_topic(layer, cfg, topic, full) for topic in topic_names]

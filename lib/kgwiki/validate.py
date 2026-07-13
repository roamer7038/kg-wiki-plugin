"""kg validate: 全 issue コード検査（基本設計 03 §4.7）。"""

from . import graph as graph_mod
from . import hashing, layers, manifest
from . import pages as pages_mod
from . import refs as refs_mod
from .layers import GLOBAL, PROJECT
from .output import Issue, sort_issues

DERIVED_FILES = ("manifest.json", "index.jsonl", "index.md", "graph.tsv", "adjacency.json")


def _resolution_refset(cli_root):
    """リンク解決用の「両層いずれかに存在するページ ref」集合（--layer 指定に依らない）。"""
    refset = set()
    global_root = layers.resolve_global_root(cli_root)
    refset.update(layers.scan_page_refs(global_root))
    project_root = layers.find_project_root()
    if project_root is not None:
        refset.update(layers.scan_page_refs(project_root))
    return refset


def run_validate(layer_list, topics=None, cli_root=None):
    """検査を実行し、整列済み Issue リストを返す。"""
    issues = []
    loaded_layers = []

    for layer in layer_list:
        loaded = layers.load_layer(layer, topics=topics)
        loaded_layers.append(loaded)

        # config-schema
        if not loaded.config_exists:
            issues.append(Issue("error", "config-schema", f"{layer.kind}:config.yml",
                                "config.yml がない（kg init で初期化する）"))
        else:
            for issue in loaded.config_issues:
                issues.append(Issue(issue.severity, issue.code,
                                    f"{layer.kind}:config.yml", issue.message))
            if not loaded.config_issues and loaded.config is not None:
                names = set(loaded.config.topic_names())
                for stray in sorted(set(layers.fs_topics(layer.root)) - names):
                    if topics is not None and stray not in topics:
                        continue
                    issues.append(Issue("error", "config-schema",
                                        f"{layer.kind}:topics/{stray}",
                                        "config.topics に未定義の topic ディレクトリ"))

        # ページ単位の issue（fm-parse / fm-schema / *-mismatch / rel-* / keywords-duplicate）
        issues.extend(loaded.page_issues)

    refset = _resolution_refset(cli_root)

    # 層マージ（shadow・グラフ）
    pages_by_layer = {ld.layer.kind: ld.pages for ld in loaded_layers}
    shadow = set()
    if GLOBAL in pages_by_layer and PROJECT in pages_by_layer:
        shadow = set(pages_by_layer[GLOBAL]) & set(pages_by_layer[PROJECT])
    for ref in sorted(shadow):
        issues.append(Issue("warn", "shadow", ref,
                            "同一 ref が両層に存在（プロジェクト層を優先）"))

    merged_pages = {}
    for ld in loaded_layers:  # global → project の順 = プロジェクト層優先で上書き
        merged_pages.update(ld.pages)

    # リンク検査・本文検査
    for ld in loaded_layers:
        for ref in sorted(ld.pages):
            page = ld.pages[ref]
            for relation in page.relations:
                if relation.to not in refset:
                    issues.append(Issue("error", "link-broken-fm", ref,
                                        f"relations.to の未解決: {relation.to}"))
            seen_links = set()
            for link in pages_mod.extract_body_links(page.body):
                if not refs_mod.is_canonical(link):
                    if ("ref-format", link) not in seen_links:
                        issues.append(Issue("error", "ref-format", ref,
                                            f"本文リンクが正準形でない: [[{link}]]"))
                        seen_links.add(("ref-format", link))
                elif link not in refset and ("broken", link) not in seen_links:
                    issues.append(Issue("warn", "link-broken-body", ref,
                                        f"本文リンクの未解決: [[{link}]]"))
                    seen_links.add(("broken", link))
            if pages_mod.body_has_h1(page.body):
                issues.append(Issue("warn", "body-h1", ref,
                                    "本文に h1 見出し（title が h1 相当）"))

    # マージ後グラフ（page-orphan / contradicts-pair / superseded-ref）
    edges = []
    for ld in loaded_layers:
        for ref in sorted(ld.pages):
            if ld.layer.kind == GLOBAL and ref in shadow:
                continue  # from 基準規則: shadow された from の出エッジは捨てる
            edges.extend(graph_mod.extract_edges(ld.pages[ref]))
    edges = sorted(set(edges))

    degree = {ref: 0 for ref in merged_pages}
    superseded = {}  # to -> from（supersedes 宣言）
    for from_ref, rel, to_ref, _src in edges:
        if from_ref in degree:
            degree[from_ref] += 1
        if to_ref in degree:
            degree[to_ref] += 1
        if rel == "contradicts":
            issues.append(Issue("info", "contradicts-pair", from_ref,
                                f"{from_ref} ↔ {to_ref}"))
        if rel == "supersedes":
            superseded[to_ref] = from_ref
    for ref in sorted(degree):
        if degree[ref] == 0:
            issues.append(Issue("warn", "page-orphan", ref,
                                "入出エッジ（mentions 含む）が 0"))
    for from_ref, rel, to_ref, _src in edges:
        if to_ref in superseded and superseded[to_ref] != from_ref:
            issues.append(Issue("info", "superseded-ref", from_ref,
                                f"[[{to_ref}]] は [[{superseded[to_ref]}]] に "
                                f"supersede されている（{rel} で参照中）"))

    # derived-stale / topic-empty
    for ld in loaded_layers:
        cfg = ld.config
        topic_names = cfg.topic_names() if cfg is not None else layers.fs_topics(ld.layer.root)
        if topics is not None:
            topic_names = [t for t in topic_names if t in topics]
        for topic in topic_names:
            target = f"{ld.layer.kind}:{topic}"
            current = {ref: page.hash for ref, page in ld.pages.items()
                       if ref.startswith(topic + "/")}
            if not current:
                issues.append(Issue("info", "topic-empty", target, "ページを持たない topic"))
            derived = layers.derived_dir(ld.layer.root, topic)
            man = manifest.load(derived)
            if man is None:
                if current or derived.is_dir():
                    issues.append(Issue("warn", "derived-stale", target,
                                        "manifest.json がない（kg build を実行）"))
                continue
            missing = [n for n in DERIVED_FILES if not (derived / n).is_file()]
            if missing:
                issues.append(Issue("warn", "derived-stale", target,
                                    f"派生物の欠落: {', '.join(missing)}（kg build を実行）"))
            if not manifest.is_current(man):
                issues.append(Issue("warn", "derived-stale", target,
                                    "manifest のバージョン不一致（kg build を実行）"))
            elif man.get("pages") != current:
                issues.append(Issue("warn", "derived-stale", target,
                                    "pages/ と manifest の不一致（kg build を実行）"))

    return sort_issues(issues)


def run_quick(layer_list, cli_root=None) -> str:
    """--quick: 鮮度・件数のみの 1 行集約（03 §4.7。常に exit 0 は cli 層が保証）。"""
    total_pages = 0
    n_layers = 0
    stale = False
    for layer in layer_list:
        if not layer.root.is_dir():
            continue
        n_layers += 1
        for topic in layers.fs_topics(layer.root):
            current = {}
            for type_dir, slug, path in layers.iter_page_paths(layer.root, topic):
                current[f"{topic}/{type_dir}/{slug}"] = hashing.page_hash(path)
            total_pages += len(current)
            derived = layers.derived_dir(layer.root, topic)
            man = manifest.load(derived)
            if man is None:
                if current:
                    stale = True
                continue
            if not manifest.is_current(man) or man.get("pages") != current \
                    or any(not (derived / n).is_file() for n in DERIVED_FILES):
                stale = True
    state = "stale (run kg build)" if stale else "fresh"
    plural = "layer" if n_layers == 1 else "layers"
    return f"kg: {n_layers} {plural}, {total_pages} pages, derived: {state}"

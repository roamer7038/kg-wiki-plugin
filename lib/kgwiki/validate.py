"""kg validate: 全 issue コード検査（基本設計 03 §4.7）。"""

from . import community as community_mod
from . import graph as graph_mod
from . import hashing, layers, manifest, yamlsub
from . import pages as pages_mod
from . import refs as refs_mod
from .errors import KgError
from .layers import GLOBAL, PROJECT
from .output import TRUST_NOTICE, Issue, sort_issues

DERIVED_FILES = ("manifest.json", "index.jsonl", "index.md", "graph.tsv",
                 "adjacency.json", "communities/assignment.json")
COMMUNITY_FM_KEYS = {"community", "topic", "built_from"}


def _resolution_refset(cli_root):
    """リンク解決用の「両層いずれかに存在するページ ref」集合（--layer 指定に依らない）。"""
    refset = set()
    global_root = layers.resolve_global_root(cli_root)
    refset.update(layers.scan_page_refs(global_root))
    project_root = layers.find_project_root()
    if project_root is not None:
        refset.update(layers.scan_page_refs(project_root))
    return refset


def run_validate(layer_list, topics=None, cli_root=None, skills=False, dest=None):
    """検査を実行し、整列済み Issue リストを返す。

    skills=True で生成 Skill の検査（skill-format / skill-stale）を追加する（03 §4.7）。
    """
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

    # コミュニティ要約 md の検査（Phase 2。03 §3.6: community-format / community-stale）
    for ld in loaded_layers:
        cfg = ld.config
        topic_names = cfg.topic_names() if cfg is not None else layers.fs_topics(ld.layer.root)
        if topics is not None:
            topic_names = [t for t in topic_names if t in topics]
        for topic in topic_names:
            issues.extend(_community_issues(ld, topic))

    # qmd バージョン逸脱（Phase 2。03 §4.7: qmd-version）
    issues.extend(_qmd_version_issues(loaded_layers))

    # 生成 Skill（Phase 3。--skills 指定時のみ。03 §3.7: skill-format / skill-stale）
    if skills:
        issues.extend(run_skills(loaded_layers, dest))

    return sort_issues(issues)


def _community_issues(ld, topic):
    issues = []
    derived = layers.derived_dir(ld.layer.root, topic)
    cdir = derived / "communities"
    if not cdir.is_dir():
        return issues
    assignment = community_mod.load_assignment(derived)
    members_by_id = {}
    if assignment is not None:
        raw = assignment.get("communities")
        if isinstance(raw, dict):
            members_by_id = {k: v for k, v in raw.items() if isinstance(v, list)}
    for md_path in sorted(cdir.glob("*.md")):
        cid = md_path.name[:-3]
        target = f"{ld.layer.kind}:{topic}/{cid}"
        text = md_path.read_text(encoding="utf-8")
        fm_lines, _sk, _su, errors = community_mod.parse_community_md(text)
        for message in errors:
            issues.append(Issue("error", "community-format", target, message))
        built_from = None
        if fm_lines is not None:
            data, yaml_issues = yamlsub.parse_mapping_lines(fm_lines, first_lineno=2)
            for yi in yaml_issues:
                issues.append(Issue("error", "community-format", target,
                                    f"L{yi.line}: {yi.message}"))
            unknown = set(data) - COMMUNITY_FM_KEYS
            missing = COMMUNITY_FM_KEYS - set(data)
            if unknown:
                issues.append(Issue("error", "community-format", target,
                                    f"未知キー: {', '.join(sorted(unknown))}"))
            if missing:
                issues.append(Issue("error", "community-format", target,
                                    f"必須キーの欠落: {', '.join(sorted(missing))}"))
            if "community" in data and data["community"] != cid:
                issues.append(Issue("error", "community-format", target,
                                    f"community '{data['community']}' が"
                                    f"ファイル名 '{cid}' と一致しない"))
            if "topic" in data and data["topic"] != topic:
                issues.append(Issue("error", "community-format", target,
                                    f"topic '{data['topic']}' が不一致"))
            built_from = data.get("built_from")
            if built_from is not None and not (isinstance(built_from, str)
                                               and built_from.startswith("sha256:")):
                issues.append(Issue("error", "community-format", target,
                                    "built_from は 'sha256:<hex64>' であること"))
                built_from = None
        # stale / 孤児（A-5。04 §5.3: 孤児は community-stale の message で区別）
        if cid not in members_by_id:
            issues.append(Issue("warn", "community-stale", target,
                                "現分割に存在しない旧コミュニティの孤児 md"
                                "（内容確認のうえ手動削除する）"))
            continue
        if built_from is None:
            continue  # format エラーとして報告済み
        current = {}
        stale = False
        for member in members_by_id[cid]:
            page = ld.pages.get(member)
            if page is None:
                stale = True
                continue
            current[member] = page.hash
        if stale or hashing.set_hash(current) != built_from:
            issues.append(Issue("warn", "community-stale", target,
                                "built_from が現所属ページの集合ハッシュと不一致"
                                "（kg build と要約の再執筆を検討）"))
    return issues


def run_skills(loaded_layers, dest=None):
    """生成 Skill の検査（03 §3.7）。staging + インストール先を走査する。"""
    from . import skillgen
    issues = []
    for ld in loaded_layers:
        for topic, name, path in skillgen.iter_staging(ld.layer):
            target = f"{ld.layer.kind}:{topic}/skills/{name}"
            issues.extend(skill_file_issues(path, name, target, loaded_layers))
    for name, path in skillgen.iter_installed(dest):
        issues.extend(skill_file_issues(path, name, str(path.parent),
                                        loaded_layers))
    return issues


def skill_file_issues(path, name, target, loaded_layers):
    """1 つの生成 SKILL.md の issue（03 §3.7 の検証項目）。"""
    from . import skillgen
    issues = []
    text = path.read_text(encoding="utf-8")

    fm_lines, _sk, summary, errors = community_mod.parse_community_md(text)
    for message in errors:
        issues.append(Issue("error", "skill-format", target, message))

    # 信頼境界の注意書き定型文（完全一致。03 §6.4）
    lines = text.split("\n")
    for notice in TRUST_NOTICE:
        if notice not in lines:
            issues.append(Issue("error", "skill-format", target,
                                "信頼境界の注意書き定型文がない（03 §6.4 と完全一致）"))
            break

    if fm_lines is None:
        return issues
    data, yaml_issues = yamlsub.parse_mapping_lines(fm_lines, first_lineno=2)
    for yi in yaml_issues:
        issues.append(Issue("error", "skill-format", target,
                            f"L{yi.line}: {yi.message}"))
    unknown = set(data) - skillgen.FM_KEYS
    missing = skillgen.FM_KEYS - set(data)
    if unknown:
        issues.append(Issue("error", "skill-format", target,
                            f"未知キー: {', '.join(sorted(unknown))}"))
    if missing:
        issues.append(Issue("error", "skill-format", target,
                            f"必須キーの欠落: {', '.join(sorted(missing))}"))
    if "name" in data and data["name"] != name:
        issues.append(Issue("error", "skill-format", target,
                            f"name '{data['name']}' がディレクトリ名 '{name}' と"
                            "一致しない"))
    built_from = data.get("built_from")
    if built_from is not None and not (isinstance(built_from, str)
                                       and built_from.startswith("sha256:")):
        issues.append(Issue("error", "skill-format", target,
                            "built_from は 'sha256:<hex64>' であること"))
        built_from = None
    kg_source = data.get("kg_source")
    if kg_source is not None and not (
            isinstance(kg_source, str)
            and kg_source.partition(":")[0] in ("topic", "community")
            and kg_source.partition(":")[2]):
        issues.append(Issue("error", "skill-format", target,
                            "kg_source は 'topic:<topic>' または 'community:<id>' "
                            "であること"))
        kg_source = None

    if errors:
        return issues  # 領域が壊れている間は未執筆・stale を判定しない

    # 未執筆の LLM 領域（03 §3.7。--install の事前検証で exit 2 となる条件）
    if skillgen.is_unwritten(data.get("description"), summary):
        issues.append(Issue("error", "skill-format", target,
                            "LLM 執筆領域が未執筆（description のプレースホルダ残存、"
                            "または summary 領域が空）"))

    # stale（built_from ≠ 現ソースページの集合ハッシュ。A-5）
    if built_from is not None and kg_source is not None:
        stale, decided = _skill_stale(loaded_layers, kg_source, built_from)
        if decided and stale:
            issues.append(Issue("warn", "skill-stale", target,
                                "built_from が現ソースページの集合ハッシュと不一致"
                                "（kg skillgen で再生成し、要約を再執筆する）"))
    return issues


def _skill_stale(loaded_layers, kg_source, built_from):
    """(stale か, 判定できたか)。ソースを解決できない層は判定しない。"""
    from . import skillgen
    kind, _sep, value = kg_source.partition(":")
    for ld in loaded_layers:
        try:
            _topic, members = skillgen.resolve_target(ld.layer, kind, value)
        except KgError:
            continue
        current = {}
        for ref in members:
            page = ld.pages.get(ref)
            if page is None:
                return True, True  # ソースページが消えた
            current[ref] = page.hash
        return hashing.set_hash(current) != built_from, True
    return False, False


def _qmd_version_issues(loaded_layers):
    from . import qmdfacade
    issues = []
    for ld in loaded_layers:
        cfg = ld.config
        if cfg is None or not cfg.qmd_version_range:
            continue
        if not qmdfacade.enabled_by_config([ld.layer]) or qmdfacade.qmd_path() is None:
            continue
        actual = qmdfacade.version()
        if actual is not None and not actual.startswith(cfg.qmd_version_range):
            issues.append(Issue("warn", "qmd-version", f"{ld.layer.kind}:config.yml",
                                f"qmd 実バージョン {actual} が動作確認済みレンジ "
                                f"'{cfg.qmd_version_range}' 外"))
    return issues


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

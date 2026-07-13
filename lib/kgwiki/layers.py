"""層（グローバル/プロジェクト）の解決・走査・マージ（基本設計 03 §2.3）。"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import config as config_mod
from . import pages as pages_mod
from .errors import KgError, UsageError

GLOBAL = "global"
PROJECT = "project"
DEFAULT_GLOBAL_ROOT = "~/kg-wiki"
PROJECT_DIR_NAME = ".kg-wiki"


@dataclass
class Layer:
    kind: str  # "global" | "project"
    root: Path


@dataclass
class LoadedLayer:
    layer: Layer
    config: object = None
    config_issues: list = field(default_factory=list)
    config_exists: bool = False
    pages: dict = field(default_factory=dict)   # ref -> Page
    page_issues: list = field(default_factory=list)


def resolve_global_root(cli_root=None) -> Path:
    """グローバル層 root の解決（03 §2.3 / 04 §1.4 の解決順）。"""
    if cli_root:
        return Path(cli_root).expanduser()
    env = os.environ.get("KG_WIKI_ROOT")
    if env:
        return Path(env).expanduser()
    opt = os.environ.get("CLAUDE_PLUGIN_OPTION_WIKI_ROOT")
    if opt:
        return Path(opt).expanduser()
    return Path(DEFAULT_GLOBAL_ROOT).expanduser()


def find_project_root() -> Path:
    """プロジェクト層 root（無ければ None）。CLAUDE_PROJECT_DIR > 上方探索（03 §2.3）。"""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        candidate = Path(env) / PROJECT_DIR_NAME
        return candidate if candidate.is_dir() else None
    current = Path.cwd()
    for directory in [current, *current.parents]:
        candidate = directory / PROJECT_DIR_NAME
        if candidate.is_dir():
            return candidate
    return None


def select_layers(layer_opt, cli_root=None, for_write=False, quiet=False):
    """--layer の解決。読み取り系の既定 all / 書き込み系の既定は 03 §4.1。

    返り値はマージ優先順を保証するため常に [global, project] の部分列。
    """
    layer_opt = layer_opt or ("" if for_write else "all")
    global_root = resolve_global_root(cli_root)
    project_root = find_project_root()

    if for_write:
        if layer_opt == "all":
            raise UsageError("書き込み系コマンドに --layer all は指定できない")
        if layer_opt == "":
            if project_root is not None:
                if not quiet:
                    print(f"kg: プロジェクト層 {project_root} を対象とする", file=sys.stderr)
                return [Layer(PROJECT, project_root)]
            if not quiet:
                print(f"kg: グローバル層 {global_root} を対象とする", file=sys.stderr)
            return [Layer(GLOBAL, global_root)]

    if layer_opt == "global":
        return [Layer(GLOBAL, global_root)]
    if layer_opt == "project":
        if project_root is None:
            raise KgError("プロジェクト層（.kg-wiki）が見つからない")
        return [Layer(PROJECT, project_root)]
    # all
    result = [Layer(GLOBAL, global_root)]
    if project_root is not None:
        result.append(Layer(PROJECT, project_root))
    elif not for_write and not quiet:
        print("kg: プロジェクト層なし（グローバル層のみで続行）", file=sys.stderr)
    return result


# --- 走査 ---

def fs_topics(root: Path):
    """topics/ 直下のディレクトリ名（辞書順）。"""
    topics_dir = Path(root) / "topics"
    if not topics_dir.is_dir():
        return []
    return sorted(p.name for p in topics_dir.iterdir() if p.is_dir())


def iter_page_paths(root: Path, topic: str):
    """(type_dir, slug, path) を type→slug の辞書順で列挙する。"""
    pages_dir = Path(root) / "topics" / topic / "pages"
    if not pages_dir.is_dir():
        return
    for type_dir in sorted(p.name for p in pages_dir.iterdir() if p.is_dir()):
        d = pages_dir / type_dir
        for md in sorted(p.name for p in d.iterdir()
                         if p.is_file() and p.name.endswith(".md")):
            yield type_dir, md[:-3], d / md


def scan_page_refs(root: Path, topics=None):
    """層内の全ページ ref → path（パース不要の存在スキャン）。"""
    result = {}
    for topic in (topics if topics is not None else fs_topics(root)):
        for type_dir, slug, path in iter_page_paths(root, topic):
            result[f"{topic}/{type_dir}/{slug}"] = path
    return result


def load_layer(layer: Layer, topics=None) -> LoadedLayer:
    """config とページ群をフルパースで読み込む（build / validate 用）。"""
    loaded = LoadedLayer(layer=layer)
    cfg, cfg_issues, exists = config_mod.load_config(layer.root)
    loaded.config, loaded.config_issues, loaded.config_exists = cfg, cfg_issues, exists
    scan_topics = topics
    if scan_topics is None:
        scan_topics = cfg.topic_names() if cfg is not None else fs_topics(layer.root)
    for topic in scan_topics:
        for type_dir, slug, path in iter_page_paths(layer.root, topic):
            page, issues = pages_mod.load_page(path, layer.kind, topic, type_dir, cfg)
            loaded.page_issues.extend(issues)
            if page is not None:
                loaded.pages[page.ref] = page
    return loaded


def page_path(layer: Layer, ref: str) -> Path:
    topic, type_dir, slug = ref.split("/")
    return Path(layer.root) / "topics" / topic / "pages" / type_dir / f"{slug}.md"


def derived_dir(root: Path, topic: str) -> Path:
    return Path(root) / "topics" / topic / "_derived"


# --- index の実行時マージ（03 §2.3） ---

def load_index_records(layer: Layer, topics=None):
    """層の index.jsonl 群を読み込む。{ref: record}。未生成 topic は無視する。"""
    import json

    records = {}
    for topic in (topics if topics is not None else fs_topics(layer.root)):
        path = derived_dir(layer.root, topic) / "index.jsonl"
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and "ref" in rec:
                records[rec["ref"]] = rec
    return records


def merge_index(layer_records):
    """[(kind, {ref: record})] をマージする。(merged, shadow_set)。

    同一 ref はプロジェクト層優先（layer_records は global → project の順）。
    """
    merged = {}
    seen_by_layer = {}
    for kind, records in layer_records:
        seen_by_layer[kind] = set(records)
        merged.update(records)
    shadow = seen_by_layer.get(GLOBAL, set()) & seen_by_layer.get(PROJECT, set())
    return merged, shadow

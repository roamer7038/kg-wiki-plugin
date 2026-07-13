"""config.yml の読み込み・検証・生成（基本設計 03 §2.2）。"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import yamlsub
from .output import Issue

CONFIG_NAME = "config.yml"
TOP_KEYS = {"version", "topics", "types", "relations", "qmd"}
TOPIC_KEYS = {"name", "description"}
QMD_KEYS = {"enabled", "version_range"}
NAME_RE = re.compile(r"^[a-z0-9-]+$")
REL_NAME_RE = re.compile(r"^[a-z0-9_-]+$")

DEFAULT_TYPES = ["concepts", "entities", "articles", "papers", "queries", "decisions"]
DEFAULT_RELATIONS = [
    "is_a", "part_of", "uses", "relates_to",
    "contradicts", "supersedes", "derived_from", "evaluated_by",
]
RESERVED_REL = "mentions"


@dataclass
class Config:
    topics: list = field(default_factory=list)  # [{"name":..., "description":...}]
    types: list = field(default_factory=list)
    relations: list = field(default_factory=list)
    qmd_enabled: bool = False
    qmd_version_range: str = ""

    def topic_names(self):
        return [t["name"] for t in self.topics if isinstance(t, dict) and "name" in t]


def _err(issues, message):
    issues.append(Issue("error", "config-schema", CONFIG_NAME, message, halts=True))


def load_config(root: Path):
    """(Config|None, [Issue], exists) を返す。ファイル不在時は (None, [], False)。"""
    path = Path(root) / CONFIG_NAME
    if not path.is_file():
        return None, [], False
    text = path.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")
    data, yaml_issues = yamlsub.parse_document(text)
    issues: list = []
    for yi in yaml_issues:
        _err(issues, f"L{yi.line}: {yi.message}")

    config = Config()
    for key in data:
        if key not in TOP_KEYS:
            _err(issues, f"未知キー: {key}")

    version = data.get("version")
    if version != 1:
        _err(issues, f"version は 1 であること（現値: {version!r}）")

    topics = data.get("topics")
    if not isinstance(topics, list):
        _err(issues, "topics は必須（マッピングのリスト。空リスト可）")
    else:
        seen = set()
        for item in topics:
            if not isinstance(item, dict):
                _err(issues, "topics の要素はマッピングであること")
                continue
            extra = set(item) - TOPIC_KEYS
            if extra:
                _err(issues, f"topics 要素の未知キー: {', '.join(sorted(extra))}")
            name = item.get("name")
            if not isinstance(name, str) or not NAME_RE.match(name):
                _err(issues, f"topics.name は [a-z0-9-]+ の文字列であること（現値: {name!r}）")
                continue
            if name in seen:
                _err(issues, f"topics.name の重複: {name}")
                continue
            seen.add(name)
            desc = item.get("description")
            if desc is not None and not isinstance(desc, str):
                _err(issues, f"topics.description は文字列であること（topic: {name}）")
            config.topics.append({"name": name, "description": desc})

    types = data.get("types")
    if not isinstance(types, list) or not all(
        isinstance(t, str) and NAME_RE.match(t) for t in types
    ):
        _err(issues, "types は [a-z0-9-]+ 文字列の完全列挙リストであること（必須）")
    else:
        config.types = types

    relations = data.get("relations")
    if not isinstance(relations, list) or not all(
        isinstance(r, str) and REL_NAME_RE.match(r) for r in relations
    ):
        _err(issues, "relations は関係語彙の完全列挙リストであること（必須）")
    else:
        if RESERVED_REL in relations:
            _err(issues, "relations に予約語 mentions は定義できない")
        config.relations = relations

    qmd = data.get("qmd")
    if qmd is not None:
        if not isinstance(qmd, dict):
            _err(issues, "qmd はマッピングであること")
        else:
            extra = set(qmd) - QMD_KEYS
            if extra:
                _err(issues, f"qmd の未知キー: {', '.join(sorted(extra))}")
            enabled = qmd.get("enabled")
            if enabled is not None:
                if not isinstance(enabled, bool):
                    _err(issues, "qmd.enabled は真偽値であること")
                else:
                    config.qmd_enabled = enabled
            version_range = qmd.get("version_range")
            if version_range is not None:
                if not isinstance(version_range, str):
                    _err(issues, "qmd.version_range は文字列であること")
                else:
                    config.qmd_version_range = version_range

    return config, issues, True


def qmd_effectively_enabled(config) -> bool:
    """qmd 有効判定の設定値解決（02 §2.3: 環境変数 > config > 既定 false）。"""
    env = os.environ.get("CLAUDE_PLUGIN_OPTION_ENABLE_QMD")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    return bool(config and config.qmd_enabled)


def initial_config_text(topic_names) -> str:
    """kg init が生成する config.yml（03 §2.2 の初期値・キー順は規範例のとおり）。"""
    lines = ["version: 1"]
    if topic_names:
        lines.append("topics:")
        for name in topic_names:
            lines.append(f"  - name: {name}")
    else:
        lines.append("topics: []")
    lines.append("types: [" + ", ".join(DEFAULT_TYPES) + "]")
    lines.append("relations: [" + ", ".join(DEFAULT_RELATIONS) + "]")
    lines.append("qmd:")
    lines.append("  enabled: false")
    lines.append('  version_range: ""')
    return "\n".join(lines) + "\n"


def add_topics_text(text: str, new_names) -> str:
    """既存 config.yml テキストに topic を追記する（kg init。他行は変更しない）。"""
    lines = text.split("\n")
    entries = [f"  - name: {name}" for name in new_names]
    for i, line in enumerate(lines):
        if line == "topics: []":
            lines[i:i + 1] = ["topics:"] + entries
            return "\n".join(lines)
        if line == "topics:" or line.startswith("topics:"):
            # 既存 topics ブロックの末尾（次のトップレベルキーの直前）に挿入する
            j = i + 1
            while j < len(lines) and (lines[j].startswith("  ") or lines[j].strip() == ""
                                      or lines[j].lstrip().startswith("#")):
                if lines[j].strip() == "" and j + 1 < len(lines) \
                        and not lines[j + 1].startswith("  "):
                    break
                j += 1
            lines[j:j] = entries
            return "\n".join(lines)
    # topics キーが無い（config-schema エラー状態）→ 末尾に追記
    if lines and lines[-1] == "":
        lines = lines[:-1]
    lines += ["topics:"] + entries + [""]
    return "\n".join(lines)

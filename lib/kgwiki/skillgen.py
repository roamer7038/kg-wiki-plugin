"""kg skillgen: Corpus2Skill（基本設計 03 §3.7・§4.14、方式設計 02 §6.7）。

生成物は staging（`topics/<topic>/_derived/skills/<name>/SKILL.md`）に置き、
配置（インストール）と分離する。LLM 執筆領域（description・summary 領域）は
再生成でも保持する（A-5）。配置は必ず人間のゲートを通す（FR-4.2。承認 UI は
CLI ではなく /kg-skillgen スキルの固定手順が担う）。
"""

import difflib
from pathlib import Path

from . import community as community_mod
from . import hashing, layers, output, yamlsub
from .community import parse_community_md as parse_regions
from .errors import KgError, UsageError

SKILL_NAME = "SKILL.md"
LLM_FIELD = "<!-- kg:llm-field -->"
DESCRIPTION_PLACEHOLDER = f"{LLM_FIELD}（LLM 執筆: 発火条件を含む説明）"
FM_KEYS = {"name", "description", "built_from", "kg_source"}
# インストール先の既定。ネスト配置（~/.claude/skills/kg-generated/<name>/）の Skill は
# 発火しないため、フラット配置とする（04 §10 (c) の実機確認）
DEFAULT_DEST = "~/.claude/skills"


def parse_source(text: str):
    """`topic:<topic>` | `community:<id>` を (kind, value) に解析する（03 §4.14）。"""
    kind, _sep, value = text.partition(":")
    if kind not in ("topic", "community") or not value:
        raise UsageError(
            "kg skillgen の対象は topic:<topic> または community:<id> であること: "
            f"{text}")
    return kind, value


def default_name(kind: str, topic: str, value: str) -> str:
    """topic 単位は kg-<topic>、コミュニティ単位は kg-<topic>-<id>（03 §3.7）。"""
    return f"kg-{topic}" if kind == "topic" else f"kg-{topic}-{value}"


def staging_dir(layer, topic: str, name: str) -> Path:
    return layers.derived_dir(layer.root, topic) / "skills" / name


def resolve_target(layer, kind: str, value: str):
    """(topic, members) を返す。members は ref 順のソースページ ref 列。"""
    if kind == "topic":
        topic = value
        records = layers.load_index_records(layer, [topic])
        if not records:
            raise KgError(
                f"topic に index が無い: {topic}（topic 名と kg build を確認する）")
        return topic, sorted(records)

    for topic in layers.fs_topics(layer.root):
        data = community_mod.load_assignment(layers.derived_dir(layer.root, topic))
        if data is None:
            continue
        members = (data.get("communities") or {}).get(value)
        if isinstance(members, list):
            return topic, sorted(members)
    raise KgError(f"コミュニティが見つからない: {value}（kg build を実行する）")


def source_hash(layer, members) -> str:
    """ソースページの集合ハッシュ（built_from。03 §3.7）。"""
    pages = {}
    for ref in members:
        path = layers.page_path(layer, ref)
        if path.is_file():
            pages[ref] = hashing.page_hash(path)
    return hashing.set_hash(pages)


def skill_md_text(name: str, kg_source: str, built_from: str, members, records,
                  description: str, summary_lines) -> str:
    """生成 SKILL.md（骨格 = 生成、description・summary 領域 = 保持。03 §3.7）。"""
    lines = [
        "---",
        f"name: {name}",
        f"description: {yamlsub.dump_scalar(description)}",
        f"built_from: {built_from}",
        f"kg_source: {kg_source}",
        "---",
        "",
    ]
    lines += list(output.TRUST_NOTICE)
    lines += [
        "",
        community_mod.MARK_SK_BEGIN,
        f"## 参照ページ（{len(members)}）",
        "",
    ]
    for ref in members:
        rec = records.get(ref, {})
        lines.append(f"- [[{ref}]] — {rec.get('summary', '')}".rstrip())
    lines += [community_mod.MARK_SK_END, "", community_mod.MARK_SU_BEGIN]
    lines += list(summary_lines or [])
    lines += [community_mod.MARK_SU_END, ""]
    return "\n".join(lines)


def existing_llm_regions(path: Path):
    """既存 staging の LLM 執筆領域 (description, summary_lines)。無ければ既定値。"""
    if not path.is_file():
        return DESCRIPTION_PLACEHOLDER, []
    text = path.read_text(encoding="utf-8")
    fm_lines, _sk, summary, errors = parse_regions(text)
    description = DESCRIPTION_PLACEHOLDER
    if fm_lines is not None:
        data, _issues = yamlsub.parse_mapping_lines(fm_lines, first_lineno=2)
        value = data.get("description")
        if isinstance(value, str) and value:
            description = value
    return description, ([] if errors else summary)


def is_unwritten(description, summary_lines) -> bool:
    """未執筆判定（03 §3.7）: プレースホルダ残存、または summary 領域が空。"""
    if not isinstance(description, str) or LLM_FIELD in description:
        return True
    return not any(line.strip() for line in (summary_lines or []))


def generate(layer, kind: str, value: str, name):
    """staging を生成・更新する。(path, name, topic) を返す。"""
    topic, members = resolve_target(layer, kind, value)
    name = name or default_name(kind, topic, value)
    path = staging_dir(layer, topic, name) / SKILL_NAME
    description, summary = existing_llm_regions(path)
    records = layers.load_index_records(layer, [topic])
    text = skill_md_text(name, f"{kind}:{value}", source_hash(layer, members),
                         members, records, description, summary)
    from . import fsio
    fsio.atomic_write_text(path, text)
    return path, name, topic


def diff_lines(old_text: str, new_text: str, name: str):
    """インストール差分（新規は全文が追加差分）。"""
    return list(difflib.unified_diff(
        old_text.split("\n"), new_text.split("\n"),
        fromfile=f"installed/{name}/{SKILL_NAME}",
        tofile=f"staging/{name}/{SKILL_NAME}", lineterm=""))


def dest_dir(dest) -> Path:
    return Path(dest or DEFAULT_DEST).expanduser()


def install(staged: Path, name: str, dest, dry_run: bool):
    """(diff 行列, 変更したか)。dry_run なら書き込まない（03 §4.14）。"""
    new_text = staged.read_text(encoding="utf-8")
    target = dest_dir(dest) / name / SKILL_NAME
    old_text = target.read_text(encoding="utf-8") if target.is_file() else ""
    diff = diff_lines(old_text, new_text, name)
    if dry_run or not diff:
        return diff, False
    from . import fsio
    fsio.atomic_write_text(target, new_text)
    return diff, True


# --- kg validate --skills（03 §3.7・§4.7） ---

def iter_staging(layer):
    """層内の staging SKILL.md を (topic, name, path) で列挙する。"""
    for topic in layers.fs_topics(layer.root):
        base = layers.derived_dir(layer.root, topic) / "skills"
        if not base.is_dir():
            continue
        for skill_dir in sorted(base.iterdir()):
            path = skill_dir / SKILL_NAME
            if path.is_file():
                yield topic, skill_dir.name, path


def iter_installed(dest):
    """インストール先の kg 由来 Skill を (name, path) で列挙する。

    frontmatter に kg_source を持つものだけを対象とする（手書き Skill は検査しない）。
    """
    base = dest_dir(dest)
    if not base.is_dir():
        return
    for skill_dir in sorted(base.iterdir()):
        path = skill_dir / SKILL_NAME
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        fm_lines, _sk, _su, _errors = parse_regions(text)
        if fm_lines is None:
            continue
        data, _issues = yamlsub.parse_mapping_lines(fm_lines, first_lineno=2)
        if "kg_source" in data:
            yield skill_dir.name, path

"""kg init / kg new。"""

import sys
from pathlib import Path

from . import config as config_mod
from . import fsio, layers, oplog, refs, yamlsub
from .errors import KgError
from .output import Issue

GITIGNORE_TEXT = (
    ".kg-lock\n"
    "topics/*/_derived/*\n"
    "!topics/*/_derived/communities/\n"
    "!topics/*/_derived/skills/\n"
)
TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "templates" / "page.md"


def run_init(layer, topic_names, date, quiet=False) -> bool:
    """冪等な初期化（既存は上書きせず不足のみ補完）。新規作成なら True。"""
    root = Path(layer.root)
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / config_mod.CONFIG_NAME
    created = not config_path.exists()

    def note(msg):
        if not quiet:
            print(f"kg init: {msg}", file=sys.stderr)

    if created:
        fsio.atomic_write_text(config_path, config_mod.initial_config_text(topic_names))
        note(f"config.yml を作成: {config_path}")
    else:
        note("既存 config.yml は変更しない（topic 追記を除く）")
        if topic_names:
            cfg, _issues, _exists = config_mod.load_config(root)
            existing = set(cfg.topic_names()) if cfg is not None else set()
            new_names = [n for n in topic_names if n not in existing]
            if new_names:
                text = config_path.read_text(encoding="utf-8")
                fsio.atomic_write_text(config_path,
                                       config_mod.add_topics_text(text, new_names))
                note(f"topics へ追記: {', '.join(new_names)}")

    log_path = root / oplog.LOG_NAME
    if not log_path.exists():
        fsio.atomic_write_text(log_path, "")
        note("log.md を作成")

    gitignore = root / ".gitignore"
    if not gitignore.exists():
        fsio.atomic_write_text(gitignore, GITIGNORE_TEXT)
        note(".gitignore を作成")

    for name in topic_names:
        pages_dir = root / "topics" / name / "pages"
        if not pages_dir.is_dir():
            pages_dir.mkdir(parents=True, exist_ok=True)
            note(f"topics/{name}/pages/ を作成")

    if created:
        detail = f"topics: {', '.join(topic_names)}" if topic_names else None
        oplog.append(root, oplog.format_line(date, "init", "root", detail))
    return created


def new_page_issues(layer, cfg, ref_text: str):
    """kg new / kg move の事前検証（exit 2 相当の issue 列）。"""
    issues = []
    try:
        ref = refs.parse_ref(ref_text)
    except Exception:
        issues.append(Issue("error", "ref-format", ref_text,
                            "ref が正準形 <topic>/<type>/<slug> でない"))
        return issues, None
    if cfg is None:
        issues.append(Issue("error", "config-schema", f"{layer.kind}:config.yml",
                            "config.yml がない・不正（kg init で初期化する）"))
        return issues, ref
    if ref.topic not in cfg.topic_names():
        issues.append(Issue("error", "topic-undefined", ref_text,
                            f"config 未定義の topic: {ref.topic}"))
    if ref.type not in cfg.types:
        issues.append(Issue("error", "type-undefined", ref_text,
                            f"config 未定義の type: {ref.type}"))
    return issues, ref


def run_new(layer, ref_text: str, title, summary, keywords, date):
    """scaffold 生成。(issues, path)。issues が空でなければ作成しない。"""
    cfg, cfg_issues, exists = config_mod.load_config(layer.root)
    if not exists:
        raise KgError(f"config.yml がない: {layer.root}（kg init で初期化する）")
    if cfg_issues:
        return cfg_issues, None
    issues, ref = new_page_issues(layer, cfg, ref_text)
    if issues:
        return issues, None
    path = layers.page_path(layer, ref_text)
    if path.exists():
        return [Issue("error", "ref-exists", ref_text, f"既存ページと衝突: {path}")], None

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    extra = ""
    if summary:
        extra += f"summary: {yamlsub.dump_scalar(summary)}\n"
    if keywords:
        extra += "keywords: [" + ", ".join(yamlsub.dump_scalar(k) for k in keywords) + "]\n"
    content = (
        template
        .replace("{{title}}", yamlsub.dump_scalar(title if title else ref.slug))
        .replace("{{type}}", ref.type)
        .replace("{{slug}}", ref.slug)
        .replace("{{extra}}", extra)
        .replace("{{updated}}", date.isoformat())
    )
    fsio.atomic_write_text(path, content)
    oplog.append(layer.root, oplog.format_line(date, "new", ref_text))
    return [], path

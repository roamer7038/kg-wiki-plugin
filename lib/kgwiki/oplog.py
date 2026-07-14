"""log.md への追記。

構造操作はスクリプト経由: LLM・スキルによる log.md 直接編集は禁止で、
追記は本モジュール（kg の各書き込みコマンド・kg log）経由に限る。
"""

from pathlib import Path

from . import fsio
from .errors import KgError
from .layers import scan_page_refs

LOG_NAME = "log.md"
# op 一覧。kg log が受け付けるのは ingest のみで、他は各コマンドが
# 自身で記録する
OPS = ("init", "new", "ingest", "move", "skillgen", "skill-install")
LOG_CMD_OP = "ingest"


def format_line(date, op: str, target: str, detail: str = None) -> str:
    """1 操作 1 行の書式: - <YYYY-MM-DD> [<op>] <対象> — <詳細>（詳細は任意）。"""
    line = f"- {date.isoformat() if hasattr(date, 'isoformat') else date} [{op}] {target}"
    if detail:
        line += f" — {detail}"
    return line


def append(root: Path, line: str) -> None:
    path = Path(root) / LOG_NAME
    text = ""
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if text and not text.endswith("\n"):
            text += "\n"
    fsio.atomic_write_text(path, text + line + "\n")


def run_log_ingest(layer_list, refs, source: str, date) -> object:
    """kg log ingest。1 ref = 1 行で追記し、記録先の層（Layer）を返す。

    layer_list はグローバル → プロジェクトの順（両層に存在する場合は
    プロジェクト層に記録する）。

    一括取り込みのため refs は複数可。**全 ref を先に解決してから書く**
    （途中の不在で部分適用しない）。
    """
    if isinstance(refs, str):
        refs = [refs]
    known = [(layer, scan_page_refs(layer.root)) for layer in layer_list]
    resolved = []
    for ref in refs:
        target_layer = None
        for layer, page_refs in known:  # 後勝ち = プロジェクト層優先
            if ref in page_refs:
                target_layer = layer
        if target_layer is None:
            raise KgError(f"ページが両層に不在: {ref}")
        resolved.append((target_layer, ref))
    for target_layer, ref in resolved:
        append(target_layer.root, format_line(date, "ingest", ref, source))
    return resolved[0][0]

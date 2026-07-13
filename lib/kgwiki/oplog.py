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


def run_log_ingest(layer_list, ref: str, source: str, date) -> object:
    """kg log ingest。記録先の層（Layer）を返す。

    layer_list はグローバル → プロジェクトの順（両層に存在する場合は
    プロジェクト層に記録する）。
    """
    target_layer = None
    for layer in layer_list:  # 後勝ち = プロジェクト層優先
        if ref in scan_page_refs(layer.root):
            target_layer = layer
    if target_layer is None:
        raise KgError(f"ページが両層に不在: {ref}")
    append(target_layer.root, format_line(date, "ingest", ref, source))
    return target_layer

"""manifest.json の読み書き（基本設計 03 §3.2）。"""

import json
from pathlib import Path

from . import __version__, fsio, hashing

SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"


def load(derived: Path):
    """manifest を読む。不在・破損は None。"""
    path = Path(derived) / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def is_current(data) -> bool:
    """schema_version / tool_version の一致（不一致は全再生成フォールバック。03 §3.2）。"""
    return (
        data is not None
        and data.get("schema_version") == SCHEMA_VERSION
        and data.get("tool_version") == __version__
    )


def build_manifest(pages_hashes: dict) -> dict:
    """topic のページハッシュ集合から manifest 内容を構築する。"""
    shash = hashing.set_hash(pages_hashes)
    return {
        "derived": {
            "adjacency.json": shash,
            "graph.tsv": shash,
            "index.jsonl": shash,
        },
        "pages": dict(sorted(pages_hashes.items())),
        "schema_version": SCHEMA_VERSION,
        "tool_version": __version__,
    }


def write(derived: Path, data: dict) -> None:
    """キー辞書順・インデント 2・生 UTF-8・末尾改行（03 §3.1）でアトミック書き込み。"""
    text = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    fsio.atomic_write_text(Path(derived) / MANIFEST_NAME, text)

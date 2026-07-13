"""ページハッシュ・集合ハッシュ（基本設計 03 §3.1、詳細設計 04 §11.3）。"""

import hashlib
from pathlib import Path


def page_hash_bytes(data: bytes) -> str:
    """バイト列の SHA-256。返り値 "sha256:<hex64 小文字>"。"""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def page_hash(path: Path) -> str:
    """ファイルのバイト列そのままの SHA-256（03 §3.1）。"""
    return page_hash_bytes(path.read_bytes())


def set_hash(pages: dict) -> str:
    """集合ハッシュ（03 §3.1）。

    対象ページ集合の "<ref>\\t<hex64>" 行（sha256: プレフィクスなし）を ref の
    Unicode 昇順で LF 連結（末尾改行なし）した UTF-8 バイト列の SHA-256。
    引数 pages は {ref: "sha256:<hex64>"}。
    """
    lines = []
    for ref in sorted(pages):
        digest = pages[ref]
        if digest.startswith("sha256:"):
            digest = digest[len("sha256:"):]
        lines.append(f"{ref}\t{digest}")
    joined = "\n".join(lines).encode("utf-8")
    return "sha256:" + hashlib.sha256(joined).hexdigest()

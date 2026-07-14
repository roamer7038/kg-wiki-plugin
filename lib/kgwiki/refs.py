"""ページ参照（ref）の解析・検証。

正準形は <topic>/<type>/<slug>、各要素は [a-z0-9-]+。これ以外の形式は認めない。
"""

import re
from dataclasses import dataclass

from .errors import RefFormatError

# $ は末尾改行の直前にもマッチするため、\Z（文字列末尾）で終端を固定する
SLUG_RE = re.compile(r"^[a-z0-9-]+\Z")
REF_RE = re.compile(r"^([a-z0-9-]+)/([a-z0-9-]+)/([a-z0-9-]+)\Z")


@dataclass(frozen=True)
class Ref:
    topic: str
    type: str
    slug: str

    def __str__(self) -> str:
        return f"{self.topic}/{self.type}/{self.slug}"


def is_canonical(text: str) -> bool:
    """文字列が正準 ref 形式か（構文検査のみ）。"""
    return isinstance(text, str) and REF_RE.match(text) is not None


def parse_ref(text: str) -> Ref:
    """正準 ref を解析する。失敗時は RefFormatError。"""
    if not isinstance(text, str):
        raise RefFormatError(f"ref が文字列でない: {text!r}")
    m = REF_RE.match(text)
    if m is None:
        raise RefFormatError(
            f"ref が正準形 <topic>/<type>/<slug>（各要素 [a-z0-9-]+）でない: {text!r}"
        )
    return Ref(m.group(1), m.group(2), m.group(3))


def is_slug(text: str) -> bool:
    return isinstance(text, str) and SLUG_RE.match(text) is not None

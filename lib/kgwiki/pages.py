"""ページの読み込み・frontmatter スキーマ検証・本文処理。"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import hashing, refs, yamlsub
from .output import Issue

KNOWN_KEYS = {"title", "type", "slug", "summary", "keywords", "relations", "sources", "updated"}
SOURCE_KEYS = {"url", "title", "accessed"}
LINK_RE = re.compile(r"\[\[([^\[\]\n]+)\]\]")
FENCE_RE = re.compile(r"^ {0,3}(```|~~~)")
INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
H1_RE = re.compile(r"^#( |$)")
LIST_RE = re.compile(r"^(?:[-*+] |\d+[.)] )")
# 水平線（CommonMark thematic break）: 同一記号 3 個以上、間の空白は許容
THEMATIC_BREAK_RE = re.compile(
    r"^(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$")
SUMMARY_LIMIT = 120  # コードポイント


@dataclass
class Relation:
    rel: str
    to: str


@dataclass
class Source:
    url: str
    title: str = None
    accessed: date = None


@dataclass
class Page:
    ref: str
    path: Path
    layer: str
    title: str = ""
    type: str = ""
    slug: str = ""
    summary: str = ""
    keywords: list = field(default_factory=list)
    relations: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    updated: date = None
    body: str = ""
    hash: str = ""


def split_frontmatter(text: str):
    """(fm_lines, body, fatal_message) を返す。fatal 時は fm_lines=None（回復不能）。"""
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        return None, "", "frontmatter 開始 '---' がない"
    for i in range(1, len(lines)):
        if lines[i] == "---":
            return lines[1:i], "\n".join(lines[i + 1:]), None
    return None, "", "frontmatter 終了 '---' に到達しない（EOF）"


# --- 本文処理 ---

def body_lines_flags(body: str):
    """本文各行に (行, フェンスコード内か) を付す。フェンス行自体はコード扱い。"""
    result = []
    fence = None
    for line in body.split("\n"):
        m = FENCE_RE.match(line)
        if m:
            if fence is None:
                fence = m.group(1)
                result.append((line, True))
                continue
            if m.group(1) == fence:
                fence = None
                result.append((line, True))
                continue
        result.append((line, fence is not None))
    return result


def mask_inline_code(line: str) -> str:
    """インラインコード区間を同長の空白に置換する（リンク抽出の除外用）。"""
    return INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), line)


def extract_body_links(body: str):
    """本文の [[...]] を出現順に返す（フェンス・インラインコード内は除外）。"""
    links = []
    for line, in_code in body_lines_flags(body):
        if in_code:
            continue
        for m in LINK_RE.finditer(mask_inline_code(line)):
            links.append(m.group(1))
    return links


def body_has_h1(body: str) -> bool:
    return any(
        H1_RE.match(line) for line, in_code in body_lines_flags(body) if not in_code
    )


def extract_summary(body: str) -> str:
    """本文の最初の本文段落行を 120 コードポイントで切り詰めて返す。

    見出し・コードブロック・リスト・引用・表・HTML コメントを除く非空行。
    該当行が無ければ空文字列。
    """
    in_comment = False
    for line, in_code in body_lines_flags(body):
        if in_code:
            continue
        stripped = line.strip()
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if not stripped:
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_comment = True
            continue
        if stripped.startswith(("#", ">", "|")) or LIST_RE.match(stripped):
            continue
        if THEMATIC_BREAK_RE.match(stripped):
            continue
        return stripped[:SUMMARY_LIMIT]
    return ""


# --- スキーマ検証 ---

def _is_str(v) -> bool:
    return isinstance(v, str)


def _coerce_scalar_str(v):
    """yamlsub の型推論で int/bool/date になった値を元の文字列表現に戻す。

    title/slug/type/keywords は「文字列であること」で検証されるため、
    `slug: 2024` や `title: true` のような正当値が型推論で非文字列になると
    build を止めてしまう。ここで文字列へ正規化して悪影響を防ぐ。
    dict/list などスカラー以外はそのまま返す（呼び出し側で型検証する）。
    """
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def _err(issues, code, target, message, halts=True):
    issues.append(Issue("error", code, target, message, halts=halts))


def _warn(issues, code, target, message):
    issues.append(Issue("warn", code, target, message))


def load_page(path: Path, layer_kind: str, topic: str, type_dir: str, config):
    """ページファイルを読み込み検証する。(Page|None, [Issue]) を返す。

    Page はパース不能（fatal）の場合のみ None。スキーマ違反があっても、判明した
    フィールドを持つ Page を返す（issues の halts で build 中断を判断する）。
    """
    path = Path(path)
    slug_from_name = path.name[:-3] if path.name.endswith(".md") else path.name
    ref = f"{topic}/{type_dir}/{slug_from_name}"
    issues: list = []

    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n")  # 規約は LF。CRLF は寛容に読む
    fm_lines, body, fatal = split_frontmatter(text)
    if fatal is not None:
        _err(issues, "fm-parse", ref, fatal)
        return None, issues

    data, yaml_issues = yamlsub.parse_mapping_lines(fm_lines, first_lineno=2)
    for yi in yaml_issues:
        _err(issues, "fm-parse", ref, f"L{yi.line}: {yi.message}")

    # 文字列であるべきキーは型推論の巻き添えを外し、生の文字列表現へ正規化する。
    # （updated / sources.accessed の日付など他キーには触れない）
    for key in ("title", "type", "slug"):
        if key in data:
            data[key] = _coerce_scalar_str(data[key])
    if isinstance(data.get("keywords"), list):
        data["keywords"] = [_coerce_scalar_str(k) for k in data["keywords"]]

    page = Page(ref=ref, path=path, layer=layer_kind, body=body,
                hash=hashing.page_hash_bytes(raw))

    for key in data:
        if key not in KNOWN_KEYS:
            _err(issues, "fm-schema", ref, f"未知キー: {key}")

    # title
    title = data.get("title")
    if title is None:
        _err(issues, "fm-schema", ref, "title は必須")
    elif not _is_str(title) or title == "":
        _err(issues, "fm-schema", ref, "title は空でない文字列であること")
    else:
        page.title = title

    # type
    ptype = data.get("type")
    if ptype is None:
        _err(issues, "fm-schema", ref, "type は必須")
    elif not _is_str(ptype):
        _err(issues, "fm-schema", ref, "type は文字列であること")
    else:
        page.type = ptype
        if ptype != type_dir:
            _err(issues, "type-mismatch", ref,
                 f"type '{ptype}' が親ディレクトリ '{type_dir}' と一致しない")
        elif config is not None and ptype not in config.types:
            _err(issues, "type-mismatch", ref,
                 f"type '{ptype}' は config の types に未定義")

    # slug
    slug = data.get("slug")
    if slug is None:
        _err(issues, "fm-schema", ref, "slug は必須")
    elif not refs.is_slug(slug):
        _err(issues, "fm-schema", ref, "slug は [a-z0-9-]+ であること")
    else:
        page.slug = slug
        if slug != slug_from_name:
            _err(issues, "slug-mismatch", ref,
                 f"slug '{slug}' がファイル名 '{slug_from_name}' と一致しない")

    # summary
    summary = data.get("summary")
    if summary is not None:
        if not _is_str(summary):
            _err(issues, "fm-schema", ref, "summary は文字列であること")
        else:
            page.summary = summary
    if not page.summary:
        page.summary = extract_summary(body)

    # keywords
    keywords = data.get("keywords")
    if keywords is not None:
        if not isinstance(keywords, list) or not all(_is_str(k) for k in keywords):
            _err(issues, "fm-schema", ref, "keywords は文字列リストであること")
        else:
            page.keywords = keywords
            seen = set()
            for k in keywords:
                if k in seen:
                    _warn(issues, "keywords-duplicate", ref, f"keywords の重複: {k}")
                seen.add(k)

    # relations
    relations = data.get("relations")
    if relations is not None:
        if not isinstance(relations, list):
            _err(issues, "fm-schema", ref, "relations はマッピングのリストであること")
        else:
            seen_pairs = set()
            for item in relations:
                if not isinstance(item, dict):
                    _err(issues, "fm-schema", ref, "relations の要素はマッピングであること")
                    continue
                extra = set(item) - {"rel", "to"}
                if extra:
                    _err(issues, "fm-schema", ref,
                         f"relations 要素の未知キー: {', '.join(sorted(extra))}")
                rel = item.get("rel")
                to = item.get("to")
                ok = True
                if not _is_str(rel):
                    _err(issues, "fm-schema", ref, "relations 要素に rel（文字列）が必要")
                    ok = False
                elif rel == "mentions":
                    _err(issues, "rel-undefined", ref,
                         "mentions は本文リンク専用の予約語（frontmatter では使用不可）")
                elif config is not None and rel not in config.relations:
                    _err(issues, "rel-undefined", ref, f"config 未定義の rel: {rel}")
                if not _is_str(to):
                    _err(issues, "fm-schema", ref, "relations 要素に to（文字列）が必要")
                    ok = False
                elif not refs.is_canonical(to):
                    _err(issues, "ref-format", ref,
                         f"relations.to が正準形でない: {to}")
                    ok = False
                elif to == ref:
                    _err(issues, "rel-self", ref, "自己参照 relation は不可")
                    ok = False
                if ok and _is_str(rel):
                    if (rel, to) in seen_pairs:
                        _warn(issues, "rel-duplicate", ref, f"重複 relation: ({rel}, {to})")
                    seen_pairs.add((rel, to))
                    page.relations.append(Relation(rel, to))

    # sources
    sources = data.get("sources")
    if sources is not None:
        if not isinstance(sources, list):
            _err(issues, "fm-schema", ref, "sources はマッピングのリストであること")
        else:
            for item in sources:
                if not isinstance(item, dict):
                    _err(issues, "fm-schema", ref, "sources の要素はマッピングであること")
                    continue
                extra = set(item) - SOURCE_KEYS
                if extra:
                    _err(issues, "fm-schema", ref,
                         f"sources 要素の未知キー: {', '.join(sorted(extra))}")
                url = item.get("url")
                if not _is_str(url):
                    _err(issues, "fm-schema", ref, "sources 要素に url（文字列）が必要")
                    continue
                stitle = item.get("title")
                if stitle is not None and not _is_str(stitle):
                    _err(issues, "fm-schema", ref, "sources.title は文字列であること")
                accessed = item.get("accessed")
                if accessed is not None and not isinstance(accessed, date):
                    _err(issues, "fm-schema", ref,
                         "sources.accessed は ISO 日付（YYYY-MM-DD）であること")
                page.sources.append(Source(url, stitle if _is_str(stitle) else None,
                                           accessed if isinstance(accessed, date) else None))

    # updated
    updated = data.get("updated")
    if updated is None:
        _err(issues, "fm-schema", ref, "updated は必須")
    elif not isinstance(updated, date):
        _err(issues, "fm-schema", ref, "updated は ISO 日付（YYYY-MM-DD）であること")
    else:
        page.updated = updated

    return page, issues


def normalize_text(s: str) -> str:
    """検索用正規化: Unicode NFC + ASCII のみ小文字化。"""
    s = unicodedata.normalize("NFC", s)
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in s)

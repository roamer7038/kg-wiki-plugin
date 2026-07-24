"""Markdown サブセット → HTML（05 §4）。純関数・依存なし。

対応範囲は 05 §4.1 が規範。範囲外の記法は解釈せずエスケープして
原文のまま出力する（レンダラの網羅性不足が可読性の破綻に直結しない）。
"""

import html
import re

_HEADING_RE = re.compile(r"^(#{1,4}) +(.*)$")
_HR_RE = re.compile(r"^-{3,}$")
_BULLET_RE = re.compile(r"^(\s*)[-*] +(.*)$")
_ORDERED_RE = re.compile(r"^(\s*)\d+\. +(.*)$")
_TABLE_SEP_RE = re.compile(r"^\|[\s:|-]+\|$")


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def render(md_text: str, resolve) -> str:
    """md 本文 → HTML。resolve(ref) -> (href, label, ok)。"""
    lines = md_text.replace("\r\n", "\n").split("\n")
    state = {"heading_no": 0}
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            i, block = _take_fence(lines, i)
            out.append(block)
            continue
        if not line.strip():
            i += 1
            continue
        m = _HEADING_RE.match(line)
        if m:
            state["heading_no"] += 1
            level = min(max(len(m.group(1)), 2), 4)
            out.append('<h{0} id="sec-{1}">{2}</h{0}>'.format(
                level, state["heading_no"], inline(m.group(2), resolve)))
            i += 1
            continue
        if _HR_RE.match(line.strip()):
            out.append("<hr>")
            i += 1
            continue
        if _is_table(lines, i):
            i, block = _take_table(lines, i, resolve)
            out.append(block)
            continue
        if _BULLET_RE.match(line) or _ORDERED_RE.match(line):
            i, block = _take_list(lines, i, resolve)
            out.append(block)
            continue
        i, block = _take_paragraph(lines, i, resolve)
        out.append(block)
    return "\n".join(out)


def _take_fence(lines, i):
    i += 1
    code = []
    while i < len(lines) and not lines[i].startswith("```"):
        code.append(lines[i])
        i += 1
    i += 1  # 閉じフェンス（EOF でも進める）
    return i, "<pre><code>" + esc("\n".join(code)) + "</code></pre>"


def _is_table(lines, i):
    return (lines[i].startswith("|") and i + 1 < len(lines)
            and _TABLE_SEP_RE.match(lines[i + 1].strip()) is not None)


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _take_table(lines, i, resolve):
    header = _cells(lines[i])
    i += 2  # ヘッダ行 + 区切り行
    body = []
    while i < len(lines) and lines[i].startswith("|"):
        body.append(_cells(lines[i]))
        i += 1
    head_html = "".join("<th>%s</th>" % inline(c, resolve) for c in header)
    rows = "".join(
        "<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c, resolve) for c in row)
        for row in body)
    return i, ("<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>"
               % (head_html, rows))


def _take_list(lines, i, resolve):
    """インデント 2 段までのリスト。ネストは 2 スペース単位で判定する。"""
    items = []          # [(depth, tag, text)]
    tag = "ol" if _ORDERED_RE.match(lines[i]) else "ul"
    while i < len(lines):
        m = _BULLET_RE.match(lines[i]) or _ORDERED_RE.match(lines[i])
        if m is None:
            break
        depth = min(len(m.group(1)) // 2, 1)
        items.append((depth, m.group(2)))
        i += 1
    return i, _render_items(items, tag, resolve)


def _render_items(items, tag, resolve):
    out = []
    idx = 0
    while idx < len(items):
        depth, text = items[idx]
        idx += 1
        children = []
        while idx < len(items) and items[idx][0] > depth:
            children.append((items[idx][0] - 1, items[idx][1]))
            idx += 1
        body = inline(text, resolve)
        if children:
            body += _render_items(children, "ul", resolve)
        out.append("<li>%s</li>" % body)
    return "<%s>%s</%s>" % (tag, "".join(out), tag)


def _take_paragraph(lines, i, resolve):
    buf = []
    while i < len(lines) and lines[i].strip():
        if (lines[i].startswith("```") or _HEADING_RE.match(lines[i])
                or _BULLET_RE.match(lines[i]) or _ORDERED_RE.match(lines[i])
                or _HR_RE.match(lines[i].strip()) or _is_table(lines, i)):
            break
        buf.append(lines[i].strip())
        i += 1
    return i, "<p>%s</p>" % inline(" ".join(buf), resolve)


def inline(text: str, resolve) -> str:
    """Task 2 で実装する。現時点はエスケープのみ。"""
    return esc(text)

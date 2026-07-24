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
        if not line.strip():
            i += 1
            continue
        if not _is_block_start(lines, i):
            i, block = _take_paragraph(lines, i, resolve)
            out.append(block)
            continue
        if line.startswith("```"):
            i, block = _take_fence(lines, i)
            out.append(block)
            continue
        m = _HEADING_RE.match(line)
        if m:
            state["heading_no"] += 1
            level = min(max(len(m.group(1)), 2), 4)
            out.append('<h{0} id="sec-{1}">{2}</h{0}>'.format(
                level, state["heading_no"], inline(m.group(2).strip(), resolve)))
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
        # 残る分岐はリスト（_is_block_start が True のケースの最後の候補）
        i, block = _take_list(lines, i, resolve)
        out.append(block)
    return "\n".join(out)


def _is_block_start(lines, i):
    """行 i が段落ではなく別ブロック（フェンス／見出し／水平線／テーブル／リスト）の
    開始かどうか。render() の分岐と _take_paragraph() の終端判定の両方で使う。
    """
    line = lines[i]
    return (line.startswith("```") or _HEADING_RE.match(line) is not None
            or _HR_RE.match(line.strip()) is not None or _is_table(lines, i)
            or _BULLET_RE.match(line) is not None
            or _ORDERED_RE.match(line) is not None)


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
    """インデント 2 段までの連続するリスト行を全て集める。
    マーカー種別（- / * ↔ 1.）が変わっても打ち切らない（打ち切りは、
    リスト行そのものが途切れたときのみ）。構造化・タグ分けは
    _render_runs 側の責務。
    """
    items = []  # [(depth, marker, text)]
    while i < len(lines):
        m = _BULLET_RE.match(lines[i])
        marker = "ul"
        if m is None:
            m = _ORDERED_RE.match(lines[i])
            marker = "ol"
        if m is None:
            break
        depth = min(len(m.group(1)) // 2, 1)
        items.append((depth, marker, m.group(2)))
        i += 1
    # トップレベルの連は別ブロックとして "\n" で区切る
    # （test_marker_change_starts_new_list の既存仕様）。
    return i, "\n".join(_render_runs(items, resolve))


def _render_runs(items, resolve):
    """items（先頭要素と同じ深さの兄弟、およびその子孫）を、深さごと・
    マーカー種別ごとの連（run）に分割し、連ごとに <ul> または <ol> を
    1 つ出す（05 §4.1）。返り値は連ごとの HTML 文字列のリスト。
    子リストは直前の <li> の中に、連同士の区切りなしで並べて入る。
    """
    depth = items[0][0]
    runs = []
    idx = 0
    while idx < len(items):
        run_marker = items[idx][1]
        run = []
        while (idx < len(items) and items[idx][0] == depth
               and items[idx][1] == run_marker):
            _d, _marker, text = items[idx]
            idx += 1
            children = []
            while idx < len(items) and items[idx][0] > depth:
                child_depth, child_marker, child_text = items[idx]
                children.append((child_depth - 1, child_marker, child_text))
                idx += 1
            body = inline(text, resolve)
            if children:
                body += "".join(_render_runs(children, resolve))
            run.append("<li>%s</li>" % body)
        runs.append("<%s>%s</%s>" % (run_marker, "".join(run), run_marker))
    return runs


def _take_paragraph(lines, i, resolve):
    buf = []
    while i < len(lines) and lines[i].strip():
        if _is_block_start(lines, i):
            break
        buf.append(lines[i].strip())
        i += 1
    return i, "<p>%s</p>" % inline(" ".join(buf), resolve)


def inline(text: str, resolve) -> str:
    """Task 2 で実装する。現時点はエスケープのみ。"""
    return esc(text)

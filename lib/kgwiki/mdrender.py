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

ALLOWED_SCHEMES = ("http://", "https://", "mailto:")

_INLINE_RE = re.compile(
    r"(?P<code>`[^`\n]+`)"
    r"|(?P<wiki>\[\[[a-z0-9-]+/[a-z0-9-]+/[a-z0-9-]+\]\])"
    r"|(?P<link>\[[^\[\]\n]+\]\([^)\s]*\))"
    r"|(?P<strong>\*\*[^*\n]+\*\*)"
    r"|(?P<em>\*[^*\n]+\*)")


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def render(md_text: str, resolve) -> str:
    """md 本文 → HTML。resolve(ref) -> (href, label, ok)。"""
    lines = md_text.replace("\r\n", "\n").split("\n")
    heading_no = 0
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
            heading_no += 1
            level = min(max(len(m.group(1)), 2), 4)
            out.append('<h{0} id="sec-{1}">{2}</h{0}>'.format(
                level, heading_no, inline(m.group(2).strip(), resolve)))
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
        # 深さは 0/1 の 2 段階に丸める。05 §4.1 は「インデント 2 段まで」
        # としか定めておらず 3 段以上の扱いは仕様上未規定のため、3 段以上の
        # インデントも一律で深さ 1 として扱う（意図的な割り切り）。
        depth = min(len(m.group(1)) // 2, 1)
        items.append((depth, marker, m.group(2)))
        i += 1
    # 先頭項目の深さを 0 に正規化する（それ以外の項目は相対化するだけで、
    # 通常どおり先頭が深さ 0 のときは無変更）。字下げされた行からリストが
    # 始まる（先頭項目の深さが 1）と、正規化しない場合は後続の深さ 0 の
    # 項目が _render_runs のどの分岐（同じ深さの兄弟／基準より深い子）にも
    # 一致せず idx が進まなくなる（無限ループ）。正規化により「items の
    # どの要素も先頭要素の深さ以上」という不変条件が常に成立し、
    # _render_runs 側の前進が構造的に保証される。
    if items and items[0][0] != 0:
        base = items[0][0]
        items = [(max(0, d - base), mk, t) for d, mk, t in items]
    # トップレベルの連は別ブロックとして "\n" で区切る
    # （test_marker_change_starts_new_list の既存仕様）。
    return i, "\n".join(_render_runs(items, resolve))


def _render_runs(items, resolve):
    """items（先頭要素と同じ深さの兄弟、およびその子孫）を、深さごと・
    マーカー種別ごとの連（run）に分割し、連ごとに <ul> または <ol> を
    1 つ出す（05 §4.1）。返り値は連ごとの HTML 文字列のリスト。
    子リストは直前の <li> の中に、連同士の区切りなしで並べて入る。

    不変条件: items のどの要素の深さも items[0][0]（＝ depth）以上である。
    これはトップレベル呼び出しでは _take_list が正規化して保証し、
    再帰呼び出し（children）では、深さが 0/1 の 2 段階にしか丸められない
    ため children は必ず全要素が depth+1（相対化後は 0）になることで自動的に
    保証される。この不変条件があるので、外側 while の各周回は
    「items[idx] は depth と同じ（run に追加）」か「depth より深い（内側の
    子リスト収集ループで消費）」のどちらかに必ず該当し、idx は毎周回で
    必ず 1 つ以上進む（depth より浅い項目が紛れ込んで idx が進まなくなる
    ケースは構造上あり得ない）。
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
    """インライン記法を処理する。

    左から非重複で走査し、確定した区間は再処理しない（05 §4.1）。
    代替の順序がそのまま優先順位: コードスパン → wikilink → リンク → 強調。
    """
    out = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        out.append(esc(text[pos:m.start()]))
        kind = m.lastgroup
        raw = m.group()
        if kind == "code":
            out.append("<code>%s</code>" % esc(raw[1:-1]))
        elif kind == "wiki":
            out.append(_wikilink(raw[2:-2], resolve))
        elif kind == "link":
            out.append(_link(raw))
        elif kind == "strong":
            out.append("<strong>%s</strong>" % esc(raw[2:-2]))
        else:
            out.append("<em>%s</em>" % esc(raw[1:-1]))
        pos = m.end()
    out.append(esc(text[pos:]))
    return "".join(out)


def _wikilink(ref, resolve):
    href, label, ok = resolve(ref)
    cls = "" if ok else ' class="broken"'
    return '<a%s href="%s">%s</a>' % (cls, esc(href), esc(label))


def _link(raw):
    label, _, url = raw[1:-1].partition("](")
    if not url.startswith(ALLOWED_SCHEMES):
        return esc(raw)          # リンク化せず原文表示（05 §8）
    return '<a href="%s">%s</a>' % (esc(url), esc(label))

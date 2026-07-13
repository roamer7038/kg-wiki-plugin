"""kg pack: コンテキストパックの生成（基本設計 03 §4.13、詳細設計 04 §7）。

本文を返す例外的なコマンド（A-7）。信頼境界の注意書きを機械的に付与する（03 §6.4）。
バイト計上は「固定部 + ページブロック列 + 省略部」に分解し、各部は先頭に空行を持たず
末尾に空行を持つ（04 §7.1。部の連結がそのまま出力となり、計上が独立する）。
"""

from . import config as config_mod
from . import layers as layers_mod
from . import output
from . import pages as pages_mod
from . import refs as refs_mod
from . import search as search_mod
from . import traverse as traverse_mod

OMIT_HEADING = "## 省略（--max-bytes 超過）"
# ref 列形式では近傍の件数上限を設けない（--limit は query 形式の上位 M 件に効く）
NEIGHBOR_LIMIT = 10 ** 9


def block_bytes(lines) -> int:
    """行列（各行 LF 終端）の UTF-8 バイト長（04 §7.1）。"""
    return len("".join(line + "\n" for line in lines).encode("utf-8"))


def is_ref_form(args) -> bool:
    """位置引数がすべて正準形 ref なら ref 列形式（03 §4.13）。"""
    return bool(args) and all(refs_mod.is_canonical(a) for a in args)


def collect(args, layer_list, topics, hops: int, limit: int):
    """収集規則（03 §4.13）。(ref 順の ref 列, merged_index) を返す。

    missing ノード（両層の index に無い ref）は収集対象から除外する。
    """
    out, inn, _nodes, merged, _shadow = traverse_mod.load_merged_graph(
        layer_list, topics)
    if is_ref_form(args):
        collected = set()
        for ref in args:
            collected.add(ref)
            for row in traverse_mod.bfs(out, inn, ref, hops, "both", None):
                collected.add(row[0])
    else:
        hits = search_mod.run_search(" ".join(args), layer_list, topics, limit,
                                     no_body=False)
        collected = {rec["ref"] for _score, rec in hits}
    return sorted(ref for ref in collected if ref in merged), merged


def fixed_lines(refs) -> list:
    """固定部 = 注意書き 2 行 + 目次（収集された全 ref）。末尾に空行（04 §7.1）。"""
    lines = list(output.TRUST_NOTICE)
    lines += ["", f"## 収載ページ（{len(refs)}）", ""]
    lines += [f"- [[{ref}]]" for ref in refs]
    lines.append("")
    return lines


def source_line(source) -> str:
    """`- <url>`（+ ` — <title>`）（+ `（accessed: <date>）`）。04 §7.1。"""
    line = f"- {source.url}"
    if source.title:
        line += f" — {source.title}"
    if source.accessed:
        line += f"（accessed: {source.accessed.isoformat()}）"
    return line


def page_lines(page) -> list:
    """ページブロック（04 §7.1）。sources 節・本文節は空なら出力しない。"""
    updated = page.updated.isoformat() if page.updated else ""
    lines = [f"## [[{page.ref}]] — {page.title}（updated: {updated}）", ""]
    if page.sources:
        lines += ["### sources", ""]
        lines += [source_line(s) for s in page.sources]
        lines.append("")
    body = page.body.strip("\n")
    if body.strip():
        lines += body.split("\n")
        lines.append("")
    return lines


def omit_lines(refs) -> list:
    """省略部（末尾の空行を持たない。04 §7.1）。"""
    return [OMIT_HEADING] + [f"- [[{ref}]]" for ref in refs]


def select(refs, sizes, fixed_size: int, max_bytes):
    """採否の逐次貪欲（04 §7.2）。(kept, omitted) を ref 順で返す。

    running = 固定部 + 省略部見出し（常時予約）から開始し、ref 順に
    「running + ページブロック ≤ B なら採用、超えるなら省略して省略行を計上」。
    """
    if max_bytes is None:
        return list(refs), []
    running = fixed_size + block_bytes([OMIT_HEADING])
    kept, omitted = [], []
    for ref in refs:
        size = sizes[ref]
        if running + size <= max_bytes:
            kept.append(ref)
            running += size
        else:
            omitted.append(ref)
            running += block_bytes([f"- [[{ref}]]"])
    return kept, omitted


def load_pages(refs, merged, layer_list):
    """収集 ref のページを読み込む。{ref: Page}（読めないページは除外）。"""
    layer_by_kind = {layer.kind: layer for layer in layer_list}
    configs = {}
    result = {}
    for ref in refs:
        layer = layer_by_kind.get(merged[ref].get("layer"))
        if layer is None:
            continue
        if layer.kind not in configs:
            configs[layer.kind] = config_mod.load_config(layer.root)[0]
        topic, type_dir, _slug = ref.split("/")
        path = layers_mod.page_path(layer, ref)
        if not path.is_file():
            continue
        page, _issues = pages_mod.load_page(path, layer.kind, topic, type_dir,
                                            configs[layer.kind])
        if page is not None:
            result[ref] = page
    return result


def run_pack(args, layer_list, topics, hops: int, limit: int, max_bytes):
    """(text, omitted, over_budget) を返す。text は出力全体（LF 終端）。

    収集対象が 0 件なら text=None（呼び出し側が exit 1。03 §4.13）。
    """
    refs, merged = collect(args, layer_list, topics, hops, limit)
    pages = load_pages(refs, merged, layer_list)
    refs = [ref for ref in refs if ref in pages]
    if not refs:
        return None, [], False

    head = fixed_lines(refs)
    fixed_size = block_bytes(head)
    blocks = {ref: page_lines(pages[ref]) for ref in refs}
    sizes = {ref: block_bytes(blocks[ref]) for ref in refs}

    kept, omitted = select(refs, sizes, fixed_size, max_bytes)

    lines = list(head)
    for ref in kept:
        lines += blocks[ref]
    if omitted:
        lines += omit_lines(omitted)
    text = "".join(line + "\n" for line in lines)

    over_budget = (max_bytes is not None
                   and len(text.encode("utf-8")) > max_bytes)
    return text, omitted, over_budget

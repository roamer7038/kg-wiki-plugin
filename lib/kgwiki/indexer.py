"""index.jsonl / index.md の生成（基本設計 03 §3.3）。"""

from . import output


def page_record(page) -> dict:
    """Page → index.jsonl レコード（03 §3.3 の全キー）。"""
    return {
        "hash": page.hash,
        "keywords": list(page.keywords),
        "layer": page.layer,
        "ref": page.ref,
        "summary": page.summary,
        "title": page.title,
        "type": page.type,
        "updated": page.updated.isoformat() if page.updated is not None else "",
    }


def index_jsonl_text(records: dict) -> str:
    """{ref: record} → JSONL（ref 順・1 行 1 レコード・末尾改行）。空なら空文字列。"""
    lines = [output.jsonl(records[ref]) for ref in sorted(records)]
    return "".join(line + "\n" for line in lines)


def index_md_text(topic: str, records: dict) -> str:
    """index.jsonl から人間用 index.md を整形生成する（03 §3.3）。"""
    header = (
        f"# index: {topic}（{len(records)} ページ）\n"
        "<!-- 自動生成: kg build。手編集禁止 -->\n"
    )
    if not records:
        return header
    lines = []
    for ref in sorted(records):
        rec = records[ref]
        line = f"- [[{ref}]] — {rec.get('summary', '')}"
        keywords = rec.get("keywords") or []
        if keywords:
            line += " | kw: " + ", ".join(keywords)
        lines.append(line.rstrip())
    return header + "\n" + "".join(line + "\n" for line in lines)

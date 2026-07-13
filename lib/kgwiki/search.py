"""kg search: 語彙検索（BM25 不使用）。"""

from . import layers as layers_mod
from . import output
from . import pages as pages_mod

# CJK 判定ブロック（追加ブロックは採らない）
CJK_RANGES = (
    (0x3040, 0x309F),  # ひらがな
    (0x30A0, 0x30FF),  # カタカナ
    (0x4E00, 0x9FFF),  # CJK 統合漢字
    (0x3400, 0x4DBF),  # 拡張 A
)
FIELD_WEIGHTS = (("title", 3.0), ("keywords", 2.0), ("summary", 1.0))
GREP_PER_LINE = 0.5
GREP_MAX_LINES = 5
EXACT_FACTOR = 2.0
ALL_TERMS_BONUS = 2.0


def is_cjk_term(term: str) -> bool:
    return any(any(lo <= ord(c) <= hi for lo, hi in CJK_RANGES) for c in term)


def bigrams(term: str):
    return {term[i:i + 2] for i in range(len(term) - 1)}


def _match_one(term: str, text: str) -> float:
    """項 × 単一フィールド文字列の生一致点 m（完全一致は呼び出し側）。"""
    if not text:
        return 0.0
    if is_cjk_term(term) and len(term) >= 2:
        grams = bigrams(term)
        hit = sum(1 for g in grams if g in text)
        return hit / len(grams)
    return 1.0 if term in text else 0.0


def term_field_score(term: str, field_value, weight: float) -> float:
    """項スコア候補 w × m。field_value は文字列（title/summary）または
    文字列リスト（keywords。完全一致はリスト要素単位）。"""
    if isinstance(field_value, list):
        m = 0.0
        for element in field_value:
            if term == element:
                m = max(m, EXACT_FACTOR)
            else:
                m = max(m, _match_one(term, element))
    else:
        if term == field_value:
            m = EXACT_FACTOR
        else:
            m = _match_one(term, field_value)
    return weight * m


def index_score(terms, norm_fields) -> tuple:
    """(ページスコア, 全項一致か)。norm_fields = {"title": str, "keywords": [str], "summary": str}"""
    total = 0.0
    all_matched = True
    for term in terms:
        best = 0.0
        for name, weight in FIELD_WEIGHTS:
            best = max(best, term_field_score(term, norm_fields[name], weight))
        if best <= 0.0:
            all_matched = False
        total += best
    if terms and all_matched:
        total *= ALL_TERMS_BONUS
    return total, all_matched


def grep_bonus(terms, body_norm_lines) -> float:
    bonus = 0.0
    for term in terms:
        n = sum(1 for line in body_norm_lines if term in line)
        bonus += min(n, GREP_MAX_LINES) * GREP_PER_LINE
    return bonus


def _norm(s: str) -> str:
    return pages_mod.normalize_text(s)


def _body_norm_lines(layer_roots, record):
    """レコードの属する層のページ本文を正規化行リストで返す（無ければ空）。"""
    root = layer_roots.get(record.get("layer"))
    if root is None:
        return []
    try:
        text = layers_mod.page_path(layers_mod.Layer(record["layer"], root),
                                    record["ref"]).read_text(encoding="utf-8",
                                                             errors="replace")
    except OSError:
        return []
    _fm, body, fatal = pages_mod.split_frontmatter(text.replace("\r\n", "\n"))
    if fatal is not None:
        body = text
    return [_norm(line) for line in body.split("\n")]


def run_search(query: str, layer_list, topics, limit: int, no_body: bool):
    """検索を実行し [(score, record)] をスコア降順 → ref 昇順で返す。"""
    terms = [_norm(t) for t in query.split() if t]
    if not terms:
        return []
    layer_records = [(ly.kind, layers_mod.load_index_records(ly, topics))
                     for ly in layer_list]
    merged, _shadow = layers_mod.merge_index(layer_records)
    layer_roots = {ly.kind: ly.root for ly in layer_list}

    hits = []
    for ref in sorted(merged):
        rec = merged[ref]
        norm_fields = {
            "title": _norm(rec.get("title", "")),
            "keywords": [_norm(k) for k in rec.get("keywords") or []],
            "summary": _norm(rec.get("summary", "")),
        }
        score, _all = index_score(terms, norm_fields)
        if not no_body:
            lines = _body_norm_lines(layer_roots, rec)
            if lines:
                score += grep_bonus(terms, lines)
        if score > 0.0:
            hits.append((score, rec))
    hits.sort(key=lambda h: (-h[0], h[1]["ref"]))
    return hits[:limit]


def format_hit(score, rec) -> str:
    return output.hit_line(output.fmt_score(score), rec["ref"],
                           rec.get("title", ""), rec.get("summary", ""))


def hit_record(score, rec) -> dict:
    data = dict(rec)
    data["score"] = output.score_json(score)
    return data

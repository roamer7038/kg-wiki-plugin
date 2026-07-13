"""コミュニティ検出（CNM 貪欲法）と kg community コマンド（02 §4.1、03 §3.6・§4.12、04 §5）。

決定論規約: ΔQ は浮動小数を使わず整数比較キー 2m×W − K×K で評価し（A-17）、
タイブレークは最小 ref の辞書順ペア。ID 継承の Jaccard 比較は Fraction で厳密に行う。
"""

import hashlib
import json
import re
from fractions import Fraction
from pathlib import Path

from . import hashing, layers
from .errors import KgError

ALGORITHM = "cnm-v1"
ASSIGNMENT_SCHEMA_VERSION = 1
MARK_SK_BEGIN = "<!-- kg:skeleton:begin -->"
MARK_SK_END = "<!-- kg:skeleton:end -->"
MARK_SU_BEGIN = "<!-- kg:summary:begin -->"
MARK_SU_END = "<!-- kg:summary:end -->"


# --- 検出（04 §5.1） ---

def build_weights(edges, member_refs):
    """topic 内グラフの無向重み {(a, b): 行数}（a < b、自己エッジ除外。03 §3.4）。

    トピック横断エッジ・非ページ端点はコミュニティ検出の対象外（02 §4.1、
    member_refs = その topic の index に載る全 ref）。
    """
    weights = {}
    for from_ref, _rel, to_ref, _src in edges:
        if from_ref == to_ref:
            continue
        if from_ref in member_refs and to_ref in member_refs:
            a, b = (from_ref, to_ref) if from_ref < to_ref else (to_ref, from_ref)
            weights[(a, b)] = weights.get((a, b), 0) + 1
    return weights


def detect(weights):
    """CNM 貪欲法。[[member_ref, ...]（ref 順）]（コミュニティは最小 ref 順）。

    孤立ノード（エッジ 0）は weights に現れないため最初から除外される（04 §5.1）。
    """
    nodes = sorted({n for pair in weights for n in pair})
    if not nodes:
        return []
    index = {n: i for i, n in enumerate(nodes)}
    m = sum(weights.values())
    members = {i: {n} for i, n in enumerate(nodes)}
    min_ref = {i: n for i, n in enumerate(nodes)}
    degree = {i: 0 for i in members}
    inter = {}  # (i, j) i<j -> W_uv
    for (a, b), wt in weights.items():
        i, j = sorted((index[a], index[b]))
        inter[(i, j)] = inter.get((i, j), 0) + wt
        degree[i] += wt
        degree[j] += wt

    while True:
        best = None  # (dq, tie_pair, i, j)
        for (i, j), wuv in inter.items():
            if wuv <= 0:
                continue  # W=0 のペアは ΔQ~ < 0 のため走査不要
            dq = 2 * m * wuv - degree[i] * degree[j]
            tie = tuple(sorted((min_ref[i], min_ref[j])))
            if best is None or dq > best[0] or (dq == best[0] and tie < best[1]):
                best = (dq, tie, i, j)
        if best is None or best[0] <= 0:
            break
        _dq, _tie, i, j = best
        # j を i へマージ（04 §5.1 手順 3: K_uv = K_u + K_v、W_(uv)x = W_ux + W_vx）
        members[i] |= members.pop(j)
        min_ref[i] = min(min_ref[i], min_ref.pop(j))
        degree[i] += degree.pop(j)
        new_inter = {}
        for (a, b), wt in inter.items():
            if j in (a, b):
                other = b if a == j else a
                if other == i:
                    continue  # 内部化したエッジは W から消える
                a, b = (i, other) if i < other else (other, i)
            new_inter[(a, b)] = new_inter.get((a, b), 0) + wt
        inter = new_inter

    result = [sorted(s) for s in members.values()]
    result.sort(key=lambda c: c[0])
    return result


def community_id(members) -> str:
    """ID 導出（04 §5.2）: 所属 ref を昇順 LF 連結した UTF-8 の sha256 先頭 8 桁。"""
    digest = hashlib.sha256("\n".join(sorted(members)).encode("utf-8")).hexdigest()
    return f"c-{digest[:8]}"


def assign_ids(communities, old_assignment):
    """ID 継承（04 §5.3）: Jaccard ≥ 1/2 の旧コミュニティから貪欲マッチングで継承。

    communities は detect() の返り値。{index: id} を返す。
    """
    old = {}
    if isinstance(old_assignment, dict):
        raw = old_assignment.get("communities")
        if isinstance(raw, dict):
            old = {k: set(v) for k, v in raw.items() if isinstance(v, list)}
    candidates = []
    for old_id, old_set in old.items():
        for idx, members in enumerate(communities):
            new_set = set(members)
            intersection = len(old_set & new_set)
            union = len(old_set | new_set)
            if union == 0 or 2 * intersection < union:
                continue  # Jaccard < 0.5
            candidates.append((-Fraction(intersection, union), old_id, members[0], idx))
    candidates.sort()
    ids = {}
    used_old = set()
    for _negj, old_id, _minref, idx in candidates:
        if old_id in used_old or idx in ids:
            continue  # 旧 ID は高々 1 回
        used_old.add(old_id)
        ids[idx] = old_id
    for idx, members in enumerate(communities):
        if idx not in ids:
            ids[idx] = community_id(members)
    return ids


# --- 派生物（03 §3.6） ---

def assignment_data(communities, ids) -> dict:
    return {
        "algorithm": ALGORITHM,
        "communities": {ids[idx]: list(members)
                        for idx, members in enumerate(communities)},
        "schema_version": ASSIGNMENT_SCHEMA_VERSION,
    }


def assignment_json_text(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def load_assignment(derived: Path):
    path = Path(derived) / "communities" / "assignment.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def parse_community_md(text: str):
    """(fm_lines, skeleton_lines, summary_lines, errors) に分解する。

    マーカーは 4 行の完全一致文字列（03 §3.6）。欠落・重複・順序違反は errors。
    """
    lines = text.split("\n")
    errors = []
    positions = {}
    for marker in (MARK_SK_BEGIN, MARK_SK_END, MARK_SU_BEGIN, MARK_SU_END):
        found = [i for i, line in enumerate(lines) if line == marker]
        if len(found) != 1:
            errors.append(f"マーカー {marker} が {len(found)} 個（1 個であること）")
        positions[marker] = found[0] if len(found) == 1 else None
    if not errors:
        order = [positions[m] for m in (MARK_SK_BEGIN, MARK_SK_END,
                                        MARK_SU_BEGIN, MARK_SU_END)]
        if order != sorted(order):
            errors.append("マーカーの順序が不正")
    fm_lines = None
    if lines and lines[0] == "---":
        for i in range(1, len(lines)):
            if lines[i] == "---":
                fm_lines = lines[1:i]
                break
    if fm_lines is None:
        errors.append("frontmatter がない")
    if errors:
        return fm_lines, [], [], errors
    skeleton = lines[positions[MARK_SK_BEGIN] + 1:positions[MARK_SK_END]]
    summary = lines[positions[MARK_SU_BEGIN] + 1:positions[MARK_SU_END]]
    return fm_lines, skeleton, summary, errors


def summary_region(text: str):
    """既存 md の summary 領域（LLM 執筆領域）。無ければ None。"""
    _fm, _sk, summary, errors = parse_community_md(text)
    if errors:
        return None
    return summary


def members_hash(members, records) -> str:
    """所属ページの集合ハッシュ（built_from。03 §3.6）。"""
    return hashing.set_hash({ref: records[ref]["hash"] for ref in members
                             if ref in records})


def community_md_text(topic, cid, members, records, edges, existing_summary) -> str:
    """コミュニティ要約 md（骨格 = 生成、summary 領域 = 保持。03 §3.6）。"""
    member_set = set(members)
    rel_counts = {}
    for from_ref, rel, to_ref, _src in edges:
        if from_ref in member_set and to_ref in member_set and from_ref != to_ref:
            rel_counts[rel] = rel_counts.get(rel, 0) + 1

    lines = [
        "---",
        f"community: {cid}",
        f"topic: {topic}",
        f"built_from: {members_hash(members, records)}",
        "---",
        "",
        MARK_SK_BEGIN,
        f"## 所属ページ（{len(members)}）",
        "",
    ]
    for ref in sorted(members):
        rec = records.get(ref, {})
        lines.append(f"- [[{ref}]] — {rec.get('summary', '')}".rstrip())
    lines += ["", "## 内部関係", ""]
    if rel_counts:
        lines += ["| rel | 件数 |", "|---|---|"]
        lines += [f"| {rel} | {rel_counts[rel]} |" for rel in sorted(rel_counts)]
    else:
        lines.append("（内部関係なし）")
    lines += [MARK_SK_END, "", MARK_SU_BEGIN]
    lines += list(existing_summary or [])
    lines += [MARK_SU_END, ""]
    return "\n".join(lines)


# --- kg community コマンド（03 §4.12） ---

def _find_assignment(layer_list, topic):
    """topic の assignment を持つ層を global → project 順で列挙する。"""
    found = []
    for layer in layer_list:
        data = load_assignment(layers.derived_dir(layer.root, topic))
        if data is not None:
            found.append((layer, data))
    return found

def locate_community(layer_list, ref: str):
    """ref の所属コミュニティ (layer, cid, members)。プロジェクト層優先。"""
    topic = ref.split("/")[0]
    result = None
    for layer, data in _find_assignment(layer_list, topic):
        for cid, members in (data.get("communities") or {}).items():
            if isinstance(members, list) and ref in members:
                result = (layer, cid, members)  # 後勝ち = プロジェクト層優先
    return result


def run_community_ref(ref: str, layer_list, topics):
    """<ref> 指定モード。(cid, layer, members, summary_lines|None, stale) を返す。"""
    topic = ref.split("/")[0]
    if topics is not None and topic not in topics:
        raise KgError(f"--topic の指定に {topic} が含まれない")
    located = locate_community(layer_list, ref)
    if located is None:
        if not _find_assignment(layer_list, topic):
            raise KgError(f"assignment.json が未生成: topic {topic}（kg build を実行）")
        raise KgError(f"ref が assignment に未収載: {ref}（build 後に追加されたページ。"
                      "kg build を実行）")
    layer, cid, members = located
    md_path = layers.derived_dir(layer.root, topic) / "communities" / f"{cid}.md"
    summary = None
    stale = False
    if md_path.is_file():
        text = md_path.read_text(encoding="utf-8")
        summary = summary_region(text)
        m = re.search(r"^built_from: (sha256:[0-9a-f]{64})$", text, re.MULTILINE)
        current = {}
        for member in members:
            page = layers.page_path(layer, member)
            if page.is_file():
                current[member] = hashing.page_hash(page)
            else:
                stale = True
        if m is None or hashing.set_hash(current) != m.group(1):
            stale = True
    else:
        stale = True
    return cid, layer, sorted(members), summary, stale


def run_community_query(query: str, layer_list, topics, limit: int):
    """--query 指定モード。[(count, cid, topic, member_count)] を件数降順 → id 昇順で返す。"""
    from . import search
    hits = search.run_search(query, layer_list, topics, limit, no_body=False)
    counts = {}
    for _score, rec in hits:
        located = locate_community(layer_list, rec["ref"])
        if located is None:
            continue
        _layer, cid, members = located
        topic = rec["ref"].split("/")[0]
        key = (cid, topic, len(members))
        counts[key] = counts.get(key, 0) + 1
    result = [(count, cid, topic, size)
              for (cid, topic, size), count in counts.items()]
    result.sort(key=lambda r: (-r[0], r[1]))
    return result

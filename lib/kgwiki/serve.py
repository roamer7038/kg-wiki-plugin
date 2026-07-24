"""kg serve: ローカル・読み取り専用の Web ビューワ（05）。

HTTP に触れるのは §6 のアダプタのみ。検索・グラフ・層マージのロジックは
既存モジュールに委譲し、本モジュールでは再実装しない（05 §5.1）。
"""

import re
from dataclasses import dataclass, field
from urllib.parse import quote

from . import graph as graph_mod
from . import hashing
from . import layers as layers_mod
from . import manifest as manifest_mod
from . import mdrender
from . import output as output_mod
from . import pages as pages_mod
from . import refs as refs_mod
from . import search as search_mod
from . import traverse as traverse_mod
from . import views


@dataclass
class ViewContext:
    layer_list: list
    topics: list = None


def load_merged_index(ctx):
    layer_records = [(ly.kind, layers_mod.load_index_records(ly, ctx.topics))
                     for ly in ctx.layer_list]
    return layers_mod.merge_index(layer_records)


def find_page(ctx, ref):
    """ref → (layer, path)。プロジェクト層優先（DR-2）。無ければ (None, None)。"""
    found = (None, None)
    for layer in ctx.layer_list:            # select_layers は global→project 順
        path = layers_mod.page_path(layer, ref)
        if path.is_file():
            found = (layer, path)
    return found


def page_state(layer, ref, path):
    """05 §6.2 の 4 状態のうち、当該ページの状態を返す。"""
    topic = ref.split("/")[0]
    derived = layers_mod.derived_dir(layer.root, topic)
    data = manifest_mod.load(derived)
    if not manifest_mod.is_current(data):
        return "unbuilt"
    recorded = (data.get("pages") or {}).get(ref)
    if recorded is None:
        return "new"
    return "ok" if recorded == hashing.page_hash(path) else "stale"


def backlinks(ctx, ref):
    """自ページを参照している (rel, from_ref) の一覧。辞書順。"""
    out, inn, _nodes, _index, _shadow = traverse_mod.load_merged_graph(
        ctx.layer_list, ctx.topics)
    rows = [(rel, other)
            for rel, other, direction in graph_mod.get_neighbors(
                out, inn, ref, direction="in")
            if direction == "in"]
    return sorted(set(rows))


def topic_stats(ctx):
    """ホーム用のトピック統計（05 §3.2）。

    ref 単位で重複を除去する（層マージ相当。shadow は 1 回のみ数える）。
    プロジェクト層優先（DR-2）は layer_list の走査順（global→project）に
    委ね、後勝ちの上書きで採用する。未 build のトピックも表示するため
    ファイルシステム走査は維持し、index には頼らない。
    """
    topic_names = set()
    entries = {}  # ref -> (topic, type_dir, layer, path)
    for layer in ctx.layer_list:
        topics = ctx.topics if ctx.topics is not None else layers_mod.fs_topics(layer.root)
        topic_names.update(topics)
        for topic in topics:
            for type_dir, slug, path in layers_mod.iter_page_paths(layer.root, topic):
                ref = "%s/%s/%s" % (topic, type_dir, slug)
                entries[ref] = (topic, type_dir, layer, path)

    stats = {name: {"topic": name, "count": 0, "types": {}, "stale": 0}
              for name in topic_names}
    for ref, (topic, type_dir, layer, path) in entries.items():
        entry = stats[topic]
        entry["count"] += 1
        entry["types"][type_dir] = entry["types"].get(type_dir, 0) + 1
        if page_state(layer, ref, path) != "ok":
            entry["stale"] += 1
    return [stats[name] for name in sorted(stats)]


@dataclass
class Response:
    status: int
    content_type: str
    body: bytes
    headers: dict = field(default_factory=dict)


SLUG = r"[a-z0-9-]+"
MAX_LIMIT = 100
DEFAULT_LIMIT = 20
RECENT_LIMIT = 20


def _by_updated_desc_ref_asc(records):
    """`updated` 降順 → `ref` 昇順の 2 段階ソート（05 §3.2 / §3.3）。

    reverse=True を tuple キーへ一括適用すると ref まで降順になってしまうため、
    安定ソートを利用して ref 昇順 → updated 降順の順に 2 回に分けて適用する。
    """
    rows = sorted(records, key=lambda r: r["ref"])
    rows.sort(key=lambda r: r.get("updated", ""), reverse=True)
    return rows


def _html(body, status=200):
    return Response(status, "text/html; charset=utf-8", body.encode("utf-8"))


def _one(query, key, default=""):
    values = query.get(key) or []
    return values[0] if values else default


def route(method, path, query, ctx):
    if method != "GET":
        return _html(views.error_page(
            "405 Method Not Allowed",
            "このビューワは読み取り専用で、GET のみを受け付ける。"), 405)
    for pattern, handler in ROUTES:
        m = pattern.match(path)
        if m:
            return handler(ctx, query, *m.groups())
    if path.startswith("/p/") or path.startswith("/t/"):
        return _html(views.error_page(
            "400 Bad Request",
            "ref は正準形 <topic>/<type>/<slug>（文字集合 [a-z0-9-]）でなければならない。"),
            400)
    return _html(views.error_page("404 Not Found", "そのページは存在しない。"), 404)


def _style(ctx, query):
    return Response(200, "text/css; charset=utf-8", views.STYLE.encode("utf-8"))


def _home(ctx, query):
    merged, _shadow = load_merged_index(ctx)
    recent = _by_updated_desc_ref_asc(list(merged.values()))[:RECENT_LIMIT]
    return _html(views.home(topic_stats(ctx), recent))


def _topic_unbuilt(ctx, name):
    """05 §6.2: topic 単位の未 build 判定。mtime は使わず manifest を照合する。

    対象層のいずれかで topic ディレクトリが存在し、かつそこの
    _derived/manifest.json が無い、または is_current() が偽なら未 build。
    """
    for layer in ctx.layer_list:
        if name not in layers_mod.fs_topics(layer.root):
            continue
        data = manifest_mod.load(layers_mod.derived_dir(layer.root, name))
        if not manifest_mod.is_current(data):
            return True
    return False


def _topic(ctx, query, name):
    merged, _shadow = load_merged_index(ctx)
    type_filter = _one(query, "type")
    groups = {}
    for ref in sorted(merged):
        rec = merged[ref]
        topic, type_dir, _slug = ref.split("/")
        if topic != name:
            continue
        if type_filter and type_dir != type_filter:
            continue
        groups.setdefault(type_dir, []).append(rec)
    if not groups and name not in {s["topic"] for s in topic_stats(ctx)}:
        return _html(views.error_page(
            "404 Not Found", "トピック %s は対象層に存在しない。" % name), 404)
    for type_dir in groups:
        groups[type_dir] = _by_updated_desc_ref_asc(groups[type_dir])
    banners = []
    if _topic_unbuilt(ctx, name):
        banners.append(("unbuilt", "このトピックは未 build。"
                                   "検索と被リンクは利用できない（kg build を実行）。"))
    return _html(views.topic(name, groups, type_filter, banners))


def _resolver(merged):
    def resolve(ref):
        rec = merged.get(ref)
        if rec is None:
            slug = ref.split("/")[-1]
            return ("/search?q=" + quote(slug), ref, False)
        return ("/p/" + ref, rec.get("title") or ref, True)
    return resolve


def _page(ctx, query, topic, type_dir, slug):
    ref = "%s/%s/%s" % (topic, type_dir, slug)
    if not refs_mod.is_canonical(ref):
        return _html(views.error_page("400 Bad Request", "ref が正準形でない。"), 400)
    layer, path = find_page(ctx, ref)
    merged, shadow = load_merged_index(ctx)
    if layer is None:
        # 05 §6.2「削除済み」: index には残っているが md が無い
        deleted = " なお、このページは index には残っている（kg build で解消する）。" \
            if ref in merged else ""
        hits = search_mod.run_search(slug, ctx.layer_list, ctx.topics, 5, True)
        rows = "".join(views.hit_row(output_mod.fmt_score(s), r["ref"],
                                     r.get("title", ""), r.get("summary", ""),
                                     r.get("layer", ""))
                       for s, r in hits)
        extra = "<h3>近いページ</h3>%s" % (rows or "<p>該当なし。</p>")
        return _html(views.error_page(
            "404 Not Found",
            "ページ %s は未作成。`kg new %s` で作成できる。%s" % (ref, ref, deleted),
            extra), 404)

    try:
        page_obj, issues = pages_mod.load_page(
            path, layer.kind, topic, type_dir, None)
    except OSError:
        # find_page() が is_file() を確認した後の TOCTOU（削除・権限変更等）。
        # frontmatter パース不能は load_page が例外ではなく (None, issues) を
        # 返す契約なので、ここで捕捉するのはファイル読み取り自体の失敗のみ。
        # 想定外の例外は伝播させる（500 への変換は HTTP アダプタの責務。05 §3.6）。
        page_obj, issues = None, []
    resolve = _resolver(merged)
    banners = []
    state = page_state(layer, ref, path)
    if state == "unbuilt":
        banners.append(("unbuilt", "このトピックは未 build。"
                                   "検索と被リンクは利用できない（kg build を実行）。"))
    elif state in ("stale", "new"):
        banners.append(("stale", "本文は最新だが、被リンクと検索は前回 build 時点の内容"
                                 "（kg build を実行すると解消する）。"))
    if ref in shadow:
        banners.append(("shadow", "このページはプロジェクト層の内容を表示している"
                                  "（グローバル層の同名ページを隠している）。"))
    if page_obj is None:
        text = path.read_text(encoding="utf-8", errors="replace")
        banners.append(("error", "frontmatter を解析できない。"
                                 "kg validate で詳細を確認すること。"))
        data = _fallback_view(ref, layer.kind, text, banners, resolve)
        return _html(views.page(data))
    if issues:
        banners.append(("error", "frontmatter に問題がある: "
                        + "、".join(i.code for i in issues)))
    return _html(views.page(_page_view(ctx, page_obj, layer, banners,
                                       merged, resolve)))


def _link_tuple(ref, merged, resolve):
    href, label, ok = resolve(ref)
    rec = merged.get(ref) or {}
    return (href, label, rec.get("summary", ""), ok)


def _page_view(ctx, page_obj, layer, banners, merged, resolve):
    relations = {}
    for rel in page_obj.relations:
        relations.setdefault(rel.rel, []).append(
            _link_tuple(rel.to, merged, resolve))
    back = {}
    for rel, from_ref in backlinks(ctx, page_obj.ref):
        back.setdefault(rel, []).append(_link_tuple(from_ref, merged, resolve))
    return {
        "title": page_obj.title or page_obj.ref,
        "type": page_obj.type,
        "updated": str(page_obj.updated or ""),
        "summary": page_obj.summary or "",
        "layer": layer.kind,
        "banners": banners,
        "body_html": mdrender.render(page_obj.body, resolve),
        "relations": relations,
        "backlinks": back,
        "keywords": page_obj.keywords or [],
        "sources": [(s.title, s.url) for s in page_obj.sources or []],
    }


def _fallback_view(ref, layer_kind, text, banners, resolve):
    return {
        "title": ref, "type": "", "updated": "", "summary": "",
        "layer": layer_kind, "banners": banners,
        "body_html": mdrender.render(text, resolve),
        "relations": {}, "backlinks": {}, "keywords": [], "sources": [],
    }


def _search(ctx, query):
    q = _one(query, "q").strip()
    if not q:
        return Response(302, "text/html; charset=utf-8", b"",
                        {"Location": "/"})
    try:
        limit = min(int(_one(query, "limit", str(DEFAULT_LIMIT))), MAX_LIMIT)
    except ValueError:
        limit = DEFAULT_LIMIT
    topics = ctx.topics
    topic_param = _one(query, "topic")
    if topic_param:
        topics = [t for t in topic_param.split(",") if t]
    layer_param = _one(query, "layer")
    if layer_param in (layers_mod.GLOBAL, layers_mod.PROJECT):
        # ctx.layer_list は select_layers 済みの確定リストから絞り込むのみ。
        # select_layers は再度呼ばない（05 §5.1 は既存 API の再利用を要求する）。
        layer_list = [ly for ly in ctx.layer_list if ly.kind == layer_param]
    else:
        # "all" もそれ以外の不正な値も既定（全層）にフォールバックする。
        layer_list = ctx.layer_list
    hits = search_mod.run_search(q, layer_list, topics, limit, False)
    type_filter = _one(query, "type")
    if type_filter:
        hits = [(s, r) for s, r in hits if r.get("type") == type_filter]
    rows = [(output_mod.fmt_score(s), r["ref"], r.get("title", ""),
             r.get("summary", ""), r.get("layer", "")) for s, r in hits]
    return _html(views.search_results(q, rows, len(rows)))


ROUTES = [
    (re.compile(r"^/$"), _home),
    (re.compile(r"^/style\.css$"), _style),
    (re.compile(r"^/search$"), _search),
    (re.compile(r"^/t/(%s)$" % SLUG), _topic),
    (re.compile(r"^/p/(%s)/(%s)/(%s)$" % (SLUG, SLUG, SLUG)), _page),
]

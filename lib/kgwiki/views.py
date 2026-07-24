"""画面 HTML の生成（05 §3）。純関数のみ。

すべてのページ由来文字列は esc() を通す（05 §8）。JavaScript と
外部ホストへの参照は出力しない（NFR-9）。

引数の型：以下の関数では引数が 2 種類に分かれる。
- テキスト型（esc() で自動エスケープ）：layout の title/query、banner の message、
  hit_row の全引数、layer_badge の layer
- HTML 型（呼び出し側が安全性を保証）：layout の body
"""

from .mdrender import ALLOWED_SCHEMES, esc

STYLE = """
:root { color-scheme: light dark; }
body { font-family: system-ui, sans-serif; line-height: 1.7;
       max-width: 48rem; margin: 0 auto; padding: 1rem; }
header.site { display: flex; gap: 1rem; align-items: baseline;
              border-bottom: 1px solid #8884; padding-bottom: .5rem; }
header.site a { font-weight: bold; text-decoration: none; }
form.search { margin-left: auto; }
a.broken { color: #c00; text-decoration: line-through dotted; }
.badge { font-size: .75rem; border: 1px solid #8888; border-radius: .25rem;
         padding: 0 .3rem; vertical-align: middle; }
.banner { border-left: 4px solid #888; background: #8881;
          padding: .5rem .75rem; margin: .75rem 0; }
.banner.stale, .banner.unbuilt { border-color: #d90; }
.banner.error { border-color: #c00; }
.hit { margin: .75rem 0; }
.hit .score { color: #888; font-variant-numeric: tabular-nums; }
.meta { color: #888; font-size: .875rem; }
table { border-collapse: collapse; }
th, td { border: 1px solid #8884; padding: .25rem .5rem; }
pre { background: #8881; padding: .75rem; overflow-x: auto; }
ul.rel { list-style: none; padding-left: 0; }
ul.rel li { margin: .25rem 0; }
"""


def layout(title, body, query=""):
    """ページレイアウト（HTML 骨組み＋サイト共通部品）。

    Args:
        title: ページタイトル（テキスト型）。自動的に esc() されます。
        body: ページ本文（HTML 型）。呼び出し側が安全性を保証した HTML 断片を渡してください。
              ページやユーザー由来の生テキストを直接渡さないこと（esc() を通すこと）。
        query: 検索フォームの初期値（テキスト型）。デフォルト ""。自動的に esc() されます。

    Returns:
        完全な HTML ドキュメント。
    """
    return (
        "<!doctype html>\n"
        '<html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>%s — kg-wiki</title><style>%s</style></head><body>"
        '<header class="site"><a href="/">kg-wiki</a>'
        '<form class="search" action="/search" method="get">'
        '<input type="search" name="q" value="%s" placeholder="検索">'
        "<button>検索</button></form></header>\n"
        "<main>%s</main></body></html>\n"
        % (esc(title), STYLE, esc(query), body))


def layer_badge(layer):
    """レイヤーを示すバッジ要素。

    Args:
        layer: レイヤー名（テキスト型）。自動的に esc() されます。

    Returns:
        <span class="badge">...</span> HTML 片。
    """
    return '<span class="badge">%s</span>' % esc(layer)


def banner(kind, message):
    """警告・エラーなどのバナー要素。

    Args:
        kind: バナー種別（CSS クラス名）（テキスト型）。自動的に esc() されます。
              例："stale", "unbuilt", "error"
        message: メッセージテキスト（テキスト型）。自動的に esc() されます。

    Returns:
        <div class="banner ...">...</div> HTML 片。
    """
    return '<div class="banner %s">%s</div>' % (esc(kind), esc(message))


def home(topics, recent):
    """ホーム画面（05 §3.2）。

    Args:
        topics: トピック統計の辞書のリスト（テキスト型。各要素は内部で esc() されます）。
                serve.topic_stats() の戻り値の形。キー: "topic"（トピック名）、
                "count"（ページ数）、"types"（{type_dir: 件数}）、
                "stale"（未 build / 変更ありページ数）。
        recent: 最近更新されたページの辞書のリスト（テキスト型）。
                キー: "ref"、"title"（無ければ ref で代替）、"updated"。

    Returns:
        完全な HTML ドキュメント（layout() 済み）。
    """
    rows = []
    for stat in topics:
        types = "、".join("%s %d" % (esc(t), n)
                          for t, n in sorted(stat["types"].items()))
        warn = ""
        if stat["stale"]:
            warn = ' <span class="meta">（未 build / 変更あり %d 件）</span>' % stat["stale"]
        rows.append('<li><a href="/t/%s">%s</a> — %d ページ'
                    '<div class="meta">%s</div>%s</li>'
                    % (esc(stat["topic"]), esc(stat["topic"]),
                       stat["count"], types, warn))
    recent_html = "".join(
        '<li><a href="/p/%s">%s</a> <span class="meta">%s</span></li>'
        % (esc(r["ref"]), esc(r.get("title") or r["ref"]),
           esc(r.get("updated", "")))
        for r in recent)
    body = ("<h2>トピック</h2><ul>%s</ul>"
            "<h2>最近更新されたページ</h2><ul>%s</ul>"
            % ("".join(rows), recent_html))
    return layout("ホーム", body)


def topic(name, groups, type_filter="", banners=None):
    """トピック一覧画面（05 §3.3）。

    Args:
        name: トピック名（テキスト型）。自動的に esc() されます。
        groups: {type_dir: [rec, ...]}（テキスト型。各 rec のキーは内部で esc() されます）。
                rec のキー: "ref"、"title"（無ければ ref で代替）、"layer"、
                "summary"、"updated"。
        type_filter: 絞り込み中の型（テキスト型）。指定時のみ案内文を表示します。
        banners: (kind, message) タプルのリスト（テキスト型。banner() へ渡されます）。
                 05 §6.2 の未 build バナー等に使う。デフォルト None（バナーなし）。

    Returns:
        完全な HTML ドキュメント（layout() 済み）。
    """
    banners_html = "".join(banner(kind, message) for kind, message in (banners or []))
    parts = []
    for type_dir in sorted(groups):
        parts.append("<h3>%s</h3><ul>" % esc(type_dir))
        for rec in groups[type_dir]:
            parts.append(
                '<li><a href="/p/%s">%s</a> %s'
                '<div class="meta">%s — %s</div></li>'
                % (esc(rec["ref"]), esc(rec.get("title") or rec["ref"]),
                   layer_badge(rec.get("layer", "")),
                   esc(rec.get("summary", "")), esc(rec.get("updated", ""))))
        parts.append("</ul>")
    head = "<h2>%s</h2>" % esc(name)
    if type_filter:
        head += '<p class="meta">型 %s で絞り込み中 — <a href="/t/%s">全て表示</a></p>' % (
            esc(type_filter), esc(name))
    return layout(name, banners_html + head + "".join(parts))


def page(data):
    """ページ画面（05 §3.4）。data のキーは serve._page_view() が組み立てる。

    Args:
        data: 以下のキーを持つ辞書。
            title, type, updated, summary, layer, keywords: テキスト型（esc() されます）。
            banners: (kind, message) タプルのリスト（テキスト型。banner() へ渡されます）。
            body_html: **HTML 型**。mdrender.render() の戻り値で、呼び出し側
                       （serve._page_view() / mdrender）が安全性を保証済み。
                       ここではエスケープしません。
            relations, backlinks: {rel: [(href, label, summary, ok), ...]}。
                                   _rel_section() に渡す（要素の意味は同関数の docstring 参照）。
            sources: [(title, url), ...]（テキスト型）。url は http/https/mailto の
                     いずれかのスキームのときのみ <a href> 化し、それ以外は
                     リンク化せずエスケープしたテキストとして表示する（05 §8）。

    Returns:
        完全な HTML ドキュメント（layout() 済み）。
    """
    parts = [banner(kind, message) for kind, message in data["banners"]]
    parts.append("<h2>%s %s</h2>" % (esc(data["title"]), layer_badge(data["layer"])))
    parts.append('<p class="meta">%s / %s</p>'
                 % (esc(data["type"]), esc(data["updated"])))
    if data["summary"]:
        parts.append("<p>%s</p>" % esc(data["summary"]))
    parts.append('<article>%s</article>' % data["body_html"])
    parts.append(_rel_section("関係", data["relations"]))
    parts.append(_rel_section("被リンク", data["backlinks"]))
    if data["keywords"]:
        parts.append('<p class="meta">キーワード: %s</p>'
                     % esc("、".join(data["keywords"])))
    if data["sources"]:
        items = []
        for t, u in data["sources"]:
            if u.startswith(ALLOWED_SCHEMES):
                items.append('<li><a href="%s" rel="noreferrer">%s</a></li>'
                             % (esc(u), esc(t or u)))
            else:
                items.append("<li>%s</li>" % esc(t or u))
        parts.append("<h3>出典</h3><ul>%s</ul>" % "".join(items))
    return layout(data["title"], "".join(parts))


def _rel_section(heading, groups):
    """関係／被リンクの一覧（05 §3.4）。groups は rel ごとにグルーピング済み。

    Args:
        heading: セクション見出し（テキスト型）。自動的に esc() されます。
        groups: {rel: [(href, label, summary, ok), ...]}。rel はテキスト型
                （esc() されます）。各タプルの要素（全てテキスト型・esc() されます）:
                    href: リンク先 URL（resolve() の戻り値。/p/... または /search?q=...）。
                    label: リンクの表示ラベル（相手ページのタイトル）。
                    summary: 相手ページの 1 行要約。
                    ok: bool。False のとき <a class="broken"> を付す（index に
                        存在しない ref へのリンク、05 §3.4）。

    グループの並び順: `mentions` を除いて辞書順、`mentions` は存在すれば
    常に最後に置く（05 §3.4「mentions は別グループとして最後に置く」）。

    Returns:
        <h3>...</h3><h4>...</h4><ul class="rel">...</ul>... の HTML 片。
        groups が空なら空文字列。
    """
    if not groups:
        return ""
    order = sorted(rel for rel in groups if rel != "mentions")
    if "mentions" in groups:
        order.append("mentions")
    parts = ["<h3>%s</h3>" % esc(heading)]
    for rel in order:
        items = "".join(
            '<li><a%s href="%s">%s</a> <span class="meta">%s</span></li>'
            % ("" if ok else ' class="broken"', esc(href), esc(label), esc(summary))
            for href, label, summary, ok in groups[rel])
        parts.append("<h4>%s</h4><ul class=\"rel\">%s</ul>" % (esc(rel), items))
    return "".join(parts)


def search_results(q, hits, total):
    """検索結果画面（05 §3.5）。

    Args:
        q: 検索クエリ（テキスト型）。自動的に esc() されます。検索フォームの
           初期値としても使う（layout() の query 引数）。
        hits: hit_row() へそのまま展開する 5 要素タプルのリスト（テキスト型）。
              (score_text, ref, title, summary, layer)。
        total: 件数（見出しに表示するのみ。テキスト化せず %d で埋め込む）。

    Returns:
        完全な HTML ドキュメント（layout() 済み）。
    """
    if not hits:
        body = ("<h2>検索: %s</h2><p>該当なし。</p>"
                "<p class=\"meta\">派生物が未生成の場合は "
                "<code>kg build</code> を実行してください。</p>" % esc(q))
        return layout("検索", body, query=q)
    rows = "".join(hit_row(*h) for h in hits)
    return layout("検索", "<h2>検索: %s（%d 件）</h2>%s" % (esc(q), total, rows),
                  query=q)


def error_page(title, message, extra=""):
    """400/404/405 等のエラー画面（05 §3.6）。

    Args:
        title: 見出し（テキスト型）。自動的に esc() されます。例: "404 Not Found"。
        message: 説明文（テキスト型）。自動的に esc() されます。
        extra: 追加の HTML 片（**HTML 型**。呼び出し側が安全性を保証してください）。
               例: hit_row() を組み立てた「近いページ」一覧。エスケープしません。

    Returns:
        完全な HTML ドキュメント（layout() 済み）。
    """
    return layout(title, "<h2>%s</h2><p>%s</p>%s"
                  % (esc(title), esc(message), extra))


def hit_row(score_text, ref, title, summary, layer):
    """検索結果の 1 行。

    Args:
        score_text: スコア表示テキスト（テキスト型）。自動的に esc() されます。
                    例："0.95"
        ref: トピック参照（テキスト型）。自動的に esc() されます。
             href="/p/{ref}" 属性値に展開されるため、\" を含む場合も正しくエスケープされます。
        title: トピックタイトル（テキスト型）。自動的に esc() されます。
               ref と同じトピックへのリンクテキスト。ref が不正な場合の代替。
        summary: トピック説明文（テキスト型）。自動的に esc() されます。
        layer: トピックが属するレイヤー（テキスト型）。自動的に esc() されます。
               layer_badge() へ渡されます。

    Returns:
        <div class="hit">...</div> HTML 片。
    """
    return (
        '<div class="hit"><span class="score">%s</span> '
        '<a href="/p/%s">%s</a> %s<div class="meta">%s</div></div>'
        % (esc(score_text), esc(ref), esc(title or ref),
           layer_badge(layer), esc(summary)))

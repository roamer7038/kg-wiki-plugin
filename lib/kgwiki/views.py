"""画面 HTML の生成（05 §3）。純関数のみ。

すべてのページ由来文字列は esc() を通す（05 §8）。JavaScript と
外部ホストへの参照は出力しない（NFR-9）。

引数の型：以下の関数では引数が 2 種類に分かれる。
- テキスト型（esc() で自動エスケープ）：layout の title/query、banner の message、
  hit_row の全引数、layer_badge の layer
- HTML 型（呼び出し側が安全性を保証）：layout の body
"""

from .mdrender import esc

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


def topic(name, groups, type_filter=""):
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
    return layout(name, head + "".join(parts))


def page(data):
    """data のキーは serve._page_view() が組み立てる（Task 5）。"""
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
        items = "".join(
            '<li><a href="%s" rel="noreferrer">%s</a></li>' % (esc(u), esc(t or u))
            for t, u in data["sources"])
        parts.append("<h3>出典</h3><ul>%s</ul>" % items)
    return layout(data["title"], "".join(parts))


def _rel_section(heading, groups):
    if not groups:
        return ""
    parts = ["<h3>%s</h3>" % esc(heading)]
    for rel in sorted(groups):
        items = "".join(
            '<li><a%s href="%s">%s</a> <span class="meta">%s</span></li>'
            % ("" if ok else ' class="broken"', esc(href), esc(label), esc(summary))
            for href, label, summary, ok in groups[rel])
        parts.append("<h4>%s</h4><ul class=\"rel\">%s</ul>" % (esc(rel), items))
    return "".join(parts)


def search_results(q, hits, total):
    if not hits:
        body = ("<h2>検索: %s</h2><p>該当なし。</p>"
                "<p class=\"meta\">派生物が未生成の場合は "
                "<code>kg build</code> を実行してください。</p>" % esc(q))
        return layout("検索", body, query=q)
    rows = "".join(hit_row(*h) for h in hits)
    return layout("検索", "<h2>検索: %s（%d 件）</h2>%s" % (esc(q), total, rows),
                  query=q)


def error_page(title, message, extra=""):
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

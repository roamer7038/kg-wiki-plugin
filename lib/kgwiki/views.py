"""画面 HTML の生成（05 §3）。純関数のみ。

すべてのページ由来文字列は esc() を通す（05 §8）。JavaScript と
外部ホストへの参照は出力しない（NFR-9）。
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
    return '<span class="badge">%s</span>' % esc(layer)


def banner(kind, message):
    return '<div class="banner %s">%s</div>' % (esc(kind), esc(message))


def hit_row(score_text, ref, title, summary, layer):
    return (
        '<div class="hit"><span class="score">%s</span> '
        '<a href="/p/%s">%s</a> %s<div class="meta">%s</div></div>'
        % (esc(score_text), esc(ref), esc(title or ref),
           layer_badge(layer), esc(summary)))

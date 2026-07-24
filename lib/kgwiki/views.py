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

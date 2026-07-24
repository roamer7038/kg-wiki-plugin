"""views: HTML 生成の純関数（05 §3, §8）。"""

import re
import unittest

from helpers import LIB  # noqa: F401
from kgwiki import views


class TestLayout(unittest.TestCase):
    def test_title_is_escaped(self):
        html = views.layout("<script>x</script>", "<p>body</p>")
        self.assertNotIn("<script>x</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_search_query_is_escaped_in_form_value(self):
        html = views.layout("t", "<p>b</p>", query='"><script>')
        self.assertNotIn('"><script>', html)
        self.assertIn("&quot;&gt;&lt;script&gt;", html)

    def test_no_external_requests(self):
        """NFR-9: 外部ホストへの参照を一切含まない。

        以下の外部参照パターンが出力に含まれないことを検査:
        - http://, https://: 外部 URL スキーム
        - @import: CSS ファイルの外部読込
        - <link: CSS/icon の外部リソース
        - srcset=: 画像セットの外部参照
        - url(: CSS url() による外部参照
        """
        html = views.layout("t", "<p>b</p>")
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        self.assertNotIn("@import", html)
        self.assertNotIn("<link", html)
        self.assertNotIn("srcset=", html)
        self.assertNotIn("url(", html)

    def test_no_javascript(self):
        html = views.layout("t", "<p>b</p>")
        self.assertNotIn("<script", html.lower())
        self.assertFalse(re.search(r"\son[a-z]+=", html))

    def test_style_is_inlined(self):
        html = views.layout("t", "<p>b</p>")
        self.assertIn("<style>", html)


class TestParts(unittest.TestCase):
    def test_layer_badge(self):
        self.assertIn("global", views.layer_badge("global"))
        self.assertIn("project", views.layer_badge("project"))

    def test_banner_escapes_message(self):
        self.assertIn("&lt;b&gt;", views.banner("stale", "<b>"))

    def test_banner_kind_becomes_class(self):
        self.assertIn('class="banner stale"', views.banner("stale", "m"))

    def test_hit_row_escapes_all_fields(self):
        """hit_row の全引数（score_text, ref, title, summary, layer）がエスケープされること。"""
        html = views.hit_row("1.00", "t/c/s", "<i>T</i>", "<i>S</i>", "global")
        self.assertNotIn("<i>", html)
        self.assertIn("&lt;i&gt;T&lt;/i&gt;", html)
        self.assertIn('href="/p/t/c/s"', html)

    def test_hit_row_escapes_ref_in_href_attribute(self):
        """ref の " がエスケープされて href 属性から抜け出せないこと。"""
        # ref に " を含む XSS ペイロードを渡す
        html = views.hit_row("1.00", 't/c/s" onmouseover="alert(1)', "T", "S", "global")
        # 生の " による属性の切れ目がないこと
        self.assertNotIn('onmouseover="alert', html)
        # " が &quot; にエスケープされていること
        self.assertIn("&quot;", html)
        self.assertIn('href="/p/t/c/s&quot;', html)

    def test_hit_row_escapes_score_text(self):
        """score_text の危険な文字列がエスケープされること。"""
        html = views.hit_row("<script>x</script>", "t/c/s", "T", "S", "global")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_hit_row_escapes_layer(self):
        """layer の危険な文字列がエスケープされること。"""
        html = views.hit_row("1.00", "t/c/s", "T", "S", "<img src=x onerror=alert(1)>")
        # < と > がエスケープされて危険な HTML タグが成立しないこと
        self.assertIn("&lt;img", html)
        self.assertIn("&gt;", html)
        # <img> タグが実際に生成されていないこと
        self.assertNotIn("<img src=x", html)


if __name__ == "__main__":
    unittest.main()

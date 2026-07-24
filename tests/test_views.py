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
        """NFR-9: 外部ホストへの参照を一切含まない。"""
        html = views.layout("t", "<p>b</p>")
        self.assertNotIn("//", html.replace("<!--", "").replace("-->", ""))

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
        html = views.hit_row("1.00", "t/c/s", "<i>T</i>", "<i>S</i>", "global")
        self.assertNotIn("<i>", html)
        self.assertIn("&lt;i&gt;T&lt;/i&gt;", html)
        self.assertIn('href="/p/t/c/s"', html)


if __name__ == "__main__":
    unittest.main()

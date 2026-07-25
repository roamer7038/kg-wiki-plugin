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


def _page_data(**overrides):
    """views.page() 用の data 辞書（serve._page_view() が組み立てる形を模す）。"""
    data = {
        "title": "T", "type": "concepts", "updated": "2026-01-01",
        "summary": "S", "layer": "global", "banners": [],
        "body_html": "<p>body</p>", "relations": {}, "backlinks": {},
        "keywords": [], "sources": [],
    }
    data.update(overrides)
    return data


class TestHome(unittest.TestCase):
    def test_escapes_topic_name_and_recent_title(self):
        topics = [{"topic": "<script>t</script>", "count": 1,
                   "types": {"concepts": 1}, "stale": 0}]
        recent = [{"ref": "t/concepts/s", "title": "<script>x</script>",
                   "updated": "2026-01-01"}]
        html = views.home(topics, recent)
        self.assertNotIn("<script>t</script>", html)
        self.assertNotIn("<script>x</script>", html)
        self.assertIn("&lt;script&gt;", html)


class TestTopic(unittest.TestCase):
    def test_escapes_name_and_group_fields(self):
        groups = {"concepts": [
            {"ref": "t/concepts/s", "title": "<script>x</script>",
             "layer": "global", "summary": "<i>s</i>", "updated": "2026-01-01"}]}
        html = views.topic("<script>t</script>", groups)
        self.assertNotIn("<script>x</script>", html)
        self.assertNotIn("<script>t</script>", html)
        self.assertNotIn("<i>s</i>", html)

    def test_unbuilt_banner_rendered_when_passed(self):
        """05 §6.2: 未 build はトピック単位のバナーで示す（回帰テスト、項目 4）。"""
        html = views.topic("t", {}, banners=[("unbuilt", "未 build")])
        self.assertIn('class="banner unbuilt"', html)


class TestPage(unittest.TestCase):
    def test_escapes_title_summary_keywords(self):
        data = _page_data(title="<script>t</script>", summary="<i>s</i>",
                          keywords=["<b>k</b>"])
        html = views.page(data)
        self.assertNotIn("<script>t</script>", html)
        self.assertNotIn("<i>s</i>", html)
        self.assertNotIn("<b>k</b>", html)

    def test_body_html_is_passed_through_unescaped(self):
        """body_html は HTML 型（呼び出し側が安全性を保証）で、エスケープされない。"""
        data = _page_data(body_html="<p>raw <b>html</b></p>")
        html = views.page(data)
        self.assertIn("<p>raw <b>html</b></p>", html)

    def test_sources_javascript_scheme_is_not_linked(self):
        """回帰テスト（項目 1）: javascript: スキームの sources.url はリンク化しない。"""
        data = _page_data(sources=[("Evil", "javascript:alert(document.cookie)")])
        html = views.page(data)
        self.assertNotIn('href="javascript:', html)
        self.assertNotIn("javascript:alert(document.cookie)</a>", html)

    def test_sources_data_scheme_is_not_linked(self):
        data = _page_data(sources=[("Evil", "data:text/html,<script>x</script>")])
        html = views.page(data)
        self.assertNotIn('href="data:', html)

    def test_sources_https_scheme_is_linked(self):
        data = _page_data(sources=[("Good", "https://example.com/")])
        html = views.page(data)
        self.assertIn('href="https://example.com/"', html)

    def test_sources_mailto_scheme_is_linked(self):
        data = _page_data(sources=[("Mail", "mailto:a@example.com")])
        html = views.page(data)
        self.assertIn('href="mailto:a@example.com"', html)

    def test_backlinks_mentions_group_is_placed_last(self):
        """回帰テスト（項目 2）: mentions は辞書順に関わらず最後に置く。"""
        backlinks = {
            "mentions": [("/p/a/b/c", "C", "sum", True)],
            "uses": [("/p/a/b/d", "D", "sum", True)],
            "part_of": [("/p/a/b/e", "E", "sum", True)],
        }
        data = _page_data(backlinks=backlinks)
        html = views.page(data)
        pos_mentions = html.index(">mentions<")
        self.assertGreater(pos_mentions, html.index(">uses<"))
        self.assertGreater(pos_mentions, html.index(">part_of<"))

    def test_broken_relation_link_has_class(self):
        relations = {"uses": [("/search?q=x", "X", "sum", False)]}
        data = _page_data(relations=relations)
        html = views.page(data)
        self.assertIn('class="broken"', html)


class TestRelSection(unittest.TestCase):
    def test_escapes_all_four_tuple_elements(self):
        groups = {"uses": [('/p/a/b/c"', "<script>label</script>",
                            "<i>sum</i>", True)]}
        html = views._rel_section("見出し", groups)
        self.assertNotIn("<script>label</script>", html)
        self.assertNotIn("<i>sum</i>", html)
        self.assertIn("&quot;", html)

    def test_mentions_group_placed_last(self):
        groups = {"mentions": [], "beta": [], "alpha": []}
        html = views._rel_section("h", groups)
        self.assertLess(html.index(">alpha<"), html.index(">mentions<"))
        self.assertLess(html.index(">beta<"), html.index(">mentions<"))

    def test_broken_link_gets_class(self):
        groups = {"uses": [("href", "label", "sum", False)]}
        html = views._rel_section("h", groups)
        self.assertIn('class="broken"', html)

    def test_ok_link_has_no_class_attribute_on_anchor(self):
        groups = {"uses": [("href", "label", "sum", True)]}
        html = views._rel_section("h", groups)
        self.assertIn("<a href=", html)
        self.assertNotIn('class="broken"', html)


class TestSearchResults(unittest.TestCase):
    def test_escapes_query_and_hit_fields(self):
        hits = [("1.00", "t/c/s", "<script>x</script>", "<i>s</i>", "global")]
        html = views.search_results("<script>q</script>", hits, 1)
        self.assertNotIn("<script>x</script>", html)
        self.assertNotIn("<script>q</script>", html)
        self.assertNotIn("<i>s</i>", html)

    def test_no_hits_message_escapes_query(self):
        html = views.search_results("<script>q</script>", [], 0)
        self.assertNotIn("<script>q</script>", html)


class TestErrorPage(unittest.TestCase):
    def test_escapes_title_and_message(self):
        html = views.error_page("<script>t</script>", "<script>m</script>")
        self.assertNotIn("<script>t</script>", html)
        self.assertNotIn("<script>m</script>", html)

    def test_extra_is_html_type_not_escaped(self):
        """extra は HTML 型（呼び出し側が安全性を保証）で、エスケープされない。"""
        html = views.error_page("T", "M", extra="<p>extra</p>")
        self.assertIn("<p>extra</p>", html)


if __name__ == "__main__":
    unittest.main()

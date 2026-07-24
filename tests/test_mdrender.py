"""mdrender: Markdown サブセット → HTML（05 §4.1）。"""

import unittest

from helpers import LIB  # noqa: F401
from kgwiki import mdrender


def render(md):
    """resolve は Task 2 で使う。ここでは常に解決済みを返すダミー。"""
    return mdrender.render(md, lambda ref: (f"/p/{ref}", ref, True))


class TestBlocks(unittest.TestCase):
    def test_heading_levels(self):
        self.assertEqual(render("## 定義"), '<h2 id="sec-1">定義</h2>')
        self.assertEqual(render("### 詳細"), '<h3 id="sec-1">詳細</h3>')
        self.assertEqual(render("#### 補足"), '<h4 id="sec-1">補足</h4>')

    def test_h1_is_rendered_as_h2(self):
        # 03 §1.3 は本文 h1 を警告どまりにしており、実データに現れ得る
        self.assertEqual(render("# タイトル"), '<h2 id="sec-1">タイトル</h2>')

    def test_heading_ids_are_sequential(self):
        html = render("## A\n\n## B")
        self.assertIn('id="sec-1"', html)
        self.assertIn('id="sec-2"', html)

    def test_paragraph(self):
        self.assertEqual(render("普通の段落"), "<p>普通の段落</p>")

    def test_paragraph_joins_soft_wrapped_lines(self):
        self.assertEqual(render("一行目\n二行目"), "<p>一行目 二行目</p>")

    def test_bullet_list(self):
        self.assertEqual(render("- a\n- b"), "<ul><li>a</li><li>b</li></ul>")

    def test_nested_bullet_list(self):
        self.assertEqual(
            render("- a\n  - a1\n- b"),
            "<ul><li>a<ul><li>a1</li></ul></li><li>b</li></ul>")

    def test_ordered_list(self):
        self.assertEqual(render("1. a\n2. b"), "<ol><li>a</li><li>b</li></ol>")

    def test_fenced_code_is_escaped_and_not_inline_processed(self):
        md = "```python\nx = a['**b**']\n```"
        self.assertEqual(
            render(md),
            "<pre><code>x = a[&#x27;**b**&#x27;]</code></pre>")

    def test_table(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        self.assertEqual(
            render(md),
            "<table><thead><tr><th>A</th><th>B</th></tr></thead>"
            "<tbody><tr><td>1</td><td>2</td></tr></tbody></table>")

    def test_horizontal_rule(self):
        self.assertEqual(render("a\n\n---\n\nb"), "<p>a</p>\n<hr>\n<p>b</p>")


class TestUnsupportedSyntaxIsEscaped(unittest.TestCase):
    """05 §4.1: 未対応記法は解釈せずエスケープして原文のまま出す。"""

    def test_raw_html_is_escaped(self):
        self.assertEqual(render("<script>alert(1)</script>"),
                         "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>")

    def test_blockquote_is_not_interpreted(self):
        self.assertEqual(render("> 引用"), "<p>&gt; 引用</p>")

    def test_image_syntax_is_not_interpreted(self):
        # 画像は対応表に無い。リンク記法にも一致させない（先頭の ! を含めて原文）
        self.assertEqual(render("![alt](http://example.com/a.png)"),
                         "<p>!<a href=\"http://example.com/a.png\">alt</a></p>")


if __name__ == "__main__":
    unittest.main()

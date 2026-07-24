"""mdrender: Markdown サブセット → HTML（05 §4.1）。"""

import os
import subprocess
import sys
import unittest

from helpers import LIB
from kgwiki import mdrender


def render(md):
    """resolve は Task 2 で使う。ここでは常に解決済みを返すダミー。"""
    return mdrender.render(md, lambda ref: (f"/p/{ref}", ref, True))


def _render_in_subprocess(md, timeout=10):
    """別プロセスで mdrender.render(md, ...) を実行し、標準出力の HTML を返す。

    _render_runs の無限ループ回帰を検出するためのヘルパー。プロセスが
    ハングしても subprocess.run の timeout で必ず打ち切られる（テスト自体や
    CI が固まらない）。signal.alarm は Windows で動かないため使わない。
    """
    script = (
        "from kgwiki import mdrender\n"
        "import sys\n"
        "sys.stdout.write(mdrender.render(%r, lambda r: ('/p/' + r, r, True)))\n"
        % (md,)
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(LIB)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=timeout, env=env)


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

    def test_marker_change_starts_new_list(self):
        # 空行なしで bullet → ordered に切り替わったら別リストとして扱う（05 §4.1）
        self.assertEqual(
            render("- a\n- b\n1. c\n2. d"),
            "<ul><li>a</li><li>b</li></ul>\n<ol><li>c</li><li>d</li></ol>")

    def test_nested_ordered_list(self):
        # ネストした 1. 形式の子リストも <ol> になる（05 §4.1、<ul> 固定は誤り）
        self.assertEqual(
            render("1. a\n  1. a1\n2. b"),
            "<ol><li>a<ol><li>a1</li></ol></li><li>b</li></ol>")

    def test_marker_change_at_depth_1_does_not_split_parent_list(self):
        # 深さ 1 でマーカーが bullet→ordered に変わっても、深さ 0 の a/b は
        # 同一の <ul> の兄弟のまま。子は連ごとに <ul> と <ol> に分かれる。
        self.assertEqual(
            render("- a\n  - a1\n  1. a2\n- b"),
            "<ul><li>a<ul><li>a1</li></ul><ol><li>a2</li></ol></li><li>b</li></ul>")

    def test_marker_change_at_depth_1_does_not_split_parent_ordered_list(self):
        # 同様に深さ 0 が ordered の場合も a/b は同一の <ol> の兄弟のまま。
        self.assertEqual(
            render("1. a\n  1. a1\n  - a2\n2. b"),
            "<ol><li>a<ol><li>a1</li></ol><ul><li>a2</li></ul></li><li>b</li></ol>")

    def test_heading_strips_trailing_whitespace(self):
        self.assertEqual(render("## 定義   "), '<h2 id="sec-1">定義</h2>')

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


class TestIndentedListDoesNotHang(unittest.TestCase):
    """字下げされた行からリストが始まると _render_runs が無限ループしていた
    回帰の再発防止（_take_list が先頭項目の深さ 0 を保証していなかった件）。

    05 §4.1 は「リストの先頭項目が字下げされている場合は、全項目の深さを
    先頭項目を基準に正規化する」と定めており、入れ子構造の保存は要求しない。
    要求されるのは (1) 全項目が欠落なく読める形で出力されること、
    (2) 処理が必ず停止すること、の 2 点のみ（結果が複数のリストに
    分割されてよい）。以下では停止確認に加え、現在の実装が正規化した
    結果の HTML 全文を固定して検証する。
    """

    def test_list_starting_with_indented_item_terminates(self):
        result = _render_in_subprocess("  - a1\n- a")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "<ul><li>a1</li><li>a</li></ul>")
        # 欠落なし: 全項目のテキストが出力に含まれる
        self.assertIn("a1", result.stdout)
        self.assertIn(">a<", result.stdout)

    def test_marker_change_after_indented_item_terminates(self):
        result = _render_in_subprocess("  - a\n- b\n  1. c")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "<ul><li>a</li><li>b</li></ul>\n<ol><li>c</li></ol>")
        for text in ("a", "b", "c"):
            self.assertIn(">%s<" % text, result.stdout)

    def test_deeply_indented_ordered_list_with_bullet_child_terminates(self):
        result = _render_in_subprocess("  1. a\n    - a1\n  2. b")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "<ol><li>a</li></ol>\n<ul><li>a1</li></ul>\n<ol><li>b</li></ol>")
        for text in ("a", "a1", "b"):
            self.assertIn(">%s<" % text, result.stdout)

    def test_paragraph_then_indented_list_terminates(self):
        result = _render_in_subprocess("説明文\n  - 字下げされた項目\n- 通常の項目")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("<p>説明文</p>", result.stdout)
        self.assertIn("<ul>", result.stdout)
        self.assertIn("字下げされた項目", result.stdout)
        self.assertIn("通常の項目", result.stdout)

    def test_heading_then_indented_list_terminates(self):
        result = _render_in_subprocess("## 見出し\n  - 字下げされた項目\n- 通常の項目")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("<h2", result.stdout)
        self.assertIn("<ul>", result.stdout)
        self.assertIn("字下げされた項目", result.stdout)
        self.assertIn("通常の項目", result.stdout)


if __name__ == "__main__":
    unittest.main()

"""05 §6.3: 壊れたページでも 200 で読ませる。"""

import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURES, LIB, run_kg  # noqa: F401
from kgwiki import layers, serve

BROKEN_FM = "---\ntitle: 壊れている\ntype: concepts\n本文が始まってしまう\n"
UNKNOWN_KEY = ("---\ntitle: 未知キー\ntype: concepts\nslug: unknown-key\n"
               "updated: 2026-07-24\nnosuchfield: x\n---\n\n本文テキスト\n")


class TestDegraded(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "global"
        shutil.copytree(FIXTURES / "wiki-mini" / "global", self.root)
        self.assertEqual(run_kg(["build"], root=self.root).returncode, 0)
        self.dir = self.root / "topics/llm/pages/concepts"
        self.ctx = serve.ViewContext(
            layer_list=[layers.Layer(layers.GLOBAL, self.root)], topics=None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, slug, text):
        (self.dir / (slug + ".md")).write_text(text, encoding="utf-8")
        return "/p/llm/concepts/" + slug

    def write_bytes(self, slug, data):
        (self.dir / (slug + ".md")).write_bytes(data)
        return "/p/llm/concepts/" + slug

    def get(self, path):
        return serve.route("GET", path, {}, self.ctx)

    def test_unterminated_frontmatter_is_200_with_error_banner(self):
        r = self.get(self.write("broken-fm", BROKEN_FM))
        self.assertEqual(r.status, 200)
        body = r.body.decode("utf-8")
        self.assertIn("kg validate", body)
        self.assertIn("本文が始まってしまう", body)

    def test_unknown_key_is_200_and_body_readable(self):
        r = self.get(self.write("unknown-key", UNKNOWN_KEY))
        self.assertEqual(r.status, 200)
        self.assertIn("本文テキスト", r.body.decode("utf-8"))

    def test_field_issue_banner_lists_messages_not_only_codes(self):
        """05 §6.3「バナーに列挙する」。

        code だけを並べると同一 code が重複表示されるだけで、どのフィールドが
        問題なのかが読み手に伝わらない。kg validate と同じ message を出す。
        """
        path = self.write("bad-fields",
                          "---\ntitle: 不正\ntype: concepts\nslug: bad-fields\n"
                          "updated: 2026-07-24\nnosuchfield: x\n"
                          "keywords: \"リストでない\"\n---\n\n読める本文\n")
        body = self.get(path).body.decode("utf-8")
        self.assertIn("未知キー: nosuchfield", body)
        self.assertIn("keywords は文字列リストであること", body)
        self.assertIn("kg validate", body)
        self.assertIn("読める本文", body)

    def test_new_page_shows_stale_banner(self):
        r = self.get(self.write("unknown-key", UNKNOWN_KEY))
        self.assertIn("build", r.body.decode("utf-8"))

    def test_unbuilt_topic_shows_unbuilt_banner(self):
        shutil.rmtree(self.root / "topics/llm/_derived")
        r = self.get("/p/llm/concepts/rag")
        self.assertEqual(r.status, 200)
        self.assertIn("未 build", r.body.decode("utf-8"))

    # --- 追加確認: ブリーフに無いエッジケース ---

    def test_no_frontmatter_at_all_is_200(self):
        """'---' で始まらない md（frontmatter なし）は fatal 扱いだが 200 で読める。"""
        r = self.get(self.write("no-fm", "本文だけのページ。frontmatter が無い。\n"))
        self.assertEqual(r.status, 200)
        body = r.body.decode("utf-8")
        self.assertIn("kg validate", body)
        self.assertIn("本文だけのページ", body)

    def test_empty_body_page_is_200(self):
        """本文が空でも 200 で読める。"""
        text = ("---\ntitle: 空本文\ntype: concepts\nslug: empty-body\n"
                "updated: 2026-07-24\n---\n")
        r = self.get(self.write("empty-body", text))
        self.assertEqual(r.status, 200)

    def test_invalid_utf8_bytes_is_200(self):
        """不正な UTF-8 バイト列を含む md でも 500 にならず 200 で読める。"""
        data = ("---\ntitle: 不正バイト\ntype: concepts\nslug: bad-utf8\n"
                "updated: 2026-07-24\n---\n\n本文").encode("utf-8") + b"\xff\xfe" + "続き\n".encode("utf-8")
        r = self.get(self.write_bytes("bad-utf8", data))
        self.assertEqual(r.status, 200)

    def test_large_body_page_responds_promptly(self):
        """1MB 程度の本文でも実用時間で応答する。"""
        import time
        big_body = ("これはとても長い本文の行です。日本語のテキストで水増ししています。\n" * 12000)
        text = ("---\ntitle: 巨大ページ\ntype: concepts\nslug: huge\n"
                "updated: 2026-07-24\n---\n\n" + big_body)
        self.assertGreater(len(text.encode("utf-8")), 1_000_000)
        path = self.write("huge", text)
        start = time.monotonic()
        r = self.get(path)
        elapsed = time.monotonic() - start
        self.assertEqual(r.status, 200)
        self.assertLess(elapsed, 10.0, "1MB ページの応答に %.2fs かかった" % elapsed)


if __name__ == "__main__":
    unittest.main()

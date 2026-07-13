"""pages.py: summary 抽出・本文リンク抽出・スキーマ検証の unit test。"""

import tempfile
import unittest
from pathlib import Path

from helpers import LIB  # noqa: F401
from kgwiki import pages
from kgwiki.config import Config

CFG = Config(
    topics=[{"name": "llm", "description": None}],
    types=["concepts", "papers"],
    relations=["is_a", "uses", "supersedes"],
)


def load(text, filename="x.md", type_dir="concepts"):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / filename
        path.write_text(text, encoding="utf-8")
        return pages.load_page(path, "global", "llm", type_dir, CFG)


VALID = """---
title: X
type: concepts
slug: x
updated: 2026-07-01
---

本文の段落。
"""


class TestSummaryExtraction(unittest.TestCase):
    def extract(self, body):
        return pages.extract_summary(body)

    def test_skips_structure(self):
        body = ("## 見出し\n\n- リスト\n> 引用\n| 表 | x |\n"
                "<!-- コメント -->\n```\ncode\n```\n\n段落はこれ。\n")
        self.assertEqual(self.extract(body), "段落はこれ。")

    def test_multiline_comment(self):
        body = "<!--\n複数行\n-->\n本文。\n"
        self.assertEqual(self.extract(body), "本文。")

    def test_truncate_120_codepoints_no_ellipsis(self):
        body = "あ" * 200 + "\n"
        result = self.extract(body)
        self.assertEqual(len(result), 120)
        self.assertEqual(result, "あ" * 120)

    def test_keeps_ref_literal(self):
        body = "[[llm/concepts/rag]] を拡張する。\n"
        self.assertEqual(self.extract(body), "[[llm/concepts/rag]] を拡張する。")

    def test_empty_when_no_paragraph(self):
        self.assertEqual(self.extract("## 見出しのみ\n\n- リスト\n"), "")


class TestBodyLinks(unittest.TestCase):
    def test_code_exclusion(self):
        body = ("[[llm/concepts/a]]\n```\n[[llm/concepts/b]]\n```\n"
                "`[[llm/concepts/c]]` と [[llm/concepts/d]]\n")
        self.assertEqual(pages.extract_body_links(body),
                         ["llm/concepts/a", "llm/concepts/d"])

    def test_h1_detection(self):
        self.assertTrue(pages.body_has_h1("# h1\n"))
        self.assertFalse(pages.body_has_h1("## h2\n"))
        self.assertFalse(pages.body_has_h1("```\n# in code\n```\n"))


class TestSchema(unittest.TestCase):
    def codes(self, issues):
        return sorted(i.code for i in issues)

    def test_valid_page(self):
        page, issues = load(VALID)
        self.assertEqual(issues, [])
        self.assertEqual(page.ref, "llm/concepts/x")
        self.assertEqual(page.summary, "本文の段落。")  # summary 省略 → 本文抽出

    def test_missing_required(self):
        page, issues = load("---\ntitle: X\n---\n\n本文。\n")
        codes = self.codes(issues)
        self.assertIn("fm-schema", codes)
        messages = " / ".join(i.message for i in issues)
        for name in ("type", "slug", "updated"):
            self.assertIn(name, messages)

    def test_unknown_key(self):
        _page, issues = load(VALID.replace("updated:", "extra: 1\nupdated:"))
        self.assertIn("fm-schema", self.codes(issues))

    def test_slug_type_mismatch(self):
        _page, issues = load(VALID.replace("slug: x", "slug: y"))
        self.assertIn("slug-mismatch", self.codes(issues))
        _page, issues = load(VALID, type_dir="papers")
        self.assertIn("type-mismatch", self.codes(issues))

    def test_type_not_in_config(self):
        text = VALID.replace("type: concepts", "type: unknown")
        _page, issues = load(text, type_dir="unknown")
        self.assertIn("type-mismatch", self.codes(issues))

    def test_relations_validation(self):
        text = VALID.replace(
            "updated:",
            "relations:\n"
            "  - rel: likes\n    to: llm/concepts/a\n"
            "  - rel: mentions\n    to: llm/concepts/a\n"
            "  - rel: uses\n    to: bad-ref\n"
            "  - rel: uses\n    to: llm/concepts/x\n"
            "  - rel: uses\n    to: llm/concepts/a\n"
            "  - rel: uses\n    to: llm/concepts/a\n"
            "updated:")
        _page, issues = load(text)
        codes = self.codes(issues)
        self.assertEqual(codes.count("rel-undefined"), 2)  # likes + mentions
        self.assertIn("ref-format", codes)
        self.assertIn("rel-self", codes)
        self.assertIn("rel-duplicate", codes)

    def test_quoted_date_is_schema_error(self):
        _page, issues = load(VALID.replace("updated: 2026-07-01",
                                           'updated: "2026-07-01"'))
        self.assertIn("fm-schema", self.codes(issues))

    def test_fatal_frontmatter(self):
        page, issues = load("no frontmatter\n")
        self.assertIsNone(page)
        self.assertEqual([i.code for i in issues], ["fm-parse"])
        page, issues = load("---\ntitle: X\n")
        self.assertIsNone(page)
        self.assertEqual([i.code for i in issues], ["fm-parse"])


if __name__ == "__main__":
    unittest.main()

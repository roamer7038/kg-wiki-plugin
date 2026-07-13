"""kg search スコアリング: 手計算 5 例を期待値ハードコードで検証。

golden ではなく unit test として実装初期に固定する。
"""

import unittest

from helpers import LIB  # noqa: F401
from kgwiki import output, search
from kgwiki.pages import normalize_text


PAGES = {
    "page1": {"title": "Knowledge Graph", "keywords": ["ナレッジグラフ"],
              "summary": "グラフ理論による知識表現", "body_hits": {}},
    "page2": {"title": "GraphRAG", "keywords": [],
              "summary": "LLMとナレッジグラフを用いた増分検索手法",
              "body_hits": {"graphrag": 6}},
    "page3": {"title": "増分", "keywords": ["インクリメンタル"],
              "summary": "差分更新アルゴリズム", "body_hits": {}},
}


def score(query, page_key, no_body=False):
    page = PAGES[page_key]
    terms = [normalize_text(t) for t in query.split()]
    fields = {
        "title": normalize_text(page["title"]),
        "keywords": [normalize_text(k) for k in page["keywords"]],
        "summary": normalize_text(page["summary"]),
    }
    total, _all = search.index_score(terms, fields)
    if not no_body:
        for term in terms:
            n = page["body_hits"].get(term, 0)
            total += min(n, 5) * 0.5
    return total


class TestCalcExamples(unittest.TestCase):
    """手計算 5 例（最終スコアと一致すること）。"""

    def test_example1_knowledge(self):
        self.assertEqual(output.fmt_score(score("knowledge", "page1")), "6.00")

    def test_example2_katakana_exact(self):
        self.assertEqual(output.fmt_score(score("ナレッジグラフ", "page1")), "8.00")

    def test_example3_mixed_terms(self):
        self.assertEqual(output.fmt_score(score("graphrag 増分", "page2")), "16.50")
        # 注記 (1): --no-body では grep 加点が消える
        self.assertEqual(output.fmt_score(score("graphrag 増分", "page2",
                                                no_body=True)), "14.00")

    def test_example4_bigram_coverage(self):
        self.assertEqual(output.fmt_score(score("増分バックアップ", "page3")), "0.86")

    def test_example5_bonus_not_applied(self):
        self.assertEqual(output.fmt_score(score("graphrag 語彙", "page2")), "8.50")


class TestMatchingRules(unittest.TestCase):
    def test_cjk_single_char_is_substring(self):
        # CJK 1 文字項は bi-gram を構成できないため単純部分一致
        total, _ = search.index_score(["分"], {"title": "増分", "keywords": [],
                                               "summary": ""})
        self.assertEqual(total, 6.0)  # 部分一致 1.0 × w3 → 3.0、全項一致 ×2

    def test_keywords_exact_per_element(self):
        total, _ = search.index_score(
            ["rag"], {"title": "", "keywords": ["rag", "graphrag"], "summary": ""})
        self.assertEqual(total, 8.0)  # 要素完全一致 2.0 × w2 = 4.0 → ×2

    def test_no_match_zero(self):
        total, _ = search.index_score(["xyz"], {"title": "増分", "keywords": [],
                                                "summary": ""})
        self.assertEqual(total, 0.0)


if __name__ == "__main__":
    unittest.main()

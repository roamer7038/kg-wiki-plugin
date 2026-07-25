"""05 §7: 1,000 ページ規模で 1 リクエスト 1 秒以内。"""

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers import LIB, run_kg  # noqa: F401,E402
from kgwiki import layers, serve  # noqa: E402

PAGE_COUNT = 1000
BUDGET_SEC = 1.0


def build_wiki(root):
    (root / "topics/perf/pages/concepts").mkdir(parents=True)
    (root / "config.yml").write_text(
        "version: 1\ntopics:\n  - name: perf\n"
        "types: [concepts]\n"
        "relations: [relates_to]\n", encoding="utf-8")
    for i in range(PAGE_COUNT):
        target = (i + 1) % PAGE_COUNT
        (root / ("topics/perf/pages/concepts/p%04d.md" % i)).write_text(
            "---\ntitle: ページ %d\ntype: concepts\nslug: p%04d\n"
            "summary: 検索対象の要約 %d\nkeywords: [perf, graphrag]\n"
            "updated: 2026-07-24\nrelations:\n"
            "  - rel: relates_to\n    to: perf/concepts/p%04d\n---\n\n"
            # 本文に wikilink を含め、ページ画面計測に mdrender の
            # wikilink 検出・解決コストも乗せる（05 §7）。
            "## 定義\n本文 graphrag %d。次は [[perf/concepts/p%04d]] を参照。\n"
            % (i, i, i, target, i, target), encoding="utf-8")


@unittest.skipUnless(os.environ.get("KG_PERF"), "KG_PERF=1 で有効")
class TestServePerf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.root = cls.tmp / "global"
        cls.root.mkdir()
        build_wiki(cls.root)
        result = run_kg(["build"], root=cls.root)
        assert result.returncode == 0, result.stderr
        cls.ctx = serve.ViewContext(
            layer_list=[layers.Layer(layers.GLOBAL, cls.root)], topics=None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def elapsed(self, path, query=None):
        start = time.monotonic()
        response = serve.route("GET", path, query or {}, self.ctx)
        self.assertEqual(response.status, 200)
        return time.monotonic() - start

    def test_search_within_budget(self):
        seconds = self.elapsed("/search", {"q": ["graphrag"]})
        self.assertLess(seconds, BUDGET_SEC, "検索 %.3fs" % seconds)

    def test_home_within_budget(self):
        seconds = self.elapsed("/")
        self.assertLess(seconds, BUDGET_SEC, "ホーム %.3fs" % seconds)

    def test_page_within_budget(self):
        seconds = self.elapsed("/p/perf/concepts/p0001")
        self.assertLess(seconds, BUDGET_SEC, "ページ %.3fs" % seconds)


if __name__ == "__main__":
    unittest.main()

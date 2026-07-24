"""route(): HTTP を起動せずに全ルートを検証する（05 §3.1〜3.6）。"""

import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURES, LIB, run_kg  # noqa: F401
from kgwiki import layers, serve


class RouteTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "global"
        shutil.copytree(FIXTURES / "wiki-mini" / "global", self.root)
        self.assertEqual(run_kg(["build"], root=self.root).returncode, 0)
        self.ctx = serve.ViewContext(
            layer_list=[layers.Layer(layers.GLOBAL, self.root)], topics=None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def get(self, path, **query):
        q = {k: [v] for k, v in query.items()}
        return serve.route("GET", path, q, self.ctx)

    def text(self, response):
        return response.body.decode("utf-8")

    # --- 正常系 ---

    def test_home(self):
        r = self.get("/")
        self.assertEqual(r.status, 200)
        self.assertIn("llm", self.text(r))

    def test_topic_listing(self):
        r = self.get("/t/llm")
        self.assertEqual(r.status, 200)
        self.assertIn("/p/llm/concepts/rag", self.text(r))

    def test_topic_type_filter(self):
        r = self.get("/t/llm", type="papers")
        self.assertEqual(r.status, 200)
        self.assertIn("/p/llm/papers/", self.text(r))
        self.assertNotIn("/p/llm/concepts/", self.text(r))

    def test_page(self):
        r = self.get("/p/llm/concepts/rag")
        self.assertEqual(r.status, 200)
        self.assertIn("text/html", r.content_type)

    def test_search(self):
        r = self.get("/search", q="rag")
        self.assertEqual(r.status, 200)
        self.assertIn("/p/llm/concepts/rag", self.text(r))

    def test_style_css(self):
        r = self.get("/style.css")
        self.assertEqual(r.status, 200)
        self.assertIn("text/css", r.content_type)

    # --- エラー系（05 §3.6）---

    def test_empty_query_redirects_home(self):
        r = self.get("/search", q="")
        self.assertEqual(r.status, 302)
        self.assertEqual(r.headers["Location"], "/")

    def test_missing_page_is_404_with_search_hint(self):
        r = self.get("/p/llm/concepts/nope")
        self.assertEqual(r.status, 404)
        body = self.text(r)
        self.assertIn("kg new", body)
        self.assertIn("nope", body)

    def test_bad_ref_is_400(self):
        r = self.get("/p/llm/concepts/NotASlug")
        self.assertEqual(r.status, 400)

    def test_unknown_path_is_404(self):
        self.assertEqual(self.get("/nope").status, 404)

    def test_non_get_is_405(self):
        r = serve.route("POST", "/", {}, self.ctx)
        self.assertEqual(r.status, 405)

    def test_unknown_topic_is_404(self):
        self.assertEqual(self.get("/t/nosuchtopic").status, 404)


if __name__ == "__main__":
    unittest.main()

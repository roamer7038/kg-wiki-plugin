"""route(): HTTP を起動せずに全ルートを検証する（05 §3.1〜3.6）。"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import FIXTURES, LIB, clean_env, run_kg  # noqa: F401
from kgwiki import layers, pages, serve


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

    # --- 回帰テスト（Task 5 レビュー指摘）---

    def test_unbuilt_topic_shows_banner(self):
        """項目 4: 未 build のトピックはバナー付きで 200 を返す（無警告の空ページにしない）。"""
        shutil.rmtree(self.root / "topics/llm/_derived")
        r = self.get("/t/llm")
        self.assertEqual(r.status, 200)
        self.assertIn('class="banner unbuilt"', self.text(r))

    def test_unexpected_exception_in_load_page_propagates(self):
        """項目 5: 想定外の例外は縮退表示に落とさず伝播させる（500 化は HTTP アダプタの責務）。"""
        with mock.patch.object(pages, "load_page", side_effect=ValueError("boom")):
            with self.assertRaises(ValueError):
                self.get("/p/llm/concepts/rag")


class RouteLayerFilterTestCase(unittest.TestCase):
    """`/search?layer=` の絞り込み（項目 3。05 §3.5）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "root"
        shutil.copytree(FIXTURES / "wiki-mini" / "global", self.root)
        shutil.copytree(FIXTURES / "wiki-mini" / "project" / ".kg-wiki",
                        self.root / ".kg-wiki")
        result = run_kg(["build", "--layer", "global"],
                        env=clean_env(project_dir="/nonexistent"), root=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        env = clean_env(project_dir=self.root)
        env["KG_WIKI_ROOT"] = str(self.root)
        result = run_kg(["build", "--layer", "project"], env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.ctx = serve.ViewContext(
            layer_list=[layers.Layer(layers.GLOBAL, self.root),
                       layers.Layer(layers.PROJECT, self.root / ".kg-wiki")],
            topics=None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def get(self, path, **query):
        q = {k: [v] for k, v in query.items()}
        return serve.route("GET", path, q, self.ctx)

    def text(self, response):
        return response.body.decode("utf-8")

    def test_layer_project_excludes_global_hits(self):
        r = self.get("/search", q="rag", layer="project")
        self.assertEqual(r.status, 200)
        self.assertNotIn("/p/llm/concepts/rag", self.text(r))

    def test_layer_project_includes_project_only_hit(self):
        r = self.get("/search", q="ローカルメモ", layer="project")
        self.assertEqual(r.status, 200)
        self.assertIn("/p/proj/concepts/local-note", self.text(r))

    def test_layer_global_excludes_project_only_hit(self):
        r = self.get("/search", q="ローカルメモ", layer="global")
        self.assertEqual(r.status, 200)
        self.assertNotIn("/p/proj/concepts/local-note", self.text(r))

    def test_unspecified_layer_defaults_to_all(self):
        r = self.get("/search", q="ローカルメモ")
        self.assertEqual(r.status, 200)
        self.assertIn("/p/proj/concepts/local-note", self.text(r))

    def test_invalid_layer_value_falls_back_to_all(self):
        r = self.get("/search", q="ローカルメモ", layer="nosuchlayer")
        self.assertEqual(r.status, 200)
        self.assertIn("/p/proj/concepts/local-note", self.text(r))


if __name__ == "__main__":
    unittest.main()

"""serve のデータ取得層（05 §5.1, §6）。既存 API の再利用のみで実装する。"""

import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURES, LIB, run_kg  # noqa: F401
from kgwiki import layers, serve


class ServeDataTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "global"
        shutil.copytree(FIXTURES / "wiki-mini" / "global", self.root)
        result = run_kg(["build"], root=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.ctx = serve.ViewContext(
            layer_list=[layers.Layer(layers.GLOBAL, self.root)], topics=None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_merged_index_contains_pages(self):
        merged, shadow = serve.load_merged_index(self.ctx)
        self.assertIn("llm/concepts/rag", merged)
        self.assertEqual(shadow, set())

    def test_find_page_returns_layer_and_path(self):
        layer, path = serve.find_page(self.ctx, "llm/concepts/rag")
        self.assertEqual(layer.kind, "global")
        self.assertTrue(path.is_file())

    def test_find_page_missing(self):
        self.assertEqual(serve.find_page(self.ctx, "llm/concepts/nope"),
                         (None, None))

    def test_page_state_ok_after_build(self):
        layer, path = serve.find_page(self.ctx, "llm/concepts/rag")
        self.assertEqual(serve.page_state(layer, "llm/concepts/rag", path), "ok")

    def test_page_state_stale_after_edit(self):
        layer, path = serve.find_page(self.ctx, "llm/concepts/rag")
        path.write_text(path.read_text(encoding="utf-8") + "\n追記\n",
                        encoding="utf-8")
        self.assertEqual(serve.page_state(layer, "llm/concepts/rag", path),
                         "stale")

    def test_page_state_new_when_not_in_manifest(self):
        new_path = self.root / "topics/llm/pages/concepts/brand-new.md"
        new_path.write_text(
            "---\ntitle: 新規\ntype: concepts\nslug: brand-new\n"
            "updated: 2026-07-24\n---\n\n本文\n", encoding="utf-8")
        layer = self.ctx.layer_list[0]
        self.assertEqual(
            serve.page_state(layer, "llm/concepts/brand-new", new_path), "new")

    def test_page_state_unbuilt_without_manifest(self):
        shutil.rmtree(self.root / "topics/llm/_derived")
        layer, path = serve.find_page(self.ctx, "llm/concepts/rag")
        self.assertEqual(serve.page_state(layer, "llm/concepts/rag", path),
                         "unbuilt")

    def test_backlinks_are_grouped_and_sorted(self):
        links = serve.backlinks(self.ctx, "llm/concepts/rag")
        self.assertTrue(all(isinstance(x, tuple) and len(x) == 2 for x in links))
        self.assertEqual(links, sorted(links))

    def test_topic_stats(self):
        stats = serve.topic_stats(self.ctx)
        names = [s["topic"] for s in stats]
        self.assertIn("llm", names)
        llm = [s for s in stats if s["topic"] == "llm"][0]
        self.assertGreater(llm["count"], 0)
        self.assertEqual(llm["stale"], 0)


if __name__ == "__main__":
    unittest.main()

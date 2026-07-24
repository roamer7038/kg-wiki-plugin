"""serve のデータ取得層（05 §5.1, §6）。既存 API の再利用のみで実装する。"""

import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURES, LIB, clean_env, run_kg  # noqa: F401
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

    def test_page_state_unbuilt_when_manifest_version_mismatches(self):
        """schema/tool version 不一致の manifest は要 build 扱い。

        build.py / validate.py と同じ manifest.is_current() 規約に従う。
        これを通さないと、古い manifest に対してハッシュ比較を行い
        "ok" を誤って返す。
        """
        import json
        path = self.root / "topics/llm/_derived/manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["tool_version"] = "0.0.0-old"
        path.write_text(json.dumps(data), encoding="utf-8")
        layer, page = serve.find_page(self.ctx, "llm/concepts/rag")
        self.assertEqual(serve.page_state(layer, "llm/concepts/rag", page),
                         "unbuilt")

    def test_backlinks_are_grouped_and_sorted(self):
        links = serve.backlinks(self.ctx, "llm/concepts/rag")
        self.assertTrue(all(isinstance(x, tuple) and len(x) == 2 for x in links))
        self.assertEqual(links, sorted(links))
        self.assertEqual(set(links), {
            ("is_a", "llm/concepts/graphrag"),
            ("mentions", "llm/concepts/graphrag"),
            ("relates_to", "llm/concepts/agentic-search"),
            ("uses", "llm/concepts/shadowed"),
        })

    def test_topic_stats(self):
        stats = serve.topic_stats(self.ctx)
        names = [s["topic"] for s in stats]
        self.assertIn("llm", names)
        llm = [s for s in stats if s["topic"] == "llm"][0]
        self.assertEqual(llm["count"], 18)
        self.assertEqual(llm["types"], {
            "articles": 1, "concepts": 11, "decisions": 1,
            "entities": 1, "papers": 3, "queries": 1,
        })
        self.assertEqual(llm["stale"], 0)


class ServeDataTwoLayerTestCase(unittest.TestCase):
    """global/project 2 層構成での shadow・プロジェクト層優先の検証。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "root"
        shutil.copytree(FIXTURES / "wiki-mini" / "global", self.root)
        shutil.copytree(FIXTURES / "wiki-mini" / "project" / ".kg-wiki",
                        self.root / ".kg-wiki")
        result = run_kg(["build", "--layer", "global"],
                        env=clean_env(project_dir="/nonexistent"),
                        root=self.root, cwd=None)
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

    def test_load_merged_index_returns_shadow_set(self):
        merged, shadow = serve.load_merged_index(self.ctx)
        self.assertEqual(shadow, {"llm/concepts/shadowed"})
        self.assertEqual(len(merged), 23)

    def test_find_page_prefers_project_layer_for_shadow_ref(self):
        layer, path = serve.find_page(self.ctx, "llm/concepts/shadowed")
        self.assertEqual(layer.kind, "project")
        self.assertEqual(path, self.root / ".kg-wiki/topics/llm/pages/concepts/shadowed.md")

    def test_topic_stats_counts_shadow_ref_once(self):
        merged, _shadow = serve.load_merged_index(self.ctx)
        stats = serve.topic_stats(self.ctx)
        total = sum(s["count"] for s in stats)
        self.assertEqual(total, len(merged))

        by_topic = {s["topic"]: s for s in stats}
        self.assertEqual(by_topic["llm"]["count"], 19)
        self.assertEqual(by_topic["llm"]["types"], {
            "articles": 1, "concepts": 12, "decisions": 1,
            "entities": 1, "papers": 3, "queries": 1,
        })
        self.assertEqual(by_topic["proj"]["count"], 2)
        self.assertEqual(by_topic["proj"]["types"], {"concepts": 1, "decisions": 1})
        self.assertEqual(by_topic["tools"]["count"], 2)
        self.assertEqual(by_topic["tools"]["types"], {"concepts": 2})


if __name__ == "__main__":
    unittest.main()

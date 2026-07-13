"""wiki-mini に対するゴールデンテスト（03 §7.1〜7.2。T7・T11）。

期待出力は tests/fixtures/golden/ にコミットする。仕様（スコア係数等）の変更は
ゴールデン更新を同一コミットで伴うこと（04 §12）。
再生成: KG_UPDATE_GOLDEN=1 python3 -m unittest tests.test_golden
"""

import os
import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURES, copy_fixture, run_kg

GOLDEN_DIR = FIXTURES / "golden"

# (golden 名, kg 引数列)。すべて root=global / project 層あり で実行する
COMMANDS = [
    ("search-graphrag", ["search", "graphrag"]),
    ("search-knowledge-graph-ja", ["search", "ナレッジグラフ"]),
    ("search-mixed-terms", ["search", "graphrag 増分"]),
    ("search-adaptive-nobody", ["search", "適応的検索", "--no-body"]),
    ("search-kensaku-bigram", ["search", "検索", "--limit", "20"]),
    ("search-graphrag-json", ["search", "graphrag", "--json"]),
    ("search-project-layer", ["search", "kg-wiki", "--layer", "project"]),
    ("traverse-graphrag-2hop", ["traverse", "llm/concepts/graphrag", "--hops", "2",
                                "--limit", "20"]),
    ("traverse-rag-in", ["traverse", "llm/concepts/rag", "--direction", "in",
                         "--limit", "20"]),
    ("traverse-rag-rel-filter", ["traverse", "llm/concepts/rag", "--hops", "2",
                                 "--rel", "is_a,mentions", "--limit", "20"]),
    ("traverse-shadowed", ["traverse", "llm/concepts/shadowed"]),
    ("traverse-missing-node", ["traverse", "llm/articles/graphrag-intro"]),
    ("traverse-json", ["traverse", "llm/concepts/graphrag", "--json"]),
    ("path-microsoft-rag", ["path", "llm/entities/microsoft", "llm/concepts/rag"]),
    ("path-lightrag-kg", ["path", "llm/papers/lightrag",
                          "llm/concepts/knowledge-graph"]),
    ("path-json", ["path", "llm/entities/microsoft", "llm/concepts/rag", "--json"]),
    ("validate-all", ["validate"]),
    ("validate-json", ["validate", "--json"]),
    # Phase 2: コミュニティ
    ("community-graphrag", ["community", "llm/concepts/graphrag"]),
    ("community-graphrag-json", ["community", "llm/concepts/graphrag", "--json"]),
    ("community-query", ["community", "--query", "graphrag"]),
]


class TestGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.fix = copy_fixture("wiki-mini", Path(cls.tmp.name))
        for layer in ("global", "project"):
            result = run_kg(["build", "--layer", layer], root=cls.fix / "global",
                            project_dir=cls.fix / "project")
            assert result.returncode == 0, result.stderr

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_cmd(self, args):
        result = run_kg(args, root=self.fix / "global",
                        project_dir=self.fix / "project")
        return result

    def test_golden(self):
        update = os.environ.get("KG_UPDATE_GOLDEN") == "1"
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        for name, args in COMMANDS:
            with self.subTest(name=name):
                first = self.run_cmd(args)
                second = self.run_cmd(args)
                # 決定論: 複数回実行の一致（NFR-2）
                self.assertEqual(first.stdout, second.stdout, name)
                self.assertEqual(first.returncode, second.returncode, name)
                golden_path = GOLDEN_DIR / f"{name}.txt"
                if update:
                    golden_path.write_text(first.stdout, encoding="utf-8")
                else:
                    self.assertTrue(golden_path.is_file(),
                                    f"golden 不在: {name}（KG_UPDATE_GOLDEN=1 で生成）")
                    self.assertEqual(first.stdout,
                                     golden_path.read_text(encoding="utf-8"), name)

    def test_topic_filter_keeps_cross_topic_display(self):
        # --topic はエッジの出所絞り込み。到達した他 topic ノードは (missing) では
        # なく実ページとして表示される（03 §3.5、監査指摘①の回帰テスト）
        result = self.run_cmd(["traverse", "tools/concepts/qmd", "--topic", "tools"])
        self.assertIn("llm/concepts/vector-search]]\tベクトル検索", result.stdout)
        self.assertNotIn("(missing)", result.stdout)
        # 起点が --topic 外でもエッジ出所の絞り込みとして機能する
        result = self.run_cmd(["traverse", "llm/concepts/vector-search",
                               "--topic", "tools", "--direction", "in"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("tools/concepts/qmd", result.stdout)

    def test_shadow_edge_replacement(self):
        # shadow ページの出エッジ置換: project 版の uses→knowledge-graph のみ辿れる
        result = self.run_cmd(["traverse", "llm/concepts/shadowed",
                               "--direction", "out"])
        self.assertIn("llm/concepts/knowledge-graph", result.stdout)
        self.assertNotIn("llm/concepts/rag", result.stdout)

    def test_shadow_title_project_wins(self):
        result = self.run_cmd(["search", "shadowed"])
        self.assertIn("project 版が優先される", result.stdout)
        self.assertNotIn("global 版", result.stdout)

    def test_path_none(self):
        result = self.run_cmd(["path", "llm/concepts/lonely", "llm/concepts/rag"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("経路なし", result.stderr)

    def test_missing_endpoint_exit1(self):
        result = self.run_cmd(["traverse", "llm/concepts/nonexistent"])
        self.assertEqual(result.returncode, 1)
        result = self.run_cmd(["path", "llm/concepts/nonexistent", "llm/concepts/rag"])
        self.assertEqual(result.returncode, 1)

    def test_search_zero_hits(self):
        result = self.run_cmd(["search", "zzznohit"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_limit_applies(self):
        result = self.run_cmd(["search", "検索", "--limit", "3"])
        self.assertEqual(len(result.stdout.splitlines()), 3)


if __name__ == "__main__":
    unittest.main()

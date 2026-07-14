"""kg build: 冪等性・増分=全再生成・中断規約。"""

import json
import tempfile
import unittest
from pathlib import Path

from helpers import copy_fixture, run_kg, tree_bytes


def build_both(fix, extra=None):
    g = run_kg(["build", "--layer", "global"] + (extra or []),
               root=fix / "global", project_dir=fix / "project")
    p = run_kg(["build", "--layer", "project"] + (extra or []),
               root=fix / "global", project_dir=fix / "project")
    return g, p


class TestBuild(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fix = copy_fixture("wiki-mini", Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def derived_state(self):
        state = {}
        for layer in ("global", "project/.kg-wiki"):
            base = self.fix / layer / "topics"
            for derived in sorted(base.glob("*/_derived")):
                state.update({f"{layer}/{p.relative_to(self.fix / layer)}": p.read_bytes()
                              for p in sorted(derived.rglob("*")) if p.is_file()})
        return state

    def test_idempotent(self):
        g, p = build_both(self.fix)
        self.assertEqual(g.returncode, 0, g.stderr)
        self.assertEqual(p.returncode, 0, p.stderr)
        first = self.derived_state()
        g2, p2 = build_both(self.fix)
        self.assertEqual((g2.returncode, p2.returncode), (0, 0))
        self.assertEqual(first, self.derived_state())  # バイト一致

    def test_incremental_equals_full(self):
        build_both(self.fix)
        # 1 ページ変更
        page = self.fix / "global/topics/llm/pages/concepts/rag.md"
        page.write_text(page.read_text(encoding="utf-8")
                        .replace("検索拡張生成の基本形", "検索拡張生成の基本"),
                        encoding="utf-8")
        g_inc, _ = build_both(self.fix)
        self.assertEqual(g_inc.returncode, 0)
        incremental = self.derived_state()
        inc_stdout = g_inc.stdout
        # 全再生成と比較
        g_full, _ = build_both(self.fix, extra=["--full"])
        self.assertEqual(g_full.returncode, 0)
        self.assertEqual(incremental, self.derived_state())  # 出力バイト一致

    def test_incremental_equals_full_on_add(self):
        # ページ追加: 既存ページと [[ref]] で結ぶ新規ページを増分 build → --full 一致
        build_both(self.fix)
        new_page = self.fix / "global/topics/llm/pages/concepts/added.md"
        new_page.write_text(
            "---\ntitle: 追加ページ\ntype: concepts\nslug: added\n"
            "summary: 増分追加の検証用\nupdated: 2026-07-14\n---\n\n"
            "[[llm/concepts/rag]] を参照する追加ページ。\n", encoding="utf-8")
        g_inc, _ = build_both(self.fix)
        self.assertEqual(g_inc.returncode, 0, g_inc.stdout)
        incremental = self.derived_state()
        g_full, _ = build_both(self.fix, extra=["--full"])
        self.assertEqual(g_full.returncode, 0)
        self.assertEqual(incremental, self.derived_state())  # 出力バイト一致

    def test_incremental_equals_full_on_delete(self):
        # ページ削除: 他ページから参照される rag を削除 → 増分 build → --full 一致
        # （逆エッジ・adjacency・community に残骸が無いこと）
        build_both(self.fix)
        (self.fix / "global/topics/llm/pages/concepts/rag.md").unlink()
        g_inc, _ = build_both(self.fix)
        self.assertEqual(g_inc.returncode, 0, g_inc.stdout)
        incremental = self.derived_state()
        g_full, _ = build_both(self.fix, extra=["--full"])
        self.assertEqual(g_full.returncode, 0)
        self.assertEqual(incremental, self.derived_state())  # 出力バイト一致

    def test_incremental_equals_full_on_edge_change(self):
        # エッジ変更: graphrag の uses 関係の to を別の既存 ref に繋ぎ変える
        # → 増分 build → --full 一致
        build_both(self.fix)
        page = self.fix / "global/topics/llm/pages/concepts/graphrag.md"
        page.write_text(page.read_text(encoding="utf-8")
                        .replace("to: llm/concepts/knowledge-graph",
                                 "to: llm/concepts/vector-search"),
                        encoding="utf-8")
        g_inc, _ = build_both(self.fix)
        self.assertEqual(g_inc.returncode, 0, g_inc.stdout)
        incremental = self.derived_state()
        g_full, _ = build_both(self.fix, extra=["--full"])
        self.assertEqual(g_full.returncode, 0)
        self.assertEqual(incremental, self.derived_state())  # 出力バイト一致

    def test_summary_counts(self):
        g, _ = build_both(self.fix)
        lines = sorted(g.stdout.splitlines())
        self.assertEqual(lines, [
            "built llm: 18 pages (+18 ~0 -0)",
            "built tools: 2 pages (+2 ~0 -0)",
        ])
        # 変更 1・削除 1・追加なし
        page = self.fix / "global/topics/llm/pages/concepts/rag.md"
        page.write_text(page.read_text(encoding="utf-8") + "\n追記。\n",
                        encoding="utf-8")
        (self.fix / "global/topics/llm/pages/concepts/lonely.md").unlink()
        g2, _ = build_both(self.fix)
        self.assertIn("built llm: 17 pages (+0 ~1 -1)", g2.stdout)

    def test_json_output(self):
        g, _ = build_both(self.fix, extra=["--json"])
        records = [json.loads(line) for line in g.stdout.splitlines()]
        topics = {r["topic"]: r for r in records}
        self.assertEqual(topics["llm"]["pages"], 18)
        self.assertEqual(set(records[0]) ,
                         {"added", "changed", "pages", "removed", "topic"})

    def test_halt_on_invalid_page(self):
        build_both(self.fix)
        before = self.derived_state()
        bad = self.fix / "global/topics/llm/pages/concepts/badpage.md"
        bad.write_text("---\ntitle: Bad\ntype: concepts\nslug: badpage\n---\n\nx\n",
                       encoding="utf-8")  # updated 欠落 → fm-schema
        g, _ = build_both(self.fix)
        self.assertEqual(g.returncode, 2)
        self.assertIn("fm-schema", g.stdout)  # issue 形式で stdout
        # 当該 topic の派生物・manifest は未更新、他 topic（tools）は成功
        after = self.derived_state()
        llm_keys = [k for k in before if "/llm/" in k]
        for key in llm_keys:
            self.assertEqual(before[key], after[key])
        self.assertIn("built tools: 2 pages (+0 ~0 -0)", g.stdout)

    def test_link_broken_does_not_halt(self):
        # リンク未解決は中断理由にしない — wiki-mini に含まれる
        g, p = build_both(self.fix)
        self.assertEqual((g.returncode, p.returncode), (0, 0))

    def test_missing_config_exit1(self):
        result = run_kg(["build", "--layer", "global"],
                        root=Path(self.tmp.name) / "nonexistent",
                        project_dir=self.fix / "project")
        self.assertEqual(result.returncode, 1)
        self.assertIn("kg init", result.stderr)

    def test_layer_all_rejected(self):
        result = run_kg(["build", "--layer", "all"], root=self.fix / "global",
                        project_dir=self.fix / "project")
        self.assertEqual(result.returncode, 3)

    def test_config_change_detected_incrementally(self):
        # 使用中の rel/type を config から削除 → 増分 build も --full と同じく
        # exit 2 で中断する（監査指摘②の回帰テスト。増分・全再生成一致）
        build_both(self.fix)
        config = self.fix / "global/config.yml"
        text = config.read_text(encoding="utf-8")
        config.write_text(text.replace("supersedes, ", ""), encoding="utf-8")
        g_inc, _ = build_both(self.fix)
        self.assertEqual(g_inc.returncode, 2, g_inc.stdout)
        self.assertIn("rel-undefined", g_inc.stdout)
        g_full, _ = build_both(self.fix, extra=["--full"])
        self.assertEqual(g_full.returncode, 2)
        self.assertIn("rel-undefined", g_full.stdout)
        # 復元後は増分 build が回復する
        config.write_text(text, encoding="utf-8")
        g_ok, _ = build_both(self.fix)
        self.assertEqual(g_ok.returncode, 0, g_ok.stdout)

    def test_type_removal_detected_incrementally(self):
        build_both(self.fix)
        config = self.fix / "global/config.yml"
        text = config.read_text(encoding="utf-8")
        config.write_text(text.replace("queries, ", ""), encoding="utf-8")
        g_inc, _ = build_both(self.fix)
        self.assertEqual(g_inc.returncode, 2, g_inc.stdout)
        self.assertIn("type-mismatch", g_inc.stdout)

    def test_tool_version_mismatch_forces_full(self):
        build_both(self.fix)
        man_path = self.fix / "global/topics/llm/_derived/manifest.json"
        man = json.loads(man_path.read_text(encoding="utf-8"))
        man["tool_version"] = "0.0.1"
        man_path.write_text(json.dumps(man), encoding="utf-8")
        g, _ = build_both(self.fix)
        self.assertEqual(g.returncode, 0)
        man2 = json.loads(man_path.read_text(encoding="utf-8"))
        self.assertNotEqual(man2["tool_version"], "0.0.1")


if __name__ == "__main__":
    unittest.main()

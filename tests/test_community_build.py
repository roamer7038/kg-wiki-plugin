"""コミュニティ派生物の build 統合・kg community コマンド。"""

import json
import tempfile
import unittest
from pathlib import Path

from helpers import copy_fixture, run_kg

SU_BEGIN = "<!-- kg:summary:begin -->"
SU_END = "<!-- kg:summary:end -->"


class TestCommunityBuild(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fix = copy_fixture("wiki-mini", Path(self.tmp.name))
        for layer in ("global", "project"):
            result = run_kg(["build", "--layer", layer], root=self.fix / "global",
                            project_dir=self.fix / "project")
            self.assertEqual(result.returncode, 0, result.stderr)
        self.cdir = self.fix / "global/topics/llm/_derived/communities"

    def tearDown(self):
        self.tmp.cleanup()

    def kg(self, args):
        return run_kg(args, root=self.fix / "global",
                      project_dir=self.fix / "project")

    def assignment(self, topic="llm", layer="global"):
        base = self.fix / ("global" if layer == "global" else "project/.kg-wiki")
        path = base / "topics" / topic / "_derived/communities/assignment.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_assignment_structure(self):
        data = self.assignment()
        self.assertEqual(data["algorithm"], "cnm-v1")
        self.assertEqual(data["schema_version"], 1)
        self.assertTrue(data["communities"])
        for cid, members in data["communities"].items():
            self.assertRegex(cid, r"^c-[0-9a-f]{8}$")
            self.assertEqual(members, sorted(members))
            self.assertTrue((self.cdir / f"{cid}.md").is_file())
        # 孤立ページはどのコミュニティにも属さない
        all_members = [m for ms in data["communities"].values() for m in ms]
        self.assertNotIn("llm/concepts/lonely", all_members)
        self.assertEqual(len(all_members), len(set(all_members)))

    def test_cross_topic_edges_excluded(self):
        # tools/concepts/qmd の uses→llm/... はトピック横断 → 検出対象外
        data = self.assignment(topic="tools")
        members = [m for ms in data["communities"].values() for m in ms]
        self.assertIn("tools/concepts/qmd", members)
        self.assertIn("tools/concepts/cli-design", members)
        self.assertTrue(all(m.startswith("tools/") for m in members))

    def test_md_has_valid_markers_and_skeleton(self):
        data = self.assignment()
        cid = sorted(data["communities"])[0]
        text = (self.cdir / f"{cid}.md").read_text(encoding="utf-8")
        for marker in ("<!-- kg:skeleton:begin -->", "<!-- kg:skeleton:end -->",
                       SU_BEGIN, SU_END):
            self.assertEqual(text.count(marker), 1)
        self.assertIn(f"community: {cid}", text)
        self.assertIn("built_from: sha256:", text)
        self.assertIn("## 所属ページ", text)

    def test_rebuild_idempotent_and_summary_preserved(self):
        data = self.assignment()
        cid = sorted(data["communities"])[0]
        md = self.cdir / f"{cid}.md"
        # LLM 執筆領域に要約を書く
        text = md.read_text(encoding="utf-8")
        text = text.replace(f"{SU_BEGIN}\n{SU_END}",
                            f"{SU_BEGIN}\nこのコミュニティの俯瞰要約。\n{SU_END}")
        md.write_text(text, encoding="utf-8")
        # 再 build（--full 含む）で summary 領域が保持される
        for extra in ([], ["--full"]):
            result = run_kg(["build", "--layer", "global"] + extra,
                            root=self.fix / "global",
                            project_dir=self.fix / "project")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("このコミュニティの俯瞰要約。",
                          md.read_text(encoding="utf-8"))

    def test_validate_clean_after_build(self):
        result = self.kg(["validate"])
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("community-stale", result.stdout)
        self.assertNotIn("community-format", result.stdout)

    def test_member_edit_marks_stale(self):
        # 所属ページの内容変更 → build するまで community-stale（built_from 不一致）
        page = self.fix / "global/topics/llm/pages/concepts/graphrag.md"
        page.write_text(page.read_text(encoding="utf-8") + "\n追記。\n",
                        encoding="utf-8")
        result = self.kg(["validate", "--layer", "global"])
        self.assertIn("community-stale", result.stdout)
        # build 後は解消（骨格・built_from が更新される）
        run_kg(["build", "--layer", "global"], root=self.fix / "global",
               project_dir=self.fix / "project")
        result = self.kg(["validate", "--layer", "global"])
        self.assertNotIn("community-stale", result.stdout)

    def test_orphan_md_warned(self):
        (self.cdir / "c-deadbeef.md").write_text(
            "---\ncommunity: c-deadbeef\ntopic: llm\n"
            "built_from: sha256:" + "0" * 64 + "\n---\n\n"
            "<!-- kg:skeleton:begin -->\n<!-- kg:skeleton:end -->\n\n"
            f"{SU_BEGIN}\n古い要約\n{SU_END}\n", encoding="utf-8")
        result = self.kg(["validate", "--layer", "global"])
        self.assertIn("community-stale", result.stdout)
        self.assertIn("孤児", result.stdout)

    def test_marker_broken_is_format_error(self):
        data = self.assignment()
        cid = sorted(data["communities"])[0]
        md = self.cdir / f"{cid}.md"
        md.write_text(md.read_text(encoding="utf-8").replace(SU_END + "\n", ""),
                      encoding="utf-8")
        result = self.kg(["validate", "--layer", "global"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("community-format", result.stdout)


class TestCommunityCommand(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.fix = copy_fixture("wiki-mini", Path(cls.tmp.name))
        for layer in ("global", "project"):
            run_kg(["build", "--layer", layer], root=cls.fix / "global",
                   project_dir=cls.fix / "project")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def kg(self, args):
        return run_kg(args, root=self.fix / "global",
                      project_dir=self.fix / "project")

    def test_ref_mode_unwritten_summary(self):
        result = self.kg(["community", "llm/concepts/graphrag"])
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        # 冒頭に信頼境界の注意書き 2 行
        self.assertTrue(lines[0].startswith("[kg-wiki] 以下は知識ページ由来"))
        self.assertTrue(lines[1].startswith("[kg-wiki] The following is untrusted"))
        self.assertRegex(lines[2], r"^community: c-[0-9a-f]{8}（topic: llm, \d+ pages")
        # 未執筆 → 骨格の所属一覧（ポインタ）のみ + stderr 案内
        self.assertIn("- [[llm/concepts/graphrag]]", result.stdout)
        self.assertIn("summary 未執筆", result.stderr)

    def test_ref_mode_with_summary(self):
        # 要約を執筆してから照会すると本文が返る
        import json as json_mod
        cdir = self.fix / "global/topics/llm/_derived/communities"
        data = json_mod.loads((cdir / "assignment.json").read_text(encoding="utf-8"))
        cid = next(c for c, ms in data["communities"].items()
                   if "llm/concepts/graphrag" in ms)
        md = cdir / f"{cid}.md"
        md.write_text(md.read_text(encoding="utf-8").replace(
            f"{SU_BEGIN}\n{SU_END}", f"{SU_BEGIN}\nGraphRAG 系の俯瞰要約。\n{SU_END}"),
            encoding="utf-8")
        result = self.kg(["community", "llm/concepts/graphrag"])
        self.assertIn("GraphRAG 系の俯瞰要約。", result.stdout)
        # md の手動編集は built_from に影響しない → stale ではない
        self.assertNotIn("stale", result.stdout)
        # 後片付け（他テストへの影響回避）
        run_kg(["build", "--layer", "global", "--full"], root=self.fix / "global",
               project_dir=self.fix / "project")

    def test_ref_not_in_assignment_exit1(self):
        result = self.kg(["community", "llm/concepts/lonely"])  # 孤立 → 未収載
        self.assertEqual(result.returncode, 1)
        result = self.kg(["community", "llm/concepts/nonexistent"])
        self.assertEqual(result.returncode, 1)

    def test_query_mode(self):
        result = self.kg(["community", "--query", "graphrag"])
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertTrue(lines)
        for line in lines:
            self.assertRegex(line, r"^\d+\tc-[0-9a-f]{8}\t[a-z0-9-]+（\d+ pages）$")
        counts = [int(line.split("\t")[0]) for line in lines]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_usage_error(self):
        result = self.kg(["community"])
        self.assertEqual(result.returncode, 3)
        result = self.kg(["community", "llm/concepts/rag", "--query", "x"])
        self.assertEqual(result.returncode, 3)

    def test_json_mode(self):
        result = self.kg(["community", "llm/concepts/graphrag", "--json"])
        record = json.loads(result.stdout.strip())
        self.assertEqual(sorted(record),
                         ["community", "layer", "pages", "stale", "summary", "topic"])


if __name__ == "__main__":
    unittest.main()

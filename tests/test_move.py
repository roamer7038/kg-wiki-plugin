"""kg move: 移動・被参照書換・中断からの収束。"""

import tempfile
import unittest
from pathlib import Path

from helpers import copy_fixture, run_kg


class TestMove(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fix = copy_fixture("wiki-mini", Path(self.tmp.name))
        for layer in ("global", "project"):
            run_kg(["build", "--layer", layer], root=self.fix / "global",
                   project_dir=self.fix / "project")

    def tearDown(self):
        self.tmp.cleanup()

    def kg(self, args):
        return run_kg(args, root=self.fix / "global",
                      project_dir=self.fix / "project")

    def test_move_rewrites_references(self):
        result = self.kg(["move", "llm/concepts/rag", "llm/concepts/vanilla-rag",
                          "--date", "2026-07-13"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        old = self.fix / "global/topics/llm/pages/concepts/rag.md"
        new = self.fix / "global/topics/llm/pages/concepts/vanilla-rag.md"
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())
        self.assertIn("slug: vanilla-rag", new.read_text(encoding="utf-8"))
        # 被参照書換（frontmatter・本文とも、両層）
        graphrag = (self.fix / "global/topics/llm/pages/concepts/graphrag.md") \
            .read_text(encoding="utf-8")
        self.assertIn("to: llm/concepts/vanilla-rag", graphrag)
        self.assertIn("[[llm/concepts/vanilla-rag]]", graphrag)
        self.assertNotIn("llm/concepts/rag]", graphrag)
        proj = (self.fix / "project/.kg-wiki/topics/proj/pages/decisions/use-kg-wiki.md") \
            .read_text(encoding="utf-8")
        self.assertIn("to: llm/concepts/vanilla-rag", proj)
        # validate クリーン（error なし）
        v = self.kg(["validate"])
        self.assertEqual(v.returncode, 0, v.stdout)
        # log.md に move 記録（両層）
        for log in (self.fix / "global/log.md",
                    self.fix / "project/.kg-wiki/log.md"):
            self.assertIn("[move] llm/concepts/rag → llm/concepts/vanilla-rag",
                          log.read_text(encoding="utf-8"))

    def test_move_type_change_updates_frontmatter(self):
        result = self.kg(["move", "llm/concepts/lonely", "llm/queries/lonely-note",
                          "--date", "2026-07-13"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        new = self.fix / "global/topics/llm/pages/queries/lonely-note.md"
        text = new.read_text(encoding="utf-8")
        self.assertIn("type: queries", text)
        self.assertIn("slug: lonely-note", text)

    def test_dry_run_changes_nothing(self):
        before = sorted(str(p) for p in self.fix.rglob("*.md"))
        result = self.kg(["move", "llm/concepts/rag", "llm/concepts/vanilla-rag",
                          "--dry-run"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("move-plan", result.stdout)
        self.assertTrue(all(line.startswith("info\t")
                            for line in result.stdout.splitlines()))
        self.assertEqual(before, sorted(str(p) for p in self.fix.rglob("*.md")))

    def test_precheck_undefined_type_exit2(self):
        result = self.kg(["move", "llm/concepts/rag", "llm/badtype/rag"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("type-undefined", result.stdout)

    def test_precheck_ref_format_exit2(self):
        result = self.kg(["move", "llm/concepts/rag", "llm/concepts/BAD"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("ref-format", result.stdout)

    def test_conflict_exit1(self):
        result = self.kg(["move", "llm/concepts/rag", "llm/concepts/graphrag"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("衝突", result.stderr)

    def test_target_missing_exit1(self):
        result = self.kg(["move", "llm/concepts/nothere", "llm/concepts/anywhere"])
        self.assertEqual(result.returncode, 1)

    def test_interrupted_move_converges(self):
        # 人工中断状態: ページは移動済み・参照書換は未実施
        old = self.fix / "global/topics/llm/pages/concepts/rag.md"
        new = self.fix / "global/topics/llm/pages/concepts/vanilla-rag.md"
        text = old.read_text(encoding="utf-8") \
            .replace("slug: rag", "slug: vanilla-rag")
        new.write_text(text, encoding="utf-8")
        old.unlink()
        # validate が不整合（旧 ref への未解決参照）を検出する
        v = self.kg(["validate"])
        self.assertEqual(v.returncode, 2)
        self.assertIn("link-broken-fm", v.stdout)
        # 再実行 → 書換のみ続行して収束
        result = self.kg(["move", "llm/concepts/rag", "llm/concepts/vanilla-rag",
                          "--date", "2026-07-13"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        v = self.kg(["validate"])
        self.assertEqual(v.returncode, 0, v.stdout)

    def test_to_layer_move(self):
        result = self.kg(["move", "llm/concepts/project-only",
                          "llm/concepts/project-only", "--to-layer", "global",
                          "--date", "2026-07-13"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.fix /
                         "global/topics/llm/pages/concepts/project-only.md").exists())
        self.assertFalse((self.fix /
                          "project/.kg-wiki/topics/llm/pages/concepts/project-only.md"
                          ).exists())

    def test_same_ref_same_layer_exit2(self):
        result = self.kg(["move", "llm/concepts/rag", "llm/concepts/rag"])
        self.assertEqual(result.returncode, 2)

    def test_rename_topic(self):
        result = self.kg(["move", "--rename-topic", "tools", "devtools",
                          "--layer", "global", "--date", "2026-07-13"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.fix / "global/topics/tools").exists())
        self.assertTrue((self.fix /
                         "global/topics/devtools/pages/concepts/qmd.md").exists())
        config = (self.fix / "global/config.yml").read_text(encoding="utf-8")
        self.assertIn("- name: devtools", config)
        self.assertNotIn("- name: tools", config)
        # 本文リンク [[tools/concepts/qmd]] も書換済み
        cli = (self.fix / "global/topics/devtools/pages/concepts/cli-design.md") \
            .read_text(encoding="utf-8")
        self.assertIn("[[devtools/concepts/qmd]]", cli)
        v = self.kg(["validate"])
        self.assertEqual(v.returncode, 0, v.stdout)


if __name__ == "__main__":
    unittest.main()

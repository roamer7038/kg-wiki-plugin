"""回帰のテスト。"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from helpers import clean_env, run_kg

import kgwiki.pages as pages


class TestInitBootstrapsProjectLayer(unittest.TestCase):
    """kg init --layer project は .kg-wiki を自分で作れること。"""

    def test_init_project_without_existing_dir(self):
        with TemporaryDirectory() as tmp:
            proj = Path(tmp) / "proj"
            proj.mkdir()
            res = run_kg(["init", "--layer", "project", "--topic", "t1"],
                         cwd=proj, env=clean_env(project_dir=proj))
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertTrue((proj / ".kg-wiki" / "config.yml").is_file())
            self.assertTrue((proj / ".kg-wiki" / "topics" / "t1" / "pages").is_dir())


class TestSummarySkipsThematicBreak(unittest.TestCase):
    """水平線は要約に採用しないこと。"""

    def test_thematic_break_is_not_summary(self):
        body = "> 対応: FR-1.1\n\n- 箇条書きのみの本文\n\n---\n出典: spec.md\n"
        self.assertEqual(pages.extract_summary(body), "出典: spec.md")

    def test_thematic_break_variants(self):
        for rule in ("---", "***", "___", "- - -"):
            self.assertEqual(pages.extract_summary(f"{rule}\n\n本文\n"), "本文", rule)

    def test_normal_paragraph_still_wins(self):
        self.assertEqual(pages.extract_summary("最初の段落\n\n---\n"), "最初の段落")


class TestTraverseTruncationWarns(unittest.TestCase):
    """--limit による打ち切りは stderr で警告すること（黙って hop を落とさない）。"""

    def _wiki(self, tmp):
        root = Path(tmp) / "wiki"
        run_kg(["init", "--layer", "global", "--topic", "t"], root=root)
        pages_dir = root / "topics" / "t" / "pages" / "concepts"
        pages_dir.mkdir(parents=True, exist_ok=True)
        # hub に 12 件がぶら下がり、さらに深さ 2 のページを 1 件持つ
        for i in range(12):
            (pages_dir / f"n{i}.md").write_text(
                f"---\ntitle: n{i}\ntype: concepts\nslug: n{i}\n"
                f"relations:\n  - rel: relates_to\n    to: t/concepts/hub\n"
                f"updated: 2026-07-14\n---\n\n本文 n{i}\n", encoding="utf-8")
        (pages_dir / "hub.md").write_text(
            "---\ntitle: hub\ntype: concepts\nslug: hub\nupdated: 2026-07-14\n---\n\n本文 hub\n",
            encoding="utf-8")
        (pages_dir / "deep.md").write_text(
            "---\ntitle: deep\ntype: concepts\nslug: deep\n"
            "relations:\n  - rel: relates_to\n    to: t/concepts/n0\n"
            "updated: 2026-07-14\n---\n\n本文 deep\n", encoding="utf-8")
        run_kg(["build", "--layer", "global"], root=root)
        return root

    def test_warns_when_results_truncated(self):
        with TemporaryDirectory() as tmp:
            root = self._wiki(tmp)
            res = run_kg(["traverse", "t/concepts/hub", "--hops", "2", "--limit", "5",
                          "--layer", "global"], root=root)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(len(res.stdout.strip().split("\n")), 5)
            self.assertIn("打ち切り", res.stderr)
            self.assertIn("--limit", res.stderr)

    def test_no_warning_when_all_results_fit(self):
        with TemporaryDirectory() as tmp:
            root = self._wiki(tmp)
            res = run_kg(["traverse", "t/concepts/hub", "--hops", "2", "--limit", "99",
                          "--layer", "global"], root=root)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertNotIn("打ち切り", res.stderr)


class TestLogAcceptsMultipleRefs(unittest.TestCase):
    """一括取り込みを 1 コマンドで記録できること（1 ref = 1 行）。"""

    def _wiki(self, tmp):
        root = Path(tmp) / "wiki"
        run_kg(["init", "--layer", "global", "--topic", "t"], root=root)
        pages_dir = root / "topics" / "t" / "pages" / "concepts"
        pages_dir.mkdir(parents=True, exist_ok=True)
        for name in ("a", "b", "c"):
            (pages_dir / f"{name}.md").write_text(
                f"---\ntitle: {name}\ntype: concepts\nslug: {name}\n"
                f"updated: 2026-07-14\n---\n\n本文 {name}\n", encoding="utf-8")
        run_kg(["build", "--layer", "global"], root=root)
        return root

    def test_logs_one_line_per_ref(self):
        with TemporaryDirectory() as tmp:
            root = self._wiki(tmp)
            res = run_kg(["log", "ingest", "t/concepts/a", "t/concepts/b", "t/concepts/c",
                          "--source", "https://example.com/x", "--layer", "global",
                          "--date", "2026-07-14"], root=root)
            self.assertEqual(res.returncode, 0, res.stderr)
            log = (root / "log.md").read_text(encoding="utf-8")
            for name in ("a", "b", "c"):
                self.assertIn(f"[ingest] t/concepts/{name} — https://example.com/x", log)

    def test_all_refs_validated_before_any_append(self):
        """1 つでも不在なら何も書かない（部分適用しない）。"""
        with TemporaryDirectory() as tmp:
            root = self._wiki(tmp)
            before = (root / "log.md").read_text(encoding="utf-8")
            res = run_kg(["log", "ingest", "t/concepts/a", "t/concepts/missing",
                          "--source", "s", "--layer", "global"], root=root)
            self.assertNotEqual(res.returncode, 0)
            self.assertEqual((root / "log.md").read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()

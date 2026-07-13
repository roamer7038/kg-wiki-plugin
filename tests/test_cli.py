"""CLI 規約: exit code・stdout/stderr 分離・--json の JSONL 妥当性・Phase ゲート
（03 §4.1、§6.3、04 §1.3。T1・T13）。"""

import json
import tempfile
import unittest
from pathlib import Path

from helpers import PLUGIN_ROOT, copy_fixture, run_kg


class TestExitCodes(unittest.TestCase):
    def test_usage_errors_exit3(self):
        cases = [
            ["nosuchcommand"],
            ["search"],                      # query 欠落
            ["traverse", "llm/concepts/x", "--hops", "9"],
            ["traverse", "not-a-ref"],
            ["path", "llm/a/b"],             # ref2 欠落
            ["move", "llm/concepts/a"],      # new-ref 欠落
            ["new", "llm/concepts/a", "--date", "2026-13-99"],
        ]
        for args in cases:
            with self.subTest(args=args):
                result = run_kg(args)
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertIn("error:", result.stderr)

    def test_no_subcommand_exit3(self):
        result = run_kg([])
        self.assertEqual(result.returncode, 3)

    def test_phase_gates_exit4(self):
        for args in (["hook-context"],):
            with self.subTest(args=args):
                result = run_kg(args)
                self.assertEqual(result.returncode, 4, result.stderr)
                self.assertIn("Phase", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_qmd_disabled_exit4(self):
        # qmd 無効（既定）では vsearch / hybrid のみ exit 4 + 有効化手順（03 §6.3）
        with tempfile.TemporaryDirectory() as tmp:
            for args in (["vsearch", "q"], ["hybrid", "q"]):
                with self.subTest(args=args):
                    result = run_kg(args, root=Path(tmp) / "w")
                    self.assertEqual(result.returncode, 4, result.stderr)
                    self.assertIn("有効化", result.stderr)
                    self.assertEqual(result.stdout, "")

    def test_version(self):
        result = run_kg(["--version"])
        self.assertEqual(result.returncode, 0)
        import sys
        sys.path.insert(0, str(PLUGIN_ROOT / "lib"))
        import kgwiki
        self.assertEqual(result.stdout.strip(), kgwiki.__version__)

    def test_layer_project_missing_exit1(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_kg(["search", "x", "--layer", "project"],
                            root=Path(tmp), project_dir=Path(tmp))
            self.assertEqual(result.returncode, 1)


class TestStreams(unittest.TestCase):
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

    def test_stdout_is_pipeable_results_only(self):
        # プロジェクト層なしの診断は stderr（stdout は結果のみ）
        with tempfile.TemporaryDirectory() as tmp:
            result = run_kg(["search", "graphrag"], root=self.fix / "global",
                            project_dir=Path(tmp))
            self.assertIn("プロジェクト層なし", result.stderr)
            for line in result.stdout.splitlines():
                self.assertRegex(line, r"^\d+\.\d\d\t\[\[")
            # --quiet で stderr 診断も抑制
            result = run_kg(["search", "graphrag", "--quiet"],
                            root=self.fix / "global", project_dir=Path(tmp))
            self.assertEqual(result.stderr, "")

    def test_json_is_valid_jsonl(self):
        for args in (["search", "graphrag", "--json"],
                     ["traverse", "llm/concepts/graphrag", "--json"],
                     ["path", "llm/entities/microsoft", "llm/concepts/rag", "--json"],
                     ["validate", "--json"],
                     ["build", "--layer", "global", "--json"]):
            with self.subTest(args=args):
                result = self.kg(args)
                for line in result.stdout.splitlines():
                    record = json.loads(line)  # 不正 JSON なら例外
                    self.assertIsInstance(record, dict)
                    # キーは辞書順（03 §3.1）
                    self.assertEqual(list(record), sorted(record))


class TestVersionSync(unittest.TestCase):
    def test_plugin_json_matches_package(self):
        import sys
        sys.path.insert(0, str(PLUGIN_ROOT / "lib"))
        import kgwiki
        manifest = json.loads((PLUGIN_ROOT / ".claude-plugin/plugin.json")
                              .read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], kgwiki.__version__)
        self.assertEqual(manifest["name"], "kg-wiki")


if __name__ == "__main__":
    unittest.main()

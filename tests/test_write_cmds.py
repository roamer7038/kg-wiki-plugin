"""書き込み系規約: init 冪等・new 衝突・ロック・log 書式・--date 決定論（03 §7.2。T10）。"""

import tempfile
import unittest
from pathlib import Path

from helpers import run_kg, tree_bytes


class TestInit(unittest.TestCase):
    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wiki"
            args = ["init", "--layer", "global", "--topic", "llm",
                    "--date", "2026-07-13"]
            first = run_kg(args, root=root)
            self.assertEqual(first.returncode, 0, first.stderr)
            state = tree_bytes(root)
            second = run_kg(args, root=root)
            self.assertEqual(second.returncode, 0)
            self.assertEqual(state, tree_bytes(root))  # 2 回目は変更なし

    def test_appends_topic_to_existing_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wiki"
            run_kg(["init", "--layer", "global", "--topic", "llm",
                    "--date", "2026-07-13"], root=root)
            result = run_kg(["init", "--layer", "global", "--topic", "tools",
                             "--date", "2026-07-14"], root=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            config = (root / "config.yml").read_text(encoding="utf-8")
            self.assertIn("- name: llm", config)
            self.assertIn("- name: tools", config)
            # 検証にも通ること
            v = run_kg(["validate", "--layer", "global"], root=root)
            self.assertEqual(v.returncode, 0, v.stdout)
            # init の log 記録は新規作成時のみ（1 行のまま）
            log = (root / "log.md").read_text(encoding="utf-8")
            self.assertEqual(log, "- 2026-07-13 [init] root — topics: llm\n")

    def test_gitignore_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wiki"
            run_kg(["init", "--layer", "global"], root=root)
            expected = (".kg-lock\ntopics/*/_derived/*\n"
                        "!topics/*/_derived/communities/\n!topics/*/_derived/skills/\n")
            self.assertEqual((root / ".gitignore").read_text(encoding="utf-8"),
                             expected)

    def test_bad_topic_name_exit3(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_kg(["init", "--layer", "global", "--topic", "Bad_Name"],
                            root=Path(tmp) / "wiki")
            self.assertEqual(result.returncode, 3)

    def test_with_qmd_absent_exit4(self):
        from helpers import clean_env
        with tempfile.TemporaryDirectory() as tmp:
            env = clean_env()
            env["PATH"] = "/usr/bin:/bin"  # qmd を含まない PATH
            result = run_kg(["init", "--layer", "global", "--with-qmd"],
                            root=Path(tmp) / "wiki", env=env)
            self.assertEqual(result.returncode, 4)

    def test_with_qmd_enables_config(self):
        import os
        import stat
        from helpers import clean_env
        with tempfile.TemporaryDirectory() as tmp:
            stub_dir = Path(tmp) / "bin"
            stub_dir.mkdir()
            stub = stub_dir / "qmd"
            stub.write_text(
                '#!/bin/sh\ncase "$1" in\n'
                '  --version) echo "qmd 9.9.9 (stub)";;\n'
                '  collection) [ "$2" = "list" ] && echo "" || echo ok;;\n'
                '  vsearch|query) echo "[]";;\n'
                '  *) echo ok;;\n'
                'esac\nexit 0\n', encoding="utf-8")
            stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
            env = clean_env()
            env["PATH"] = f"{stub_dir}:/usr/bin:/bin"
            root = Path(tmp) / "wiki"
            result = run_kg(["init", "--layer", "global", "--topic", "llm",
                             "--with-qmd", "--date", "2026-07-13"],
                            root=root, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            config = (root / "config.yml").read_text(encoding="utf-8")
            self.assertIn("enabled: true", config)
            self.assertIn("version_range:", config)
            # 有効化後は vsearch が実行できる（スタブは空結果）
            result = run_kg(["vsearch", "q", "--layer", "global"], root=root,
                            env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")


class TestNewAndLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "wiki"
        run_kg(["init", "--layer", "global", "--topic", "llm",
                "--date", "2026-07-13"], root=self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_and_collision(self):
        result = run_kg(["new", "llm/concepts/rag", "--title", "RAG",
                         "--date", "2026-07-13", "--layer", "global"],
                        root=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = Path(result.stdout.strip())
        self.assertTrue(path.is_absolute())
        self.assertTrue(path.is_file())
        # 生成ページは validate に通る（derived-stale 警告のみは意図どおり）
        v = run_kg(["validate", "--layer", "global"], root=self.root)
        self.assertEqual(v.returncode, 0, v.stdout)
        # 衝突は exit 2
        again = run_kg(["new", "llm/concepts/rag", "--layer", "global"],
                       root=self.root)
        self.assertEqual(again.returncode, 2)
        self.assertIn("ref-exists", again.stdout)

    def test_new_precheck(self):
        result = run_kg(["new", "nosuch/concepts/x", "--layer", "global"],
                        root=self.root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("topic-undefined", result.stdout)
        result = run_kg(["new", "llm/badtype/x", "--layer", "global"],
                        root=self.root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("type-undefined", result.stdout)

    def test_new_does_not_build(self):
        run_kg(["new", "llm/concepts/rag", "--layer", "global"], root=self.root)
        self.assertFalse((self.root / "topics/llm/_derived").exists())

    def test_lock_failure_exit1(self):
        (self.root / ".kg-lock").write_text("pid=99999\n", encoding="utf-8")
        result = run_kg(["new", "llm/concepts/x", "--layer", "global"],
                        root=self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("ロック", result.stderr)

    def test_log_ingest_format_and_missing_ref(self):
        run_kg(["new", "llm/concepts/rag", "--date", "2026-07-13",
                "--layer", "global"], root=self.root)
        result = run_kg(["log", "ingest", "llm/concepts/rag",
                         "--source", "https://example.com/rag",
                         "--date", "2026-07-13"], root=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        log = (self.root / "log.md").read_text(encoding="utf-8")
        self.assertEqual(log.splitlines(), [
            "- 2026-07-13 [init] root — topics: llm",
            "- 2026-07-13 [new] llm/concepts/rag",
            "- 2026-07-13 [ingest] llm/concepts/rag — https://example.com/rag",
        ])
        # 不在 ref は exit 1
        result = run_kg(["log", "ingest", "llm/concepts/none",
                         "--source", "x"], root=self.root)
        self.assertEqual(result.returncode, 1)
        # ingest 以外の op は exit 3
        result = run_kg(["log", "move", "llm/concepts/rag", "--source", "x"],
                        root=self.root)
        self.assertEqual(result.returncode, 3)

    def test_date_explicit_full_determinism(self):
        # --date 明示で同一入力 → 同一出力（ツリー全体のバイト一致。NFR-2）
        trees = []
        for name in ("a", "b"):
            root = Path(self.tmp.name) / name
            run_kg(["init", "--layer", "global", "--topic", "llm",
                    "--date", "2026-01-01"], root=root)
            run_kg(["new", "llm/concepts/rag", "--title", "RAG",
                    "--summary", "検索拡張生成", "--keywords", "RAG,検索",
                    "--date", "2026-01-01", "--layer", "global"], root=root)
            run_kg(["build", "--layer", "global"], root=root)
            trees.append(tree_bytes(root))
        self.assertEqual(trees[0], trees[1])


if __name__ == "__main__":
    unittest.main()

"""qmd 連携: 縮退（exit 4）・チャンク→ref 写像・コレクション命名（02 §2.3、04 §8。Phase 2）。

写像テストは qmd 出力フィクスチャ（JSON）に対して行い、qmd 実体を必要としない
（03 §7.2「qmd 写像」）。
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURES, LIB, clean_env, copy_fixture, run_kg  # noqa: F401
from kgwiki import config as config_mod
from kgwiki import qmdfacade
from kgwiki.layers import Layer


class TestDegrade(unittest.TestCase):
    def test_enabled_but_qmd_absent_exit4(self):
        # config で有効化しても PATH に qmd が無ければ exit 4（AND 条件。02 §2.3）
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "w"
            run_kg(["init", "--layer", "global", "--topic", "llm"], root=root)
            config_path = root / "config.yml"
            config_path.write_text(
                config_path.read_text(encoding="utf-8")
                .replace("enabled: false", "enabled: true"), encoding="utf-8")
            env = clean_env()
            env["PATH"] = "/usr/bin:/bin"  # qmd を含まない PATH
            result = run_kg(["vsearch", "q"], root=root, env=env)
            self.assertEqual(result.returncode, 4, result.stderr)
            self.assertIn("@tobilu/qmd", result.stderr)

    def test_env_var_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "w"
            run_kg(["init", "--layer", "global"], root=root)
            env = clean_env()
            env["KG_WIKI_ENABLE_QMD"] = "true"
            env["PATH"] = "/usr/bin:/bin"
            result = run_kg(["hybrid", "q"], root=root, env=env)
            self.assertEqual(result.returncode, 4)
            self.assertIn("@tobilu/qmd", result.stderr)  # 有効だが qmd 不在の案内
            # 明示 false は config より優先
            env["KG_WIKI_ENABLE_QMD"] = "false"
            result = run_kg(["vsearch", "q"], root=root, env=env)
            self.assertEqual(result.returncode, 4)
            self.assertIn("有効化", result.stderr)

    def test_other_commands_unaffected(self):
        # qmd 不在でも他コマンドは無影響（03 §6.3）
        with tempfile.TemporaryDirectory() as tmp:
            fix = copy_fixture("wiki-mini", Path(tmp))
            env = clean_env(project_dir=fix / "project")
            env["PATH"] = "/usr/bin:/bin"
            for args in (["build", "--layer", "global"], ["search", "graphrag"],
                         ["validate", "--layer", "global"]):
                result = run_kg(args, root=fix / "global", env=env)
                self.assertIn(result.returncode, (0,), f"{args}: {result.stderr}")


class TestMapping(unittest.TestCase):
    def items(self, root):
        text = (FIXTURES / "qmd" / "vsearch.json").read_text(encoding="utf-8")
        return json.loads(text.replace("{root}", str(root)))

    def test_map_dedupe_and_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mapped, unmapped = qmdfacade.map_results(
                self.items(root), [("global", root)])
            refs = [(ref, score) for score, ref, _kind in mapped]
            # 同一 ref は最高スコア 1 件に重複排除、最良ランクの返却順を維持
            self.assertEqual([r for r, _s in refs],
                             ["llm/concepts/graphrag", "llm/concepts/rag",
                              "llm/papers/lightrag"])
            self.assertEqual(dict(refs)["llm/concepts/graphrag"], 0.92)
            # パターン外・非正準 slug は破棄（04 §8.3）
            self.assertEqual(len(unmapped), 2)

    def test_snippet_not_leaked(self):
        # 写像結果に本文スニペットを含めない（A-7）
        with tempfile.TemporaryDirectory() as tmp:
            mapped, _ = qmdfacade.map_results(self.items(Path(tmp)),
                                              [("global", Path(tmp))])
            for entry in mapped:
                self.assertEqual(len(entry), 3)  # (score, ref, kind) のみ


class TestCollectionName(unittest.TestCase):
    def test_names(self):
        import hashlib
        self.assertEqual(
            qmdfacade.collection_name(Layer("global", Path("/anywhere"))),
            "kgwiki-global")
        with tempfile.TemporaryDirectory() as tmp:
            kg_root = Path(tmp) / "proj" / ".kg-wiki"
            kg_root.mkdir(parents=True)
            name = qmdfacade.collection_name(Layer("project", kg_root))
            expected = hashlib.sha256(
                str((Path(tmp) / "proj").resolve()).encode("utf-8")).hexdigest()[:8]
            self.assertEqual(name, f"kgwiki-{expected}")
            self.assertEqual(name, name.lower())


class TestEnableQmdText(unittest.TestCase):
    def test_rewrites_existing_block(self):
        text = config_mod.initial_config_text(["llm"])
        result = config_mod.enable_qmd_text(text, "2.5")
        self.assertIn("  enabled: true", result)
        self.assertIn("  version_range: 2.5", result)
        self.assertNotIn("enabled: false", result)
        # サブセットとして妥当なまま
        from kgwiki import yamlsub
        _data, issues = yamlsub.parse_document(result)
        self.assertEqual(issues, [])

    def test_appends_block_when_missing(self):
        text = "version: 1\ntopics: []\ntypes: [concepts]\nrelations: [is_a]\n"
        result = config_mod.enable_qmd_text(text, "")
        self.assertIn("qmd:\n  enabled: true\n  version_range: \"\"", result)


if __name__ == "__main__":
    unittest.main()

"""kg hook-context: 項抽出・空出力条件・常に exit 0（03 §4.15、04 §9。T4）。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import BIN_KG, clean_env, copy_fixture, run_kg
from kgwiki import hookctx, output

NOTICE = list(output.TRUST_NOTICE)


def hook_json(prompt):
    return json.dumps({"session_id": "s1", "hook_event_name": "UserPromptSubmit",
                       "prompt": prompt}, ensure_ascii=False)


class TestExtractTerms(unittest.TestCase):
    """04 §9.2: NFC 正規化 + 英数 3 文字以上 / CJK 2 文字以上の run、先頭 8 項（A-14）。"""

    def test_alnum_runs_need_three_chars(self):
        self.assertEqual(hookctx.extract_terms("go to GraphRAG v2 now"),
                         ["graphrag", "now"])

    def test_cjk_runs_need_two_chars(self):
        self.assertEqual(hookctx.extract_terms("の 増分更新 を"), ["増分更新"])

    def test_mixed_order_preserved(self):
        # CJK は「連続 run」単位で切る（助詞も run に含まれる。04 §9.2）
        self.assertEqual(hookctx.extract_terms("GraphRAG とは何か？ RAG の増分更新"),
                         ["graphrag", "とは何か", "rag", "の増分更新"])

    def test_dedup_keeps_first_occurrence(self):
        self.assertEqual(hookctx.extract_terms("rag graphrag rag"),
                         ["rag", "graphrag"])

    def test_truncated_to_eight_terms(self):
        prompt = " ".join(f"term{i:02d}" for i in range(20))
        self.assertEqual(len(hookctx.extract_terms(prompt)), hookctx.MAX_TERMS)
        self.assertEqual(hookctx.extract_terms(prompt)[0], "term00")

    def test_empty_prompt_yields_no_terms(self):
        self.assertEqual(hookctx.extract_terms(""), [])
        self.assertEqual(hookctx.extract_terms("a の 1"), [])


class TestBudget(unittest.TestCase):
    def test_expired_deadline_returns_empty(self):
        # 500ms 予算を使い切った状態を模す（部分結果を返さない。03 §4.15）
        self.assertEqual(hookctx.run(hook_json("graphrag"), start=-10 ** 6), "")


class TestEnabled(unittest.TestCase):
    def test_default_enabled_when_env_unset(self):
        self.assertTrue(hookctx.enabled({}))

    def test_disabled_by_env(self):
        for value in ("false", "0", "no", "off", "False"):
            self.assertFalse(hookctx.enabled({hookctx.ENV_ENABLE: value}), value)

    def test_enabled_by_env(self):
        for value in ("true", "1", "yes", "on"):
            self.assertTrue(hookctx.enabled({hookctx.ENV_ENABLE: value}), value)


class HookBase(unittest.TestCase):
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

    def hook(self, stdin_text, env_extra=None, root=None):
        env = clean_env(self.fix / "project")
        env.update(env_extra or {})
        cmd = [sys.executable, str(BIN_KG), "hook-context",
               "--root", str(root if root is not None else self.fix / "global")]
        return subprocess.run(cmd, input=stdin_text, capture_output=True,
                              text=True, env=env)


class TestHookOutput(HookBase):
    def test_hit_emits_notice_and_pointers(self):
        result = self.hook(hook_json("GraphRAG について教えて"))
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.rstrip("\n").split("\n")
        self.assertEqual(lines[:2], NOTICE)
        pointers = lines[2:]
        self.assertTrue(pointers)
        self.assertLessEqual(len(pointers), 5)  # limit 5（03 §4.15）
        for line in pointers:
            self.assertRegex(line, r"^- \[\[[a-z0-9-]+/[a-z0-9-]+/[a-z0-9-]+\]\]")
        self.assertIn("- [[llm/concepts/graphrag]] — ", result.stdout)

    def test_both_layers_are_searched(self):
        result = self.hook(hook_json("kg-wiki プロジェクト固有"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("proj/", result.stdout)

    def test_deterministic(self):
        first = self.hook(hook_json("GraphRAG について教えて"))
        second = self.hook(hook_json("GraphRAG について教えて"))
        self.assertEqual(first.stdout, second.stdout)


class TestAlwaysExitZeroWithEmptyOutput(HookBase):
    """常に exit 0。無効化・0 件・内部エラー・不正入力のいずれでも空出力。"""

    def assert_silent(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_no_hits(self):
        self.assert_silent(self.hook(hook_json("zzzznomatchxyzzy")))

    def test_no_terms_in_prompt(self):
        self.assert_silent(self.hook(hook_json("a の 1")))

    def test_disabled_by_user_config(self):
        result = self.hook(hook_json("GraphRAG について教えて"),
                           env_extra={hookctx.ENV_ENABLE: "false"})
        self.assert_silent(result)

    def test_broken_json(self):
        self.assert_silent(self.hook("{not json"))

    def test_empty_stdin(self):
        self.assert_silent(self.hook(""))

    def test_missing_prompt_field(self):
        self.assert_silent(self.hook(json.dumps({"hook_event_name": "X"})))

    def test_prompt_is_not_a_string(self):
        self.assert_silent(self.hook(json.dumps({"prompt": {"a": 1}})))

    def test_missing_wiki_root(self):
        result = self.hook(hook_json("GraphRAG"),
                           root=Path(self.tmp.name) / "nonexistent")
        self.assert_silent(result)

    def test_prompt_is_not_passed_as_argument(self):
        """プロンプトは stdin からのみ読む（未検証文字列を引数化しない。02 §6.6）。"""
        env = clean_env(self.fix / "project")
        result = subprocess.run(
            [sys.executable, str(BIN_KG), "hook-context", "graphrag",
             "--root", str(self.fix / "global")],
            input=hook_json("graphrag"), capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 3)  # 位置引数は受け付けない


if __name__ == "__main__":
    unittest.main()

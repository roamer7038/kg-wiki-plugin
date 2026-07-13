"""kg pack: 収集規則・バイト計上・省略一覧・注意書き。"""

import tempfile
import unittest
from pathlib import Path

from helpers import copy_fixture, run_kg
from kgwiki import output, pack

NOTICE = list(output.TRUST_NOTICE)


class PackBase(unittest.TestCase):
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

    def pack(self, args):
        return run_kg(["pack"] + args, root=self.fix / "global",
                      project_dir=self.fix / "project")

    def toc_refs(self, stdout):
        """固定部の目次に列挙された ref。"""
        lines = stdout.split("\n")
        start = next(i for i, line in enumerate(lines)
                     if line.startswith("## 収載ページ"))
        result = []
        for line in lines[start + 2:]:
            if not line.startswith("- [["):
                break
            result.append(line[4:-2])
        return result

    def page_refs(self, stdout):
        """本文が収載された（省略されなかった）ref。"""
        return [line[len("## [["):line.index("]] — ")]
                for line in stdout.split("\n")
                if line.startswith("## [[") and "]] — " in line]

    def omitted_refs(self, stdout):
        lines = stdout.split("\n")
        if pack.OMIT_HEADING not in lines:
            return []
        start = lines.index(pack.OMIT_HEADING)
        return [line[4:-2] for line in lines[start + 1:] if line.startswith("- [[")]


class TestTrustNotice(PackBase):
    def test_notice_is_first_two_lines_verbatim(self):
        result = self.pack(["graphrag"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split("\n")[:2], NOTICE)


class TestCollection(PackBase):
    def test_query_form_collects_search_top_m(self):
        result = self.pack(["graphrag", "--limit", "3"])
        self.assertEqual(result.returncode, 0, result.stderr)
        search = run_kg(["search", "graphrag", "--limit", "3"],
                        root=self.fix / "global", project_dir=self.fix / "project")
        expected = sorted(line.split("\t")[1][2:-2]
                          for line in search.stdout.strip().split("\n"))
        self.assertEqual(self.toc_refs(result.stdout), expected)
        self.assertEqual(self.page_refs(result.stdout), expected)

    def test_query_form_joins_multiple_terms(self):
        result = self.pack(["graphrag", "増分"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("llm/papers/lightrag", self.toc_refs(result.stdout))

    def test_ref_form_includes_seed_and_1hop_neighbors(self):
        result = self.pack(["llm/papers/lightrag"])
        self.assertEqual(result.returncode, 0, result.stderr)
        # 種 + 1 hop（derived_from → graphrag、本文リンク mentions → increment）
        self.assertEqual(self.toc_refs(result.stdout),
                         ["llm/concepts/graphrag", "llm/concepts/increment",
                          "llm/papers/lightrag"])

    def test_ref_form_hops_2_widens(self):
        one = self.toc_refs(self.pack(["llm/papers/lightrag"]).stdout)
        two = self.toc_refs(self.pack(["llm/papers/lightrag", "--hops", "2"]).stdout)
        self.assertTrue(set(one) < set(two))

    def test_ref_form_union_dedup_and_ref_order(self):
        result = self.pack(["llm/papers/lightrag", "llm/concepts/graphrag"])
        refs = self.toc_refs(result.stdout)
        self.assertEqual(refs, sorted(set(refs)))
        self.assertIn("llm/papers/lightrag", refs)
        self.assertIn("llm/concepts/graphrag", refs)

    def test_missing_nodes_excluded(self):
        # graphrag-intro は未解決 ref（missing ノード）を参照する
        result = self.pack(["llm/articles/graphrag-intro"])
        self.assertEqual(result.returncode, 0, result.stderr)
        # 収載 ref はすべて実ページ（= 本文ブロックを持つ）
        self.assertEqual(self.toc_refs(result.stdout), self.page_refs(result.stdout))

    def test_zero_hits_exit_1(self):
        result = self.pack(["zzzznomatchxyzzy"])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")

    def test_no_positional_arg_exit_3(self):
        self.assertEqual(self.pack([]).returncode, 3)

    def test_deterministic(self):
        first = self.pack(["graphrag", "--limit", "5"])
        second = self.pack(["graphrag", "--limit", "5"])
        self.assertEqual(first.stdout, second.stdout)


class TestPageBlock(PackBase):
    def test_header_sources_and_body(self):
        result = self.pack(["llm/papers/graphrag-bench"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("## [[llm/papers/graphrag-bench]] — GraphRAG-Bench"
                      "（updated: 2026-07-01）", result.stdout)
        self.assertIn("### sources", result.stdout)
        self.assertIn("- https://arxiv.org/abs/2506.02404（accessed: 2026-07-01）",
                      result.stdout)
        self.assertIn("グラフが効くタスクと効かないタスクを切り分けるベンチマーク。",
                      result.stdout)

    def test_page_without_sources_has_no_sources_heading(self):
        result = self.pack(["llm/concepts/lonely"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("### sources", result.stdout)


class TestMaxBytes(PackBase):
    def test_page_boundary_truncation_and_omission_list(self):
        full = self.pack(["graphrag", "--limit", "5"])
        budget = len(full.stdout.encode("utf-8")) // 2
        result = self.pack(["graphrag", "--limit", "5", "--max-bytes", str(budget)])
        self.assertEqual(result.returncode, 0, result.stderr)
        # 目次は収集全 ref（採否によらず）
        self.assertEqual(self.toc_refs(result.stdout), self.toc_refs(full.stdout))
        kept = self.page_refs(result.stdout)
        omitted = self.omitted_refs(result.stdout)
        self.assertTrue(omitted)
        self.assertEqual(sorted(kept + omitted), self.toc_refs(full.stdout))
        # 採用分（固定部 + 省略部見出し + 採用ブロック）は予算内に収まる。
        # 省略行のバイトは予算を超えて計上され得るため、出力全体は B を超え得る
        omit_bytes = sum(pack.block_bytes([f"- [[{ref}]]"]) for ref in omitted)
        self.assertLessEqual(len(result.stdout.encode("utf-8")) - omit_bytes, budget)

    def test_omitted_pages_have_no_body_in_output(self):
        """ページ境界でのみ打ち切る（ページ内の切り詰めをしない）。"""
        full = self.pack(["graphrag", "--limit", "5"])
        budget = len(full.stdout.encode("utf-8")) // 2
        result = self.pack(["graphrag", "--limit", "5", "--max-bytes", str(budget)])
        for ref in self.omitted_refs(result.stdout):
            self.assertNotIn(f"## [[{ref}]] — ", result.stdout)
        for ref in self.page_refs(result.stdout):
            # 採用ページは単独 pack と同一のブロックがそのまま含まれる（部分切り詰めなし）
            single = self.pack([ref, "--hops", "1"]).stdout
            block = single[single.index(f"## [[{ref}]] — "):]
            block = block[:block.index("\n## ")] if "\n## " in block else block
            self.assertIn(block.rstrip("\n"), result.stdout)

    def test_tiny_budget_omits_all_and_warns_exit_0(self):
        result = self.pack(["graphrag", "--limit", "5", "--max-bytes", "10"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.page_refs(result.stdout), [])
        self.assertEqual(self.omitted_refs(result.stdout),
                         self.toc_refs(result.stdout))
        self.assertIn("--max-bytes", result.stderr)
        self.assertIn("超過", result.stderr)
        self.assertGreater(len(result.stdout.encode("utf-8")), 10)

    def test_no_omission_section_when_all_fit(self):
        result = self.pack(["graphrag", "--limit", "3", "--max-bytes", "100000"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(pack.OMIT_HEADING, result.stdout)


class TestOut(PackBase):
    def test_out_writes_file_and_keeps_stdout_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pack.md"
            result = self.pack(["graphrag", "--limit", "2", "--out", str(path)])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(path.read_text(encoding="utf-8").split("\n")[:2], NOTICE)


class TestSelectUnit(unittest.TestCase):
    """採否アルゴリズムの逐次貪欲を直接検証する。"""

    def test_omission_heading_and_line_bytes(self):
        self.assertEqual(pack.OMIT_HEADING, "## 省略（--max-bytes 超過）")
        self.assertEqual(pack.block_bytes([pack.OMIT_HEADING]),
                         len((pack.OMIT_HEADING + "\n").encode("utf-8")))
        self.assertEqual(pack.block_bytes(["- [[a/b/c]]"]), len(b"- [[a/b/c]]\n"))

    def test_no_budget_keeps_all(self):
        kept, omitted = pack.select(["a/b/1", "a/b/2"],
                                    {"a/b/1": 100, "a/b/2": 100}, 50, None)
        self.assertEqual((kept, omitted), (["a/b/1", "a/b/2"], []))

    def test_greedy_continues_after_omission(self):
        """途中の大きいページを省略しても、後続の小さいページは採用される。"""
        refs = ["a/b/1", "a/b/2", "a/b/3"]
        sizes = {"a/b/1": 10, "a/b/2": 1000, "a/b/3": 10}
        fixed = 20
        head = pack.block_bytes([pack.OMIT_HEADING])
        omit_line = pack.block_bytes(["- [[a/b/2]]"])
        budget = fixed + head + 10 + omit_line + 10
        kept, omitted = pack.select(refs, sizes, fixed, budget)
        self.assertEqual(kept, ["a/b/1", "a/b/3"])
        self.assertEqual(omitted, ["a/b/2"])

    def test_oversized_single_page_is_omitted_by_same_rule(self):
        kept, omitted = pack.select(["a/b/1"], {"a/b/1": 10 ** 6}, 20, 100)
        self.assertEqual((kept, omitted), ([], ["a/b/1"]))


if __name__ == "__main__":
    unittest.main()

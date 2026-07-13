"""コミュニティ検出の unit test: 手計算例・ID 導出・継承規則。"""

import hashlib
import unittest

from helpers import LIB  # noqa: F401
from kgwiki import community


def weights_from(pairs):
    """{(a, b): w}（a < b に正規化）。"""
    result = {}
    for a, b, w in pairs:
        key = (a, b) if a < b else (b, a)
        result[key] = result.get(key, 0) + w
    return result


class TestCnmHandCalc(unittest.TestCase):
    def test_example_04_5_1(self):
        # ノード A,B,C,D。エッジ重み A–B=2, A–C=1, C–D=1 → {A,B}, {C,D} で停止
        weights = weights_from([("a", "b", 2), ("a", "c", 1), ("c", "d", 1)])
        result = community.detect(weights)
        self.assertEqual(result, [["a", "b"], ["c", "d"]])

    def test_deterministic_repeat(self):
        weights = weights_from([
            ("n1", "n2", 1), ("n2", "n3", 1), ("n3", "n1", 1),
            ("n4", "n5", 2), ("n3", "n4", 1),
        ])
        first = community.detect(weights)
        for _ in range(5):
            self.assertEqual(community.detect(weights), first)

    def test_isolated_nodes_excluded(self):
        # weights に現れないノード（エッジ 0）は所属しない
        result = community.detect(weights_from([("a", "b", 1)]))
        self.assertEqual(result, [["a", "b"]])

    def test_empty_graph(self):
        self.assertEqual(community.detect({}), [])

    def test_tie_break_lexicographic(self):
        # 同一 ΔQ~ のペアは最小 ref の辞書順ペアが小さい方を先にマージする
        # a–b と c–d が対称（同重み・同次数）→ (a,b) が先。結果は同じ 2 コミュニティ
        weights = weights_from([("a", "b", 1), ("c", "d", 1)])
        self.assertEqual(community.detect(weights), [["a", "b"], ["c", "d"]])


class TestIdDerivation(unittest.TestCase):
    def test_id_formula(self):
        members = ["llm/concepts/rag", "llm/concepts/graphrag"]
        joined = "llm/concepts/graphrag\nllm/concepts/rag"
        expected = "c-" + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:8]
        self.assertEqual(community.community_id(members), expected)


class TestInheritance(unittest.TestCase):
    def old(self, mapping):
        return {"algorithm": "cnm-v1", "communities": mapping, "schema_version": 1}

    def test_inherit_when_jaccard_at_least_half(self):
        # 旧 {a,b,c} → 新 {a,b,c,d}: J = 3/4 ≥ 0.5 → 旧 ID 継承
        new = [["a", "b", "c", "d"]]
        ids = community.assign_ids(new, self.old({"c-old00001": ["a", "b", "c"]}))
        self.assertEqual(ids[0], "c-old00001")

    def test_no_inherit_below_half(self):
        # 旧 {a,b,c,d,e} → 新 {a,f}: J = 1/6 < 0.5 → 新規導出
        new = [["a", "f"]]
        ids = community.assign_ids(new, self.old({"c-old00001": ["a", "b", "c", "d", "e"]}))
        self.assertEqual(ids[0], community.community_id(["a", "f"]))

    def test_boundary_exactly_half(self):
        # J = 1/2 ちょうどは継承する（≥ 0.5）
        new = [["a", "b"]]  # 旧 {a,b,c,d} との J = 2/4 = 0.5
        ids = community.assign_ids(new, self.old({"c-old00001": ["a", "b", "c", "d"]}))
        self.assertEqual(ids[0], "c-old00001")

    def test_old_id_used_at_most_once(self):
        # 旧 {a,b,c,d} が新 {a,b} と {c,d} に分裂: 両方 J=0.5 →
        # Jaccard 同点は新コミュニティ最小 ref 昇順で {a,b} が継承、{c,d} は新規
        new = [["a", "b"], ["c", "d"]]
        ids = community.assign_ids(new, self.old({"c-old00001": ["a", "b", "c", "d"]}))
        self.assertEqual(ids[0], "c-old00001")
        self.assertEqual(ids[1], community.community_id(["c", "d"]))

    def test_greedy_by_jaccard_desc(self):
        # 高い Jaccard のマッチを優先する
        new = [["a", "b", "c"], ["d", "e"]]
        old = self.old({
            "c-11111111": ["a", "b", "c"],      # 新0 と J=1
            "c-22222222": ["d", "e", "a"],      # 新1 と J=2/3、新0 と J=2/4
        })
        ids = community.assign_ids(new, old)
        self.assertEqual(ids[0], "c-11111111")
        self.assertEqual(ids[1], "c-22222222")

    def test_no_old_assignment(self):
        new = [["a", "b"]]
        ids = community.assign_ids(new, None)
        self.assertEqual(ids[0], community.community_id(["a", "b"]))


class TestMdParsing(unittest.TestCase):
    def md(self, summary_lines):
        return community.community_md_text(
            "llm", "c-12345678", ["llm/concepts/a", "llm/concepts/b"],
            {"llm/concepts/a": {"hash": "sha256:" + "0" * 64, "summary": "要約A"},
             "llm/concepts/b": {"hash": "sha256:" + "1" * 64, "summary": "要約B"}},
            [("llm/concepts/a", "uses", "llm/concepts/b", "frontmatter")],
            summary_lines)

    def test_roundtrip_preserves_summary(self):
        text = self.md(["俯瞰要約の本文。", "2 行目。"])
        self.assertEqual(community.summary_region(text), ["俯瞰要約の本文。", "2 行目。"])
        _fm, skeleton, _su, errors = community.parse_community_md(text)
        self.assertEqual(errors, [])
        self.assertIn("- [[llm/concepts/a]] — 要約A", skeleton)
        self.assertIn("| uses | 1 |", skeleton)

    def test_marker_errors(self):
        text = self.md([]).replace(community.MARK_SU_END + "\n", "")
        _fm, _sk, _su, errors = community.parse_community_md(text)
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()

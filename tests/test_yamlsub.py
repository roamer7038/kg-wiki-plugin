"""yamlsub: YAML サブセット境界のテーブル駆動テスト。"""

import datetime
import unittest

from helpers import LIB  # noqa: F401
from kgwiki import yamlsub


def parse(text):
    return yamlsub.parse_document(text)


class TestScalars(unittest.TestCase):
    def test_type_inference(self):
        data, issues = parse("a: true\nb: false\nc: -42\nd: 2026-07-13\ne: text\n")
        self.assertEqual(issues, [])
        self.assertIs(data["a"], True)
        self.assertIs(data["b"], False)
        self.assertEqual(data["c"], -42)
        self.assertEqual(data["d"], datetime.date(2026, 7, 13))
        self.assertEqual(data["e"], "text")

    def test_nonexistent_date_falls_to_str(self):
        data, issues = parse("d: 2026-02-30\n")
        self.assertEqual(issues, [])
        self.assertEqual(data["d"], "2026-02-30")  # 実在検証で str に落ちる

    def test_quoted_always_str(self):
        data, issues = parse('a: "true"\nb: \'2026-07-13\'\nc: "42"\n')
        self.assertEqual(issues, [])
        self.assertEqual(data["a"], "true")
        self.assertEqual(data["b"], "2026-07-13")
        self.assertEqual(data["c"], "42")

    def test_pb1_colon_space(self):
        # PB1: 未引用の ": " はエラー、行途中の ':' 単独は許容
        _data, issues = parse("t: RAG vs GraphRAG: 評価\n")
        self.assertEqual(len(issues), 1)
        data, issues = parse("t: a:b\nu: C#\n")
        self.assertEqual(issues, [])
        self.assertEqual(data["t"], "a:b")
        self.assertEqual(data["u"], "C#")

    def test_pb2_trailing_space_trimmed(self):
        data, issues = parse("t: value   \n")
        self.assertEqual(issues, [])
        self.assertEqual(data["t"], "value")

    def test_pb3_space_hash(self):
        # PB3: 未引用値中の " #"（行末コメント）はエラー。引用すれば可
        _data, issues = parse("t: value # comment\n")
        self.assertEqual(len(issues), 1)
        data, issues = parse('t: "value # not comment"\n')
        self.assertEqual(issues, [])
        self.assertEqual(data["t"], "value # not comment")

    def test_escapes(self):
        data, issues = parse('a: "say \\"hi\\""\nb: "back\\\\slash"\nc: \'it\'\'s\'\n')
        self.assertEqual(issues, [])
        self.assertEqual(data["a"], 'say "hi"')
        self.assertEqual(data["b"], "back\\slash")
        self.assertEqual(data["c"], "it's")

    def test_invalid_escape(self):
        _data, issues = parse('a: "bad \\n escape"\n')
        self.assertEqual(len(issues), 1)

    def test_forbidden_first_chars(self):
        for value, expected in [("&anchor", "アンカー"), ("*alias", "アンカー"),
                                ("!tag", "タグ"), ("|", "ブロックスカラー"),
                                (">fold", "ブロックスカラー")]:
            _data, issues = parse(f"a: {value}\n")
            self.assertEqual(len(issues), 1, value)
            self.assertIn(expected, issues[0].message)


class TestIndent(unittest.TestCase):
    def test_tab_indent(self):
        _data, issues = parse("a: 1\n\tb: 2\n")
        self.assertEqual(len(issues), 1)
        self.assertIn("タブ", issues[0].message)

    def test_odd_spaces(self):
        _data, issues = parse("a:\n   b: 2\n")
        self.assertTrue(any("2 スペース" in i.message for i in issues))

    def test_plus4_jump(self):
        _data, issues = parse("a:\n    b: 2\n")
        self.assertTrue(any("インデントが不正" in i.message for i in issues))

    def test_recovery_continues(self):
        # 規則 1: エラー行はキー・値とも登録せず読み飛ばし、以後は通常規則で継続
        data, issues = parse("a: &bad\nb: ok\n")
        self.assertEqual(len(issues), 1)
        self.assertEqual(data["b"], "ok")
        self.assertNotIn("a", data)


class TestInlineList(unittest.TestCase):
    def test_basic_and_empty(self):
        data, issues = parse("a: [x, y]\nb: []\n")
        self.assertEqual(issues, [])
        self.assertEqual(data["a"], ["x", "y"])
        self.assertEqual(data["b"], [])

    def test_trailing_comma(self):
        _data, issues = parse("a: [x, ]\n")
        self.assertEqual(len(issues), 1)
        self.assertIn("末尾カンマ", issues[0].message)

    def test_nested_flow(self):
        for text in ("a: [[x], y]\n", "a: [{k: v}]\n"):
            _data, issues = parse(text)
            self.assertEqual(len(issues), 1, text)
            self.assertIn("ネスト", issues[0].message)

    def test_quoted_elements(self):
        data, issues = parse('a: ["x, y", \'z\']\n')
        self.assertEqual(issues, [])
        self.assertEqual(data["a"], ["x, y", "z"])

    def test_missing_separator(self):
        _data, issues = parse('a: ["x" "y"]\n')
        self.assertEqual(len(issues), 1)

    def test_unclosed(self):
        _data, issues = parse("a: [x, y\n")
        self.assertEqual(len(issues), 1)


class TestStructure(unittest.TestCase):
    def test_nested_mapping(self):
        data, issues = parse("qmd:\n  enabled: false\n  version_range: \"\"\n")
        self.assertEqual(issues, [])
        self.assertEqual(data["qmd"], {"enabled": False, "version_range": ""})

    def test_list_of_mappings(self):
        text = ("relations:\n"
                "  - rel: is_a\n"
                "    to: llm/concepts/rag\n"
                "  - rel: uses\n"
                "    to: llm/concepts/kg\n")
        data, issues = parse(text)
        self.assertEqual(issues, [])
        self.assertEqual(data["relations"], [
            {"rel": "is_a", "to": "llm/concepts/rag"},
            {"rel": "uses", "to": "llm/concepts/kg"},
        ])

    def test_block_list_of_scalars(self):
        data, issues = parse("types:\n  - concepts\n  - papers\n")
        self.assertEqual(issues, [])
        self.assertEqual(data["types"], ["concepts", "papers"])

    def test_duplicate_key_keeps_first(self):
        data, issues = parse("a: 1\na: 2\n")
        self.assertEqual(len(issues), 1)
        self.assertIn("重複キー", issues[0].message)
        self.assertEqual(data["a"], 1)  # 規則 2: 最初の定義を保持

    def test_comment_lines_and_blank(self):
        data, issues = parse("# comment\n\na: 1\n  # indented comment\nb: 2\n")
        self.assertEqual(issues, [])
        self.assertEqual(data, {"a": 1, "b": 2})

    def test_no_space_after_colon(self):
        _data, issues = parse("a:1\n")
        self.assertEqual(len(issues), 1)

    def test_root_list_rejected(self):
        _data, issues = parse("- item\n")
        self.assertTrue(any("ルート" in i.message for i in issues))

    def test_issue_order_by_line(self):
        _data, issues = parse("a: &x\nb: ok\nc: !t\n")
        self.assertEqual([i.line for i in issues], sorted(i.line for i in issues))


class TestDumpScalar(unittest.TestCase):
    def test_quote_when_needed(self):
        self.assertEqual(yamlsub.dump_scalar("simple"), "simple")
        self.assertEqual(yamlsub.dump_scalar("A: B"), '"A: B"')
        self.assertEqual(yamlsub.dump_scalar("x # y"), '"x # y"')
        self.assertEqual(yamlsub.dump_scalar("true"), '"true"')
        self.assertEqual(yamlsub.dump_scalar("2026-07-13"), '"2026-07-13"')
        self.assertEqual(yamlsub.dump_scalar('say "hi"'), 'say "hi"')  # plain で合法
        self.assertEqual(yamlsub.dump_scalar('say "hi": x'), '"say \\"hi\\": x"')
        self.assertEqual(yamlsub.dump_scalar(True), "true")


if __name__ == "__main__":
    unittest.main()

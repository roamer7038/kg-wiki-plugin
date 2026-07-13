"""output.py: スコア丸め（Decimal・最近接偶数）の unit test。"""

import unittest

from helpers import LIB  # noqa: F401  (sys.path 設定)
from kgwiki import output


class TestRounding(unittest.TestCase):
    def test_half_even(self):
        # 最近接偶数丸め: 0.005 → 0.00、0.015 → 0.02、0.025 → 0.02
        self.assertEqual(output.fmt_score(0.005), "0.00")
        self.assertEqual(output.fmt_score(0.015), "0.02")
        self.assertEqual(output.fmt_score(0.025), "0.02")
        self.assertEqual(output.fmt_score(0.035), "0.04")

    def test_binary_float_trap(self):
        # 組み込み round() では 2.675 → 2.67 になる例（Decimal(str(x)) 経由で 2.68）
        self.assertEqual(output.fmt_score(2.675), "2.68")

    def test_two_decimals_always(self):
        self.assertEqual(output.fmt_score(6.0), "6.00")
        self.assertEqual(output.fmt_score(16.5), "16.50")
        self.assertEqual(output.fmt_score(0.8571428), "0.86")

    def test_score_json(self):
        self.assertEqual(output.score_json(16.5), 16.5)
        self.assertEqual(output.score_json(0.8571428), 0.86)

    def test_jsonl_sorted_compact_utf8(self):
        self.assertEqual(output.jsonl({"b": 1, "a": "あ"}), '{"a":"あ","b":1}')


if __name__ == "__main__":
    unittest.main()

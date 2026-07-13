"""パス頑健性: 空白・非 ASCII を含む root での build / 検索（NFR-6。03 §7.2）。"""

import tempfile
import unittest
from pathlib import Path

from helpers import run_kg


class TestPathRobustness(unittest.TestCase):
    def test_space_and_non_ascii_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "kg wiki (テスト用)" / "ルート"
            result = run_kg(["init", "--layer", "global", "--topic", "llm",
                             "--date", "2026-07-13"], root=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = run_kg(["new", "llm/concepts/rag", "--title", "RAG",
                             "--summary", "検索拡張生成", "--date", "2026-07-13",
                             "--layer", "global"], root=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = run_kg(["build", "--layer", "global"], root=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("built llm: 1 pages", result.stdout)
            result = run_kg(["search", "rag"], root=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("[[llm/concepts/rag]]", result.stdout)
            result = run_kg(["validate", "--layer", "global"], root=root)
            self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()

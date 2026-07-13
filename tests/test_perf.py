"""性能スモークテスト（1,000 ページで検索 < 1 秒・増分 build < 5 秒）。

実行時間が長いため、環境変数 KG_PERF=1 のときのみ実行する
（例: KG_PERF=1 python3 -m unittest tests.test_perf）。
"""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from helpers import PLUGIN_ROOT, run_kg


@unittest.skipUnless(os.environ.get("KG_PERF") == "1", "KG_PERF=1 のときのみ実行")
class TestPerformance(unittest.TestCase):
    def test_1000_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "perf-wiki"
            subprocess.run(
                [sys.executable, str(PLUGIN_ROOT / "tests/perf/gen_fixture.py"),
                 "--pages", "1000", "--root", str(root)],
                check=True, capture_output=True)

            result = run_kg(["build", "--layer", "global"], root=root)
            self.assertEqual(result.returncode, 0, result.stderr)

            # 増分 build（1 ページ変更）< 5 秒
            page = root / "topics/perf/pages/concepts/page-0000.md"
            page.write_text(page.read_text(encoding="utf-8") + "\n追記。\n",
                            encoding="utf-8")
            start = time.monotonic()
            result = run_kg(["build", "--layer", "global"], root=root)
            elapsed_build = time.monotonic() - start
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertLess(elapsed_build, 5.0, f"増分 build {elapsed_build:.2f}s")

            # 検索 < 1 秒
            start = time.monotonic()
            result = run_kg(["search", "ベクトル 検索"], root=root)
            elapsed_search = time.monotonic() - start
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertLess(elapsed_search, 1.0, f"search {elapsed_search:.2f}s")

            # traverse < 1 秒
            start = time.monotonic()
            result = run_kg(["traverse", "perf/concepts/page-0000",
                             "--hops", "3", "--limit", "20"], root=root)
            elapsed_traverse = time.monotonic() - start
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertLess(elapsed_traverse, 1.0, f"traverse {elapsed_traverse:.2f}s")

            print(f"\nperf: incremental build {elapsed_build:.2f}s, "
                  f"search {elapsed_search:.2f}s, traverse {elapsed_traverse:.2f}s",
                  file=sys.stderr)

    def test_dense_graph_community(self):
        # 密グラフでのコミュニティ検出 < 5 秒
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dense-wiki"
            subprocess.run(
                [sys.executable, str(PLUGIN_ROOT / "tests/perf/gen_fixture.py"),
                 "--pages", "500", "--edges-per-page", "30", "--root", str(root)],
                check=True, capture_output=True)
            start = time.monotonic()
            result = run_kg(["build", "--layer", "global"], root=root)
            elapsed = time.monotonic() - start
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertLess(elapsed, 5.0, f"dense build+detect {elapsed:.2f}s")
            print(f"\nperf: dense-graph build+community {elapsed:.2f}s",
                  file=sys.stderr)


if __name__ == "__main__":
    unittest.main()

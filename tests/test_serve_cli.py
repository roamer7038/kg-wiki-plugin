"""kg serve の CLI 契約（05 §2.1）。サーバは起動せず引数検証のみを見る。"""

import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURES, LIB, run_kg  # noqa: F401


class TestServeArgs(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "global"
        shutil.copytree(FIXTURES / "wiki-mini" / "global", self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_non_loopback_host_is_usage_error(self):
        r = run_kg(["serve", "--host", "0.0.0.0"], root=self.root)
        self.assertEqual(r.returncode, 3)
        self.assertIn("ループバック", r.stderr)

    def test_public_ip_host_is_usage_error(self):
        r = run_kg(["serve", "--host", "192.168.1.10"], root=self.root)
        self.assertEqual(r.returncode, 3)

    def test_localhost_is_accepted_as_loopback(self):
        """受理されること自体は --json 拒否で確認する（サーバは起動しない）。"""
        r = run_kg(["serve", "--host", "localhost", "--json"], root=self.root)
        self.assertEqual(r.returncode, 3)
        self.assertIn("--json", r.stderr)

    def test_json_option_is_rejected(self):
        r = run_kg(["serve", "--json"], root=self.root)
        self.assertEqual(r.returncode, 3)

    def test_limit_option_is_rejected(self):
        r = run_kg(["serve", "--limit", "5"], root=self.root)
        self.assertEqual(r.returncode, 3)

    def test_date_option_is_rejected(self):
        r = run_kg(["serve", "--date", "2026-07-24"], root=self.root)
        self.assertEqual(r.returncode, 3)

    def test_help_lists_serve(self):
        r = run_kg(["--help"])
        self.assertIn("serve", r.stdout)


if __name__ == "__main__":
    unittest.main()

"""kg validate: fixtures/invalid による issue コード網羅（03 §4.7、§7.2。T8）。"""

import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURES, copy_fixture, run_kg

# case ディレクトリ → (期待 code, 期待 severity, 期待 exit code)
CASES = {
    "config-schema": [("config-schema", "error", 2)],
    "fm-parse": [("fm-parse", "error", 2)],
    "fm-schema": [("fm-schema", "error", 2)],
    "slug-mismatch": [("slug-mismatch", "error", 2)],
    "type-mismatch": [("type-mismatch", "error", 2)],
    "ref-format": [("ref-format", "error", 2)],
    "rel-undefined": [("rel-undefined", "error", 2)],
    "rel-self": [("rel-self", "error", 2)],
    "link-broken-fm": [("link-broken-fm", "error", 2)],
    "link-broken-body": [("link-broken-body", "warn", 0)],
    "rel-duplicate": [("rel-duplicate", "warn", 0)],
    "keywords-duplicate": [("keywords-duplicate", "warn", 0)],
    "body-h1": [("body-h1", "warn", 0)],
    "page-orphan": [("page-orphan", "warn", 0)],
    "derived-stale": [("derived-stale", "warn", 0)],
    "info-codes": [("contradicts-pair", "info", 0), ("superseded-ref", "info", 0),
                   ("topic-empty", "info", 0)],
}


def parse_issues(stdout):
    issues = []
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 4:
            issues.append(tuple(parts))
    return issues


class TestIssueCodes(unittest.TestCase):
    def run_case(self, name):
        root = FIXTURES / "invalid" / name / "global"
        return run_kg(["validate", "--layer", "global"], root=root)

    def test_all_cases(self):
        for name, expectations in CASES.items():
            with self.subTest(case=name):
                result = self.run_case(name)
                issues = parse_issues(result.stdout)
                fired = {(sev, code) for sev, code, _t, _m in issues}
                for code, severity, exit_code in expectations:
                    self.assertIn((severity, code), fired,
                                  f"{name}: {result.stdout!r}")
                    self.assertEqual(result.returncode, exit_code, name)

    def test_shadow_two_layers(self):
        case = FIXTURES / "invalid" / "shadow"
        result = run_kg(["validate"], root=case / "global",
                        project_dir=case / "project")
        issues = parse_issues(result.stdout)
        self.assertIn(("warn", "shadow"), {(s, c) for s, c, _t, _m in issues})
        self.assertEqual(result.returncode, 0)

    def test_output_sorted(self):
        # severity（error→warn→info）→ code → target の順（03 §4.7）
        with tempfile.TemporaryDirectory() as tmp:
            fix = copy_fixture("wiki-mini", Path(tmp))
            result = run_kg(["validate"], root=fix / "global",
                            project_dir=fix / "project")
            issues = parse_issues(result.stdout)
            rank = {"error": 0, "warn": 1, "info": 2}
            keys = [(rank[s], c, t) for s, c, t, _m in issues]
            self.assertEqual(keys, sorted(keys))

    def test_quick_always_exit0(self):
        with tempfile.TemporaryDirectory() as tmp:
            fix = copy_fixture("wiki-mini", Path(tmp))
            result = run_kg(["validate", "--quick"], root=fix / "global",
                            project_dir=fix / "project")
            self.assertEqual(result.returncode, 0)
            self.assertRegex(result.stdout.strip(),
                             r"^kg: 2 layers, \d+ pages, derived: stale \(run kg build\)$")
            # build 後は fresh
            run_kg(["build", "--layer", "global"], root=fix / "global",
                   project_dir=fix / "project")
            run_kg(["build", "--layer", "project"], root=fix / "global",
                   project_dir=fix / "project")
            result = run_kg(["validate", "--quick"], root=fix / "global",
                            project_dir=fix / "project")
            self.assertEqual(result.returncode, 0)
            self.assertIn("derived: fresh", result.stdout)
            # 層解決が失敗しても exit 0（--layer project でプロジェクト層不在）
            result = run_kg(["validate", "--quick", "--layer", "project"],
                            root=fix / "global", project_dir=Path(tmp) / "noproj")
            self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()

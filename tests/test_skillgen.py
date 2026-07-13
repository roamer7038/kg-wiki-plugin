"""kg skillgen / kg validate --skills。"""

import tempfile
import unittest
from pathlib import Path

from helpers import copy_fixture, run_kg
from kgwiki import community, output

NOTICE = list(output.TRUST_NOTICE)


class SkillgenBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fix = copy_fixture("wiki-mini", Path(self.tmp.name))
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        for layer in ("global", "project"):
            result = self.kg(["build", "--layer", layer])
            self.assertEqual(result.returncode, 0, result.stderr)

    def tearDown(self):
        self.tmp.cleanup()

    def kg(self, args):
        return run_kg(args, root=self.fix / "global",
                      project_dir=self.fix / "project", home=self.home)

    def staging(self, name, topic="llm", layer="global"):
        base = (self.fix / layer) if layer == "global" else (self.fix / "project"
                                                             / ".kg-wiki")
        return base / "topics" / topic / "_derived" / "skills" / name / "SKILL.md"

    def installed(self, name):
        return self.home / ".claude" / "skills" / name / "SKILL.md"

    def write_llm_regions(self, path, description="LLM についての知識。",
                          summary="本文。[[llm/concepts/graphrag]] を参照。"):
        """LLM 執筆領域（description・summary）を埋める（LLM の執筆を模す）。"""
        lines = path.read_text(encoding="utf-8").split("\n")
        out = []
        in_summary = False
        for line in lines:
            if line.startswith("description: "):
                out.append(f"description: {description}")
                continue
            if line == community.MARK_SU_BEGIN:
                out.append(line)
                out.append(summary)
                in_summary = True
                continue
            if line == community.MARK_SU_END:
                in_summary = False
            if in_summary:
                continue  # 既存 summary 行は捨てる（差し替え）
            out.append(line)
        text = "\n".join(out)
        path.write_text(text, encoding="utf-8")
        return text


class TestGenerate(SkillgenBase):
    def test_topic_generates_staging_skeleton(self):
        result = self.kg(["skillgen", "topic:llm", "--layer", "global"])
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.staging("kg-llm")
        self.assertTrue(path.is_file(), result.stdout + result.stderr)
        text = path.read_text(encoding="utf-8")
        self.assertIn("name: kg-llm", text)
        self.assertIn("kg_source: topic:llm", text)
        self.assertIn("built_from: sha256:", text)
        # 信頼境界の注意書き（完全一致）
        for line in NOTICE:
            self.assertIn(line, text)
        # 4 マーカーと骨格の参照ページ一覧（ref + summary、ref 順）
        for mark in (community.MARK_SK_BEGIN, community.MARK_SK_END,
                     community.MARK_SU_BEGIN, community.MARK_SU_END):
            self.assertIn(mark, text)
        self.assertIn("- [[llm/concepts/graphrag]] — ", text)
        refs = [line[4:line.index("]]")] for line in text.split("\n")
                if line.startswith("- [[")]
        self.assertEqual(refs, sorted(refs))

    def test_name_rules_and_override(self):
        self.kg(["skillgen", "topic:llm", "--layer", "global"])
        self.assertTrue(self.staging("kg-llm").is_file())
        result = self.kg(["skillgen", "topic:llm", "--layer", "global",
                          "--name", "kg-custom"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.staging("kg-custom").is_file())

    def test_community_source(self):
        cid = self.community_id()
        result = self.kg(["skillgen", f"community:{cid}", "--layer", "global"])
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.staging(f"kg-llm-{cid}")
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn(f"kg_source: community:{cid}", text)

    def community_id(self):
        result = self.kg(["community", "llm/concepts/graphrag", "--json"])
        import json
        return json.loads(result.stdout)["community"]

    def test_unknown_source_exit_3(self):
        self.assertEqual(self.kg(["skillgen", "llm"]).returncode, 3)
        self.assertEqual(self.kg(["skillgen", "topic:"]).returncode, 3)

    def test_missing_topic_exit_1(self):
        self.assertEqual(
            self.kg(["skillgen", "topic:nosuch", "--layer", "global"]).returncode, 1)

    def test_deterministic(self):
        self.kg(["skillgen", "topic:llm", "--layer", "global"])
        first = self.staging("kg-llm").read_bytes()
        self.kg(["skillgen", "topic:llm", "--layer", "global"])
        self.assertEqual(self.staging("kg-llm").read_bytes(), first)

    def test_logs_skillgen(self):
        self.kg(["skillgen", "topic:llm", "--layer", "global", "--date",
                 "2026-07-14"])
        log = (self.fix / "global" / "log.md").read_text(encoding="utf-8")
        self.assertIn("- 2026-07-14 [skillgen] topic:llm → ", log)


class TestRegeneratePreservesLlmRegions(SkillgenBase):
    def test_description_and_summary_preserved_skeleton_updated(self):
        self.kg(["skillgen", "topic:llm", "--layer", "global"])
        path = self.staging("kg-llm")
        self.write_llm_regions(path)
        before = path.read_text(encoding="utf-8")

        # ソースページを変更 → build → 再生成
        page = (self.fix / "global" / "topics" / "llm" / "pages" / "concepts"
                / "graphrag.md")
        page.write_text(page.read_text(encoding="utf-8") + "\n追記行。\n",
                        encoding="utf-8")
        self.kg(["build", "--layer", "global"])
        result = self.kg(["skillgen", "topic:llm", "--layer", "global"])
        self.assertEqual(result.returncode, 0, result.stderr)

        after = path.read_text(encoding="utf-8")
        self.assertIn("description: LLM についての知識。", after)
        self.assertIn("本文。[[llm/concepts/graphrag]] を参照。", after)
        # built_from は更新される
        def built_from(text):
            return [line for line in text.split("\n")
                    if line.startswith("built_from: ")][0]
        self.assertNotEqual(built_from(before), built_from(after))


class TestValidateSkills(SkillgenBase):
    def test_unwritten_regions_are_skill_format_errors(self):
        self.kg(["skillgen", "topic:llm", "--layer", "global"])
        result = self.kg(["validate", "--skills"])
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("skill-format", result.stdout)

    def test_written_skill_passes(self):
        self.kg(["skillgen", "topic:llm", "--layer", "global"])
        self.write_llm_regions(self.staging("kg-llm"))
        result = self.kg(["validate", "--skills"])
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("skill-format", result.stdout)

    def test_stale_skill_is_listed(self):
        self.kg(["skillgen", "topic:llm", "--layer", "global"])
        self.write_llm_regions(self.staging("kg-llm"))
        page = (self.fix / "global" / "topics" / "llm" / "pages" / "concepts"
                / "graphrag.md")
        page.write_text(page.read_text(encoding="utf-8") + "\n追記行。\n",
                        encoding="utf-8")
        result = self.kg(["validate", "--skills"])
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("skill-stale", result.stdout)

    def test_broken_marker_is_skill_format(self):
        self.kg(["skillgen", "topic:llm", "--layer", "global"])
        path = self.staging("kg-llm")
        self.write_llm_regions(path)
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace(community.MARK_SK_END, ""), encoding="utf-8")
        result = self.kg(["validate", "--skills"])
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("skill-format", result.stdout)

    def test_missing_trust_notice_is_skill_format(self):
        self.kg(["skillgen", "topic:llm", "--layer", "global"])
        path = self.staging("kg-llm")
        self.write_llm_regions(path)
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace(NOTICE[0], "改変された注意書き"),
                        encoding="utf-8")
        result = self.kg(["validate", "--skills"])
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("skill-format", result.stdout)

    def test_plain_validate_ignores_skills(self):
        self.kg(["skillgen", "topic:llm", "--layer", "global"])
        result = self.kg(["validate"])  # 未執筆でも --skills なしなら error にしない
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("skill-format", result.stdout)


class TestInstall(SkillgenBase):
    def test_install_refuses_unwritten_skill(self):
        self.kg(["skillgen", "topic:llm", "--layer", "global"])
        result = self.kg(["skillgen", "topic:llm", "--layer", "global", "--install"])
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(self.installed("kg-llm").exists())

    def test_install_copies_and_logs(self):
        self.kg(["skillgen", "topic:llm", "--layer", "global"])
        staged = self.write_llm_regions(self.staging("kg-llm"))
        result = self.kg(["skillgen", "topic:llm", "--layer", "global", "--install",
                          "--date", "2026-07-14"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.installed("kg-llm").read_text(encoding="utf-8"), staged)
        log = (self.fix / "global" / "log.md").read_text(encoding="utf-8")
        self.assertIn("[skill-install] kg-llm → ", log)

    def test_install_prints_diff_for_new_and_existing(self):
        self.kg(["skillgen", "topic:llm", "--layer", "global"])
        self.write_llm_regions(self.staging("kg-llm"))
        first = self.kg(["skillgen", "topic:llm", "--layer", "global", "--install"])
        self.assertIn("+name: kg-llm", first.stdout)  # 新規は全文が追加差分

        self.write_llm_regions(self.staging("kg-llm"),
                               description="改訂した説明。", summary="改訂した本文。")
        second = self.kg(["skillgen", "topic:llm", "--layer", "global", "--install"])
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("+description: 改訂した説明。", second.stdout)
        self.assertIn("-description: LLM についての知識。", second.stdout)

    def test_dry_run_shows_diff_without_writing(self):
        self.kg(["skillgen", "topic:llm", "--layer", "global"])
        self.write_llm_regions(self.staging("kg-llm"))
        result = self.kg(["skillgen", "topic:llm", "--layer", "global", "--install",
                          "--dry-run"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("+name: kg-llm", result.stdout)
        self.assertFalse(self.installed("kg-llm").exists())
        log = (self.fix / "global" / "log.md").read_text(encoding="utf-8")
        self.assertNotIn("skill-install", log)

    def test_dry_run_refuses_unwritten_skill(self):
        self.kg(["skillgen", "topic:llm", "--layer", "global"])
        result = self.kg(["skillgen", "topic:llm", "--layer", "global", "--install",
                          "--dry-run"])
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.installed("kg-llm").exists())

    def test_dest_override(self):
        self.kg(["skillgen", "topic:llm", "--layer", "global"])
        self.write_llm_regions(self.staging("kg-llm"))
        dest = Path(self.tmp.name) / "elsewhere"
        result = self.kg(["skillgen", "topic:llm", "--layer", "global", "--install",
                          "--dest", str(dest)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((dest / "kg-llm" / "SKILL.md").is_file())

    def test_validate_skills_checks_installed_skill(self):
        self.kg(["skillgen", "topic:llm", "--layer", "global"])
        self.write_llm_regions(self.staging("kg-llm"))
        self.kg(["skillgen", "topic:llm", "--layer", "global", "--install"])
        # インストール済み Skill を壊す → validate --skills が検出する
        path = self.installed("kg-llm")
        path.write_text(path.read_text(encoding="utf-8")
                        .replace(community.MARK_SU_END, ""), encoding="utf-8")
        result = self.kg(["validate", "--skills"])
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("skill-format", result.stdout)

    def test_validate_skills_ignores_handwritten_skill(self):
        skill = self.home / ".claude" / "skills" / "handwritten"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: handwritten\ndescription: 手書き。\n---\n\n本文。\n",
            encoding="utf-8")
        result = self.kg(["validate", "--skills"])
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("handwritten", result.stdout)


if __name__ == "__main__":
    unittest.main()

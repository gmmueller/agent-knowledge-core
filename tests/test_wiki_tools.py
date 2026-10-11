"""Targeted port checks. Run with python -I tests/test_wiki_tools.py --scratch <private-scratch-dir>."""
import argparse
import locale
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import brainlib
import build_wiki_index
import check_wiki

TOOLS = Path(__file__).resolve().parents[1] / "tools"
SCRATCH = None


class WikiTools(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wiki-tools-", dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.brain = self.root / "my-course"
        self.write("brain.md", "---\nname: my-course\ndisplay_name: My Course (The Expert)\nkind: course\nupdated: 2026-01-01\nskill:\n  description: Consult the expert.\n  short_description: Cited expert teachings\n  default_prompt: Use $my-course with citations.\n---\n# My Course\n")
        self.write("sources.yaml", "sources:\n  - {id: my-course, product: main, title: My Course}\n")
        self.write("raw/main/m01/l01.md", "---\nmethod: captions\n---\n**[0:00]** Practice every day to build skill.\n**[0:30]** Keep a record of your progress.\n")
        self.write("wiki/sources/main-m01-l01.md", "---\ntype: source\nsources: [raw/main/m01/l01.md]\nupdated: 2026-01-01\nproduct: main\nmodule: Getting Started\nlesson: Practice\nduration: 90\nurl: https://example.com/lesson\n---\n# Practice\n\n**Summary.** A lesson on [[rule-practice]].\n\n## Key claims\n- Practice builds skill. ([[raw/main/m01/l01]] @ 0:00)\n\n## Quotes\n> \"Practice every day to build skill.\" -- ([[raw/main/m01/l01]] @ 0:00)\n")
        self.write("wiki/rules/rule-practice.md", "---\ntype: rule\nsources: [raw/main/m01/l01.md]\nupdated: 2026-01-01\nstatus: bench\n---\n# Practice\n\nPractice regularly.\n\n## Key points\n- Practice builds skill. ([[raw/main/m01/l01]] @ 0:00)\n\n## Quotes\n> \"Practice every day to build skill.\" -- ([[raw/main/m01/l01]] @ 0:00)\n\n## Sources\n- [[main-m01-l01]]\n")

    def write(self, rel, text):
        brainlib.write_text(self.brain / rel, text)

    def run_tool(self, tool, *args, env=None):
        return subprocess.run([sys.executable, "-I", "-B", str(TOOLS / tool), *map(str, args)], cwd=self.root,
                              capture_output=True, text=True, encoding=locale.getencoding(), env=env)

    def test_help_and_required_paths(self):
        for name in ("check_wiki", "lint_wiki", "build_wiki_index", "requote", "merge_staging", "generate_persona", "refresh_due"):
            with self.subTest(name=name):
                self.assertEqual(self.run_tool(name + ".py", "--help").returncode, 0)
                self.assertEqual(self.run_tool(name + ".py").returncode, 2)

    def test_check_lint_and_duration_index(self):
        for tool in ("check_wiki.py", "lint_wiki.py"):
            result = self.run_tool(tool, "--brain", self.brain)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = self.run_tool("build_wiki_index.py", "--brain", self.brain)
        self.assertEqual(result.returncode, 0, result.stderr)
        index = (self.brain / "wiki/index.md").read_text(encoding="utf-8")
        self.assertIn("### My Course", index)
        self.assertIn("[[rule-practice]]", index)
        self.assertIn('duration: "1:30"', (self.brain / "wiki/sources/main-m01-l01.md").read_text(encoding="utf-8"))

    def test_product_names_registry_config_outline_and_legacy_notes(self):
        self.write("sources.yaml", "sources:\n  - {id: first, title: First Course}\n  - {id: second, title: Second Course, url: 'https://example.com/second/'}\n  - {id: legacy, title: Legacy Course, notes: '(product code legacy-code)'}\n")
        self.write("crawl.yaml", "products: [{code: one, source_id: first}]\n")
        self.write("outline.yaml", "products:\n  - {code: two, title: Outline Second, url: 'https://example.com/second'}\n  - {code: fallback, title: Fallback Course}\n")
        self.assertEqual(build_wiki_index.product_names(self.brain),
                         {"one": "First Course", "two": "Second Course", "legacy-code": "Legacy Course", "fallback": "Fallback Course"})

    def test_index_keeps_unregistered_products(self):
        path = self.brain / "wiki/sources/main-m01-l01.md"
        path.write_text(path.read_text(encoding="utf-8").replace("product: main", "product: unregistered"), encoding="utf-8")
        result = self.run_tool("build_wiki_index.py", "--brain", self.brain)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("### Unregistered", (self.brain / "wiki/index.md").read_text(encoding="utf-8"))

    def test_requote_preview_then_apply(self):
        path = self.brain / "wiki/sources/main-m01-l01.md"
        bad = path.read_text(encoding="utf-8").replace('> "Practice every day to build skill."', '> "Practice daily to build skill."')
        path.write_text(bad, encoding="utf-8")
        self.assertEqual(self.run_tool("check_wiki.py", "--brain", self.brain).returncode, 1)
        args = ("--brain", self.brain, "raw/main/m01/l01", path, "--min", "0.7")
        result = self.run_tool("requote.py", *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("would fix", result.stdout)
        self.assertEqual(path.read_text(encoding="utf-8"), bad)
        result = self.run_tool("requote.py", *args, "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.run_tool("check_wiki.py", "--brain", self.brain).returncode, 0)

    def test_merge_and_slug_map(self):
        self.write("ingest/batches.yaml", "a:\n  items: [{id: main-m01-l01, raw: raw/main/m01/l01}]\n")
        self.write("ingest/slug-map.yaml", "old-practice: rule-practice\n")
        self.write("ingest/staging/a.yaml", "lessons: [{id: main-m01-l01, presenter: The Expert}]\nconcepts:\n  - slug: old-practice\n    type: rule\n    name: Practice\n    quotes:\n      - text: Practice every day to build skill.\n        cite: {raw: raw/main/m01/l01, at: '0:00'}\n")
        for mode in ("survey", "bundles"):
            result = self.run_tool("merge_staging.py", "--brain", self.brain, mode)
            self.assertEqual(result.returncode, 0, result.stderr)
        bundle = brainlib.load_yaml(self.brain / "ingest/bundles/rule-practice.yaml")
        self.assertEqual(bundle["status"], "bench")
        self.assertEqual(bundle["quotes"][0]["presenter"], "The Expert")
        path = self.brain / "wiki/sources/main-m01-l01.md"
        path.write_text(path.read_text(encoding="utf-8").replace("[[rule-practice]]", "[[old-practice]]"), encoding="utf-8")
        result = self.run_tool("lint_wiki.py", "--brain", self.brain, "--fix-slug-map")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("slug map applied to 1 pages", result.stdout)

    def test_persona_explicit_or_environment_output(self):
        env = os.environ.copy()
        env.pop("CREATE_A_BRAIN_SKILLS_DIR", None)
        self.assertEqual(self.run_tool("generate_persona.py", "--brain", self.brain, env=env).returncode, 2)
        out = self.root / "skills"
        env["CREATE_A_BRAIN_SKILLS_DIR"] = str(out)
        result = self.run_tool("generate_persona.py", "--brain", self.brain, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.brain / "brain.md"), (out / "my-course/SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(brainlib.load_yaml(out / "my-course/agents/openai.yaml")["interface"]["display_name"], "My Course (The Expert)")
        path = self.brain / "brain.md"
        path.write_text(path.read_text(encoding="utf-8").replace("name: my-course", "name: ../outside"), encoding="utf-8")
        self.assertEqual(self.run_tool("generate_persona.py", "--brain", self.brain, "--out", out).returncode, 2)
        self.assertFalse((self.root / "outside").exists())

    def test_refresh_brain_library_tool_and_reminders_off(self):
        self.write("sources.yaml", "sources: [{id: main, title: My Course, refresh: yearly, last_crawled: 2000-01-01}]\n")
        brainlib.write_text(self.root / "library/publisher/sources.yaml", "sources: [{id: feed, title: Example Feed, refresh: weekly, last_crawled: 2000-01-01}]\n")
        self.write("wiki/tools/example-tool.md", "---\ntype: tool\nrecheck_by: 2000-01-01\n---\n")
        result = self.run_tool("refresh_due.py", "--root", self.root, "--all")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Due for refresh (3)", result.stdout)
        self.assertIn("library/publisher / Example Feed", result.stdout)
        path = self.brain / "brain.md"
        path.write_text(path.read_text(encoding="utf-8").replace("kind: course", "kind: course\nrefresh: {reminders: false}"), encoding="utf-8")
        result = self.run_tool("refresh_due.py", "--root", self.root, "--all")
        self.assertIn("Due for refresh (1)", result.stdout)
        self.assertIn("reminders off", result.stdout)

    def test_topic_speaker_library_and_paragraph_anchor(self):
        path = self.brain / "brain.md"
        path.write_text(path.read_text(encoding="utf-8").replace("kind: course", "kind: topic"), encoding="utf-8")
        brainlib.write_text(self.root / "library/publisher/raw/lesson.md", "---\nspeakers: [The Expert, Other Speaker]\n---\n**[0:00]** The Expert: Practice every day.\n**[0:30]** Other Speaker: Keep clear notes.\n**[\u00b61]** The Expert: Written explanation.\n")
        brainlib.write_text(self.root / "library/people.yaml", "expert: {name: The Expert, aliases: [Expert]}\n")
        errors = []
        check_wiki.check_cite(self.brain, "library/publisher/raw/lesson", "0:00", "Practice every day.", "fixture", errors, "Expert")
        check_wiki.check_cite(self.brain, "library/publisher/raw/lesson", "\u00b61", "Written explanation.", "fixture", errors, "The Expert")
        self.assertEqual(errors, [])
        check_wiki.check_cite(self.brain, "library/publisher/raw/lesson", "0:30", "Keep clear notes.", "fixture", errors, "The Expert")
        self.assertIn("does not match", errors[-1])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    SCRATCH = args.scratch.resolve()
    if not SCRATCH.is_dir():
        parser.error("--scratch must be an existing private scratch directory")
    unittest.main(argv=[sys.argv[0], *remaining])

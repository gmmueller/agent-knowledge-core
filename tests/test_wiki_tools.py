"""Targeted port checks. Run with python -I tests/test_wiki_tools.py --scratch <private-scratch-dir>."""
import argparse
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
import wiki_edits

TOOLS = Path(__file__).resolve().parents[1] / "tools"
SCRATCH = None


class WikiTools(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wiki-tools-", dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.brain = self.root / "my-course"
        self.write("brain.md", "---\nname: my-course\ndisplay_name: My Course (The Expert)\nkind: course\nupdated: 2026-01-01\nskill:\n  description: Consult the expert.\n  short_description: Cited expert teachings\n  default_prompt: Use $my-course with citations.\n---\n# My Course\n")
        self.write("sources.yaml", "sources:\n  - {id: my-course, product: main, title: My Course}\n")
        self.write("raw/main/m01/l01.md", "---\nmethod: captions\n---\n**[0:00]** Practice every day to build skill.\n**[0:30]** Keep a record of your progress.\n")
        self.write("wiki/sources/main-m01-l01.md", "---\ntype: source\nsources: [raw/main/m01/l01.md]\nupdated: 2026-01-01\nproduct: main\nmodule: Getting Started\nlesson: Practice\nduration: 90\nurl: https://example.com/lesson\n---\n# Practice\n\n**Summary.** A lesson on [[rule-practice]].\n\n## Key claims\n- Practice builds skill. ([[raw/main/m01/l01]] @ 0:00)\n\n## Quotes\n> \"Practice every day to build skill.\" -- ([[raw/main/m01/l01]] @ 0:00)\n")
        self.write("wiki/rules/rule-practice.md", "---\ntype: rule\nsources: [raw/main/m01/l01.md]\nupdated: 2026-01-01\nstatus: bench\n---\n# Practice\n\nPractice regularly.\n\n## Key points\n- Practice builds skill. ([[raw/main/m01/l01]] @ 0:00)\n\n## Quotes\n> \"Practice every day to build skill.\" -- ([[raw/main/m01/l01]] @ 0:00)\n\n## Sources\n- [[main-m01-l01]]\n")

    def write(self, rel, text):
        brainlib.write_text(self.brain / rel, text)

    def run_tool(self, tool, *args, env=None):
        return subprocess.run([sys.executable, "-X", "utf8", "-I", "-B", str(TOOLS / tool), *map(str, args)], cwd=self.root,
                              capture_output=True, text=True, encoding="utf-8", env=env)

    def test_help_and_required_paths(self):
        for name in ("check_wiki", "lint_wiki", "build_wiki_index", "requote", "merge_staging", "generate_persona", "refresh_due"):
            with self.subTest(name=name):
                self.assertEqual(self.run_tool(name + ".py", "--help").returncode, 0)
                self.assertEqual(self.run_tool(name + ".py").returncode, 2)

    def test_check_lint_and_duration_index(self):
        result = self.run_tool("build_wiki_index.py", "--brain", self.brain)
        self.assertEqual(result.returncode, 0, result.stderr)
        for tool in ("check_wiki.py", "lint_wiki.py"):
            result = self.run_tool(tool, "--brain", self.brain)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("unknown page type", result.stdout)
        index = (self.brain / "wiki/index.md").read_text(encoding="utf-8")
        sources = (self.brain / "wiki/sources-index.md").read_text(encoding="utf-8")
        self.assertIn("[[rule-practice]]", index)
        self.assertIn("[[sources-index]]", index)
        self.assertNotIn("## Sources", index)
        self.assertNotIn("main-m01-l01", index)
        self.assertIn("### My Course\n\n#### Getting Started", sources)
        self.assertIn("- [[main-m01-l01|Practice]]", sources)
        self.assertNotIn("[[rule-practice]]", sources)
        self.assertIn('duration: "1:30"', (self.brain / "wiki/sources/main-m01-l01.md").read_text(encoding="utf-8"))

    def test_corruption_in_pages_and_staging_but_not_urls(self):
        page = self.brain / "wiki/sources/main-m01-l01.md"
        valid = page.read_text(encoding="utf-8")
        self.write("wiki/sources/main-m01-l01.md", valid.replace('" --', '" ?')
                   + "\nhttps://example.com/?n=1?2\n### How does this work ? (Help, 2026-01-01)\n"
                   + "See https://example.com/?a=1 and don?t ignore contractions.\n")
        result = self.run_tool("check_wiki.py", "--brain", self.brain, page)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("possible corruption"), 2, result.stdout)
        self.assertIn("quote line needs a separator dash", result.stdout)
        self.write("ingest/staging/example.yaml", "concepts: []\n# Broken 1?2\n")
        result = self.run_tool("check_wiki.py", "--brain", self.brain, self.brain / "ingest/staging/example.yaml")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("possible corruption", result.stdout)

    def test_quote_dash_and_speaker_syntax_in_both_brain_kinds(self):
        page = self.brain / "wiki/rules/rule-practice.md"
        valid = page.read_text(encoding="utf-8")
        for kind in ("persona", "topic"):
            self.write("brain.md", f"---\nkind: {kind}\n---\n")
            for separator, expected in (("", "needs a separator dash"), ("-- ??", "invalid quote speaker")):
                with self.subTest(kind=kind, separator=separator):
                    self.write("wiki/rules/rule-practice.md", valid.replace('" --', f'" {separator}'))
                    errors = []
                    check_wiki.check_page(self.brain, page, errors)
                    self.assertIn(expected, "\n".join(errors))

    def test_brain_card_checks_inline_quotes_and_vault_links(self):
        brainlib.write_text(self.root / "other-vault/brain.md", "# Other")
        brainlib.write_text(self.root / "other-vault/wiki/index.md", "# Other index")
        baseline = (self.brain / "brain.md").read_text(encoding="utf-8")
        card = baseline + (
            '\n| [[rule-practice|Practice]] | "Practice every day to build skill." ([[raw/main/m01/l01]] @ 0:00) |\n'
            '\n> "Keep a record of your progress." -- Ada (Editor) ([[raw/main/m01/l01]] @ 0:30)\n'
            '\nUse the syntax `([[raw/...]] @ m:ss)`.\n'
        )
        self.write("brain.md", card)
        result = self.run_tool("check_wiki.py", "--brain", self.brain)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.write("brain.md", card.replace("Practice every day", "Practice on weekends") +
                   "\n[[other-vault/wiki/index]] and [[no-such-page]].\n")
        result = self.run_tool("check_wiki.py", "--brain", self.brain)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("brain.md:", result.stdout)
        self.assertIn("quote not at 0:00", result.stdout)
        self.assertIn("cross-brain wikilink", result.stdout)
        self.assertIn("unresolved wikilink", result.stdout)

    def test_markdown_links_outside_brain_warn_or_fail_if_missing(self):
        brainlib.write_text(self.root / "other-vault/brain.md", "# Other")
        brainlib.write_text(self.root / "other-vault/wiki/guide (draft).md", "# Guide")
        page = self.brain / "wiki/topics/link-test.md"
        self.write("wiki/topics/link-test.md", """---
type: topic
sources: []
updated: 2026-01-01
---
## Key points

[Other](<../../../other-vault/wiki/guide (draft).md#heading> "Guide")

[Local](../../brain.md) [Anchor](#key-points) [External](https://example.org/missing)
""")
        result = self.run_tool("check_wiki.py", "--brain", self.brain, page)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("Markdown link leaves the brain folder"), 1)
        with page.open("a", encoding="utf-8") as stream:
            stream.write("\n[Missing](../../../other-vault/wiki/missing.md#anchor)\n")
        result = self.run_tool("check_wiki.py", "--brain", self.brain, page)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("unresolved Markdown link outside the brain folder", result.stdout)

    def test_brain_card_requires_evidence_for_each_rule_row(self):
        card = self.brain / "brain.md"
        text = card.read_text(encoding="utf-8") + (
            "\n## Rules\n\n### Active\n\n"
            "| # | Rule | Evidence |\n|---|---|---|\n"
            '| 1 | [[rule-practice|Practice regularly]] | "Practice every day to build skill." '
            '— [[raw/main/m01/l01]] @ 0:00 |\n'
            "\n### Bench\n\n| Rule | Status | Evidence |\n|---|---|---|\n"
            "| Record each attempt | bench | [[raw/main/m01/l01]] @ 0:30 |\n"
            "| Leave time to review | bench | [[rule-practice]] |\n"
            "\n## Key points\n- Review your records.\n"
            "\n## Frameworks\n| Rule | Evidence |\n|---|---|\n| Workflow example | none |\n"
        )
        self.write("brain.md", text)
        result = self.run_tool("check_wiki.py", "--brain", self.brain, card)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("rule without an exact quote"), 2, result.stdout)
        self.assertIn("key points claim without citation", result.stdout)
        self.write("brain.md", text
                   .replace("| bench | [[", '| bench | "Keep a record of your progress." — [[')
                   .replace('— [[rule-practice]] |', '— [[raw/main/m01/l01]] @ 0:30 |')
                   .replace("Review your records.", "Review your records. ([[raw/main/m01/l01]] @ 0:30)"))
        result = self.run_tool("check_wiki.py", "--brain", self.brain, card)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_eval_quote_errors_exit_nonzero(self):
        answers = self.brain / "answers.md"
        two_on_one_line = ('If "short" is too strong for the original "term", compare '
                           '"Practice every day to build skill." ([[raw/main/m01/l01]] @ 0:00) and then '
                           '"Keep a record of your progress." ([[raw/main/m01/l01]] @ 0:30)')
        for text, status, message in (
            ('"Practice every day to build skill." ([[raw/main/m01/l01]] @ 0:00)', 0, "1 attributed quotes checked"),
            (two_on_one_line, 0, "2 attributed quotes checked, 0 problems"),
            ('"Never practice until next week." ([[raw/main/m01/l01]] @ 0:00)', 1, "quote not at"),
            ('"Never practice until next week." [[rule-practice]]', 1, "1 not found verbatim"),
        ):
            with self.subTest(text=text):
                self.write("answers.md", text + "\n")
                result = self.run_tool("verify_eval_quotes.py", "--brain", self.brain, answers)
                self.assertEqual(result.returncode, status, result.stdout + result.stderr)
                self.assertIn(message, result.stdout)

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
        self.assertIn("### Unregistered", (self.brain / "wiki/sources-index.md").read_text(encoding="utf-8"))

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

    def test_requote_skips_protected_and_unchanged_pages(self):
        protected = self.brain / "wiki/sources/main-m01-l01.md"
        editable = self.brain / "wiki/rules/rule-practice.md"
        unchanged = self.brain / "wiki/topics/manual.md"
        self.write("wiki/topics/manual.md", '> "A completely unrelated quote." -- ([[raw/main/m01/l01]] @ 0:00)\n')
        original = unchanged.read_bytes().replace(b"\n", b"\r\n")
        unchanged.write_bytes(original)
        wiki_edits.record(self.brain, init=True)
        for path in (protected, editable):
            bad = path.read_text(encoding="utf-8").replace('> "Practice every day', '> "Practice daily')
            path.write_text(bad, encoding="utf-8")
            if path == protected:
                wiki_edits.begin(self.brain)
            else:
                wiki_edits.register_writes(self.brain, {"rules/rule-practice.md": wiki_edits.hashes.digest(path)})
        owner_copy = protected.read_bytes()
        result = self.run_tool("requote.py", "--brain", self.brain, "raw/main/m01/l01", protected,
                               editable, unchanged, "--min", "0.7", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipped protected page: wiki/sources/main-m01-l01.md", result.stdout)
        self.assertIn("FIXED", result.stdout)
        self.assertIn("MANUAL", result.stdout)
        self.assertEqual(protected.read_bytes(), owner_copy)
        self.assertIn('> "Practice every day', editable.read_text(encoding="utf-8"))
        self.assertEqual(unchanged.read_bytes(), original)

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

    def test_slug_map_updates_agent_pages_during_pass(self):
        self.write("ingest/slug-map.yaml", "old-practice: rule-practice\n")
        self.write("wiki/topics/old-practice.md", "---\ntype: topic\n---\n# Old practice\n")
        wiki_edits.record(self.brain, init=True)
        protected = self.brain / "wiki/sources/main-m01-l01.md"
        original = protected.read_text(encoding="utf-8") + "\nOwner link: [[old-practice]]\n"
        self.write("wiki/sources/main-m01-l01.md", original)
        wiki_edits.begin(self.brain)
        self.write("wiki/topics/agent.md", "---\ntype: topic\n---\n# New page\n\n[[old-practice]]\n")
        wiki_edits.register_writes(self.brain, {"topics/agent.md": wiki_edits.hashes.digest(self.brain / "wiki/topics/agent.md")})
        result = self.run_tool("lint_wiki.py", "--brain", self.brain, "--fix-slug-map")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("slug map applied to 1 pages", result.stdout)
        self.assertEqual(protected.read_text(encoding="utf-8"), original)
        self.assertIn("[[rule-practice]]", (self.brain / "wiki/topics/agent.md").read_text(encoding="utf-8"))
        self.assertEqual(wiki_edits.protected_pages(self.brain), {"sources/main-m01-l01.md"})

    def test_link_examples_skips_protected_and_unchanged_pages(self):
        self.write("wiki/topics/owner.md", "# Owner\n")
        self.write("wiki/topics/agent.md", "# Agent\n\n## Related\n\n- [[owner]]\n")
        self.write("wiki/topics/untouched.md", "# Untouched")
        self.write("wiki/examples/sample.md", "# Worked example\n")
        self.write("ingest/staging/examples-acme.yaml", "examples: [{page: sample, techniques: [owner, agent]}]\n")
        wiki_edits.record(self.brain, init=True)
        self.write("wiki/topics/owner.md", "# Owner\n\nOwner edit.\n")
        wiki_edits.begin(self.brain)
        args = ("--brain", self.brain)
        result = self.run_tool("link_examples.py", *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipped protected page: wiki/topics/owner.md", result.stdout)
        self.assertEqual((self.brain / "wiki/topics/owner.md").read_bytes(), b"# Owner\n\nOwner edit.\n")
        self.assertEqual((self.brain / "wiki/topics/untouched.md").read_bytes(), b"# Untouched")
        path = self.brain / "wiki/topics/agent.md"
        original = path.read_bytes().replace(b"\n", b"\r\n")
        self.assertIn(b"[[sample]]", original)
        path.write_bytes(original)
        result = self.run_tool("link_examples.py", *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("updated Examples lists on 0 concept pages", result.stdout)
        self.assertEqual(path.read_bytes(), original)

    def test_incremental_merge_carries_batch_date_and_freshness(self):
        self.write("ingest/batches-2026-01-02.yaml", "update:\n  items: [{id: update-lesson, raw: raw/update}]\n")
        self.write("raw/update.md", "---\ncreated: 2026-01-02T12:00:00\n---\nUpdated words.\n")
        self.write("ingest/staging/update.yaml", "lessons: [{id: update-lesson, presenter: The Expert}]\nconcepts:\n  - slug: update-rule\n    type: rule\n    name: Update\n    quotes:\n      - text: Updated words.\n        freshness: tool-version\n        speaker: The Expert\n        cite: {raw: raw/update.md, at: '0:00'}\n")
        result = self.run_tool("merge_staging.py", "--brain", self.brain, "bundles")
        self.assertEqual(result.returncode, 0, result.stderr)
        quote = brainlib.load_yaml(self.brain / "ingest/bundles/update-rule.yaml")["quotes"][0]
        self.assertEqual({k: quote[k] for k in ("lesson", "batch", "date", "freshness", "speaker")},
                         {"lesson": "update-lesson", "batch": "update", "date": "2026-01-02",
                          "freshness": "tool-version", "speaker": "The Expert"})

    def test_topic_index_grouping_and_skill_lookup(self):
        path = self.brain / "brain.md"
        path.write_text(path.read_text(encoding="utf-8").replace("kind: course", "kind: topic\nexperts: [The Expert, Other Expert]"), encoding="utf-8")
        self.write("wiki/sources/article-old.md", "---\ntype: source\npublisher: example-publisher\npublished: 2024-01-01\n---\n# Older Article\n")
        self.write("wiki/sources/article-new.md", "---\ntype: source\npublisher: example-publisher\npublished: 2026-01-01\n---\n# Newer Article\n")
        self.write("wiki/sources/article-newer.md", "---\ntype: source\npublisher: example-publisher\npublished: 2026-02-01\n---\n# Another Article\n")
        self.write("wiki/rules/shared-rule.md", "---\ntype: rule\nstatus: consensus\n---\n# Shared Rule\n")
        self.write("wiki/tools/platform-fact.md", "---\ntype: tool\nfreshness: platform\n---\n# Platform Fact\n")
        self.write("wiki/examples/example.md", "---\ntype: example\n---\n# Worked Example\n")
        result = self.run_tool("build_wiki_index.py", "--brain", self.brain)
        self.assertEqual(result.returncode, 0, result.stderr)
        index = (self.brain / "wiki/index.md").read_text(encoding="utf-8")
        sources = (self.brain / "wiki/sources-index.md").read_text(encoding="utf-8")
        self.assertIn("## Tools and platform facts", index)
        self.assertIn("[[platform-fact]] _platform_", index)
        self.assertIn("## Examples", index)
        self.assertLess(sources.index("#### 2026"), sources.index("#### 2024"))
        self.assertIn("- [[article-new|Newer Article]]\n- [[article-newer|Another Article]]\n", sources)
        result = self.run_tool("generate_persona.py", "--brain", self.brain, "--out", self.root / "skills")
        self.assertEqual(result.returncode, 0, result.stderr)
        skill = (self.root / "skills/my-course/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("The Expert, Other Expert", skill)
        self.assertNotRegex(skill, r"\d+ (consensus|active|bench|contested)")
        self.assertIn("read `brain.md` and the concept index `wiki/index.md`", skill)
        self.assertIn("qmd collections `my-course-wiki` and `library`", skill)
        self.assertIn("grep `wiki/` and `library/*/raw/`", skill)
        self.assertIn("Open `wiki/sources-index.md` only to locate a specific source", skill)
        self.assertIn("Worked examples are in `examples/`", skill)
        self.assertIn(f"`platform-fact.md` in `{self.brain / 'wiki'}/tools/`", skill)
        self.assertNotIn("**Tools:**", skill)  # wiki/tools/ is distinct from brain-level tools/
        self.assertIn(str(self.root / "library"), skill)
        self.assertIn("if you paraphrase, drop the quote marks", skill)

    def test_persona_lists_wiki_tool_pages_alongside_brain_tools(self):
        self.write("tools/helper.py", "")
        self.write("wiki/tools/platform-fact.md", "# Platform Fact\n")
        result = self.run_tool("generate_persona.py", "--brain", self.brain, "--out", self.root / "skills",
                               "--relative-to", self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        skill = (self.root / "skills/my-course/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`my-course/tools` holds brain-specific tools", skill)
        self.assertIn("`platform-fact.md` in `my-course/wiki/tools/`", skill)

    def test_community_index_groups_threads_by_month_and_courses(self):
        for slug, module, published in (("thread-old", "Community threads", "2024-01-01"),
                                        ("thread-new", "Community digest", "2026-01-01"),
                                        ("lesson", "Example Course", "2025-01-01")):
            self.write(f"wiki/sources/{slug}.md", f"---\ntype: source\nmodule: {module}\npublished: {published}\n---\n# {slug}\n")
        result = self.run_tool("build_wiki_index.py", "--brain", self.brain)
        self.assertEqual(result.returncode, 0, result.stderr)
        sources = (self.brain / "wiki/sources-index.md").read_text(encoding="utf-8")
        self.assertIn("### Classroom", sources)
        self.assertIn("### Community", sources)
        self.assertIn("#### Example Course", sources)
        self.assertLess(sources.index("#### 2026-01"), sources.index("#### 2024-01"))

    def test_persona_explicit_or_environment_output(self):
        env = os.environ.copy()
        env.pop("AGENT_KNOWLEDGE_CORE_SKILLS_DIR", None)
        self.assertEqual(self.run_tool("generate_persona.py", "--brain", self.brain, env=env).returncode, 2)
        out = self.root / "skills"
        env["AGENT_KNOWLEDGE_CORE_SKILLS_DIR"] = str(out)
        (self.brain / "tools").mkdir()
        (self.brain / "wiki/examples").mkdir()
        result = self.run_tool("generate_persona.py", "--brain", self.brain, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        skill = (out / "my-course/SKILL.md").read_text(encoding="utf-8")
        self.assertIn(str(self.brain / "brain.md"), skill)
        self.assertIn(str(self.brain / "tools"), skill)
        self.assertNotIn("`examples/`", skill)
        self.assertNotRegex(skill, r"\d+ (active|bench)")
        self.assertIn("read `brain.md` and the concept index `wiki/index.md`", skill)
        self.assertIn("qmd collections `my-course-wiki` and `my-course-raw`", skill)
        self.assertIn("grep `wiki/` and `raw/`", skill)
        self.assertIn("Open `wiki/sources-index.md` only to locate a specific source", skill)
        self.assertEqual(brainlib.load_yaml(out / "my-course/agents/openai.yaml")["interface"]["display_name"], "My Course (The Expert)")
        path = self.brain / "brain.md"
        path.write_text(path.read_text(encoding="utf-8").replace("name: my-course", "name: ../outside"), encoding="utf-8")
        self.assertEqual(self.run_tool("generate_persona.py", "--brain", self.brain, "--out", out).returncode, 2)
        self.assertFalse((self.root / "outside").exists())

    def test_persona_check_reports_drift_without_writing(self):
        out = self.root / "skills"
        args = ("--brain", self.brain, "--out", out, "--relative-to", self.root)
        result = self.run_tool("generate_persona.py", *args, "--check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("SKILL.md (missing)", result.stdout)
        self.assertFalse(out.exists())
        result = self.run_tool("generate_persona.py", *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.run_tool("generate_persona.py", *args, "--check").returncode, 0)

        skill = out / "my-course/SKILL.md"
        skill.write_text("Old skill\n", encoding="utf-8", newline="\n")
        metadata = out / "my-course/agents/openai.yaml"
        metadata.write_text("Old metadata\n", encoding="utf-8", newline="\n")
        result = self.run_tool("generate_persona.py", *args, "--check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertIn("SKILL.md (changed), agents/openai.yaml (changed)", result.stdout)
        self.assertEqual(skill.read_text(encoding="utf-8"), "Old skill\n")
        self.assertEqual(metadata.read_text(encoding="utf-8"), "Old metadata\n")

    def test_refresh_brain_library_tool_and_reminders_off(self):
        self.write("sources.yaml", "sources: [{id: main, title: My Course, refresh: yearly, last_crawled: 2000-01-01}]\n")
        brainlib.write_text(self.root / "library/publisher/sources.yaml", "sources: [{id: feed, title: Example Feed, refresh: weekly, last_crawled: 2000-01-01}]\n")
        self.write("wiki/tools/example-tool.md", "---\ntype: tool\nrecheck_by: 2000-01-01\n---\n")
        result = self.run_tool("refresh_due.py", "--root", self.root, "--all")
        self.assertEqual(result.returncode, 0, result.stderr)
        alias = self.run_tool("refresh_due.py", "--workspace", self.root, "--all")
        self.assertEqual((alias.returncode, alias.stdout), (result.returncode, result.stdout))
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

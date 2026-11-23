"""Wiki human-edit protection, human-owned notes and captured-source integrity."""
import contextlib
from concurrent.futures import ThreadPoolExecutor
import io
from hashlib import sha256
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import brainlib
import build_wiki_index
import check_wiki
import library_raw
import raw_guard
import wiki_edits

TOOLS = Path(__file__).resolve().parents[1] / "tools"
PAGE = "---\ntype: topic\nsources: []\nupdated: 2026-01-01\n---\n# Example\n\n## Key points\n- **Inference:** A useful thought.\n"


class EditGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="edit-guard-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.brain = self.root / "example-core"
        self.write("brain.md", "---\nkind: persona\nexperts: []\n---\n# Example\n")
        self.write("wiki/topics/example.md", PAGE)
        self.write("raw/source.md", "Captured words\n")

    def write(self, name, text):
        brainlib.write_text(self.brain / name, text)

    def run_tool(self, name, *args, scope="brain"):
        return subprocess.run([sys.executable, "-X", "utf8", "-I", str(TOOLS / name),
                               "--" + scope, str(self.brain if scope == "brain" else self.root), *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8")

    def init_wiki(self):
        result = self.run_tool("wiki_edits.py", "record", "--init")
        self.assertEqual(result.returncode, 0, result.stderr)

    def write_agent(self, page, text):
        draft = self.root / "draft.md"
        brainlib.write_text(draft, text)
        result = self.run_tool("wiki_edits.py", "write", page, "--from", draft)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_status_record_never_absorbs_changed_added_or_deleted(self):
        self.write("wiki/topics/deleted.md", PAGE)
        self.init_wiki()
        before = wiki_edits.manifest(self.brain).read_bytes()
        self.write("wiki/topics/example.md", PAGE + "Human addition\n")
        self.write("wiki/topics/new.md", PAGE)
        (self.brain / "wiki/topics/deleted.md").unlink()
        changes = wiki_edits.status(self.brain)
        self.assertEqual(changes, {"topics/deleted.md": "deleted", "topics/example.md": "changed", "topics/new.md": "added"})
        result = self.run_tool("wiki_edits.py", "status")
        self.assertEqual(result.returncode, 1, result.stderr)
        result = self.run_tool("wiki_edits.py", "record")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("left 3 human-edited pages alone", result.stdout)
        self.assertEqual(wiki_edits.manifest(self.brain).read_bytes(), before)
        self.assertEqual(wiki_edits.status(self.brain), changes)

    def test_agent_pass_records_agent_work_and_keeps_human_edits_protected(self):
        self.write("wiki/topics/agent.md", PAGE)
        self.init_wiki()
        self.write("wiki/topics/example.md", PAGE + "Human addition\n")
        result = self.run_tool("wiki_edits.py", "begin")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("protected: wiki/topics/example.md", result.stdout)
        self.assertEqual(wiki_edits.protected_pages(self.brain), {"topics/example.md"})
        # The agents write other pages during the pass.
        self.write_agent("topics/agent.md", PAGE + "Agent addition\n")
        self.write_agent("topics/new-agent-page.md", PAGE)
        status = self.run_tool("wiki_edits.py", "status")
        self.assertIn("agent pass: open (1 protected pages)", status.stdout)
        self.assertIn("3 pages differ from the baseline", status.stdout)
        result = self.run_tool("build_wiki_index.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(wiki_edits.pass_file(self.brain).exists())
        self.assertIn("agent pass: closed (1 protected pages)", self.run_tool("wiki_edits.py", "status").stdout)
        self.assertEqual(wiki_edits.status(self.brain), {"topics/example.md": "changed"})
        result = self.run_tool("wiki_edits.py", "accept", "topics/example.md")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(wiki_edits.status(self.brain), {})

    def test_begin_requires_baseline(self):
        with self.assertRaises(ValueError):
            wiki_edits.begin(self.brain)

    def test_index_leaves_mid_pass_human_edits_unrecorded(self):
        self.write("wiki/index.md", "# Original index\n")
        self.init_wiki()
        wiki_edits.begin(self.brain)
        self.write("wiki/topics/example.md", PAGE + "Owner addition\n")
        self.write("wiki/index.md", "# Owner's index\n")
        result = self.run_tool("build_wiki_index.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("wiki/topics/example.md", "wiki/index.md"):
            self.assertIn(f"left unrecorded: {name}", result.stdout)
        self.assertEqual((self.brain / "wiki/index.md").read_text(encoding="utf-8"), "# Owner's index\n")
        self.assertFalse(wiki_edits.pass_file(self.brain).exists())
        self.assertEqual(wiki_edits.status(self.brain), {"index.md": "changed", "topics/example.md": "changed"})

    def test_index_refuses_an_owner_save_after_the_protection_snapshot(self):
        self.write("wiki/index.md", "# Original index\n")
        self.init_wiki()
        wiki_edits.begin(self.brain)
        protected_pages = wiki_edits.protected_pages

        def save_after_snapshot(*args, **kwargs):
            protected = protected_pages(*args, **kwargs)
            self.write("wiki/index.md", "# Owner saved during rebuild\n")
            return protected

        with (patch.object(wiki_edits, "protected_pages", side_effect=save_after_snapshot),
              patch.object(sys, "argv", ["build_wiki_index.py", "--brain", str(self.brain)]),
              contextlib.redirect_stderr(io.StringIO()) as stderr, self.assertRaises(SystemExit) as failed):
            build_wiki_index.main()
        self.assertEqual(failed.exception.code, 2)
        self.assertIn("Refused write to wiki/index.md", stderr.getvalue())
        self.assertEqual((self.brain / "wiki/index.md").read_text(encoding="utf-8"), "# Owner saved during rebuild\n")
        self.assertTrue(wiki_edits.pass_file(self.brain).exists())

    def test_write_refuses_owner_changes_to_baseline_and_registered_content(self):
        self.init_wiki()
        wiki_edits.begin(self.brain)
        page = "topics/example.md"
        draft = self.root / "next.md"
        brainlib.write_text(draft, PAGE + "Agent revision\n")
        self.write_agent("topics/agent.md", PAGE + "Agent addition\n")
        for name in (page, "topics/agent.md"):
            with self.subTest(name=name):
                owner = PAGE + "Owner revision\n"
                self.write(f"wiki/{name}", owner)
                result = self.run_tool("wiki_edits.py", "write", name, "--from", draft)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn(f"Refused write to wiki/{name}", result.stderr)
                self.assertIn("propose", result.stderr)
                self.assertEqual((self.brain / "wiki" / name).read_text(encoding="utf-8"), owner)

    def test_write_rechecks_after_windows_sharing_violations(self):
        self.init_wiki()
        wiki_edits.begin(self.brain)
        original_replace = Path.replace
        for save_during_retry in (False, True):
            with self.subTest(save_during_retry=save_during_retry):
                path = self.brain / "wiki/topics/example.md"
                owner = PAGE + "Owner saved while file was busy\n"
                replacements = 0

                def replace(source, target):
                    nonlocal replacements
                    if target == path:
                        replacements += 1
                        if replacements == 1:
                            if save_during_retry:
                                self.write("wiki/topics/example.md", owner)
                            busy = PermissionError("sharing violation")
                            busy.winerror = 32
                            raise busy
                    return original_replace(source, target)

                with patch.object(Path, "replace", replace), patch.object(wiki_edits.time, "sleep"):
                    if save_during_retry:
                        with self.assertRaisesRegex(ValueError, "protected by an owner edit"):
                            wiki_edits.write_page(self.brain, path, PAGE + "Next agent revision\n")
                        self.assertEqual(path.read_text(encoding="utf-8"), owner)
                        self.assertEqual(replacements, 1)
                    else:
                        wiki_edits.write_page(self.brain, path, PAGE + "Agent revision\n")
                        self.assertEqual(wiki_edits.protected_pages(self.brain), set())
                        self.assertEqual(replacements, 2)
                self.assertEqual(list(path.parent.glob(".*.tmp")), [])

    def test_legacy_pass_without_snapshot_checks_each_protected_page(self):
        self.init_wiki()
        name = "topics/example.md"
        self.write(f"wiki/{name}", PAGE + "Original owner revision\n")
        wiki_edits.begin(self.brain)
        path = wiki_edits.pass_file(self.brain)
        state = wiki_edits.hashes.load(path)
        del state["at_begin"]
        wiki_edits.hashes.save(path, state)
        owner = PAGE + "New owner revision\n"
        self.write(f"wiki/{name}", owner)
        for tool, args in (("wiki_edits.py", ("record",)), ("build_wiki_index.py", ())):
            result = self.run_tool(tool, *args)
            self.assertEqual(result.returncode, 2)
            self.assertIn(f"wiki/{name}", result.stderr)
            self.assertIn("lack a pass snapshot", result.stderr)
            self.assertTrue(path.exists())
        self.assertEqual(self.run_tool("wiki_edits.py", "accept", name).returncode, 0)
        self.assertEqual(self.run_tool("wiki_edits.py", "record").returncode, 0)
        self.assertEqual((self.brain / "wiki" / name).read_text(encoding="utf-8"), owner)

    def test_wiki_errors_keep_pass_open_and_warnings_print(self):
        self.init_wiki()
        wiki_edits.begin(self.brain)
        invalid = "topics/uncited.md"
        self.write_agent(invalid, PAGE + "- Missing citation.\n")
        self.write_agent("topics/context.md", PAGE + "\nUncited context paragraph.\n")
        for tool, args in (("build_wiki_index.py", ()), ("wiki_edits.py", ("record",))):
            result = self.run_tool(tool, *args)
            self.assertEqual(result.returncode, 2)
            self.assertIn(f"wiki/{invalid}", result.stderr)
            self.assertIn("claim without citation", result.stderr)
            self.assertIn("warning: ", result.stdout)
            self.assertIn("wiki/topics/context.md", result.stdout)
            self.assertTrue(wiki_edits.pass_file(self.brain).exists())
        self.write_agent(invalid, PAGE)
        self.assertEqual(self.run_tool("build_wiki_index.py").returncode, 0)
        self.assertFalse(wiki_edits.pass_file(self.brain).exists())

    def test_pass_keeps_later_changes_to_declared_agent_output_protected(self):
        self.init_wiki()
        wiki_edits.begin(self.brain)
        page = "topics/example.md"
        self.write_agent(page, PAGE + "Agent addition\n")
        self.assertEqual(wiki_edits.protected_pages(self.brain), set())
        self.write(f"wiki/{page}", PAGE + "Agent addition\nOwner addition\n")
        self.assertEqual(wiki_edits.protected_pages(self.brain), {page})
        result = self.run_tool("wiki_edits.py", "record")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"left unrecorded: wiki/{page}", result.stdout)
        self.assertEqual(wiki_edits.status(self.brain), {page: "changed"})

    def test_owner_can_restore_original_content_after_agent_write(self):
        self.init_wiki()
        wiki_edits.begin(self.brain)
        page = "topics/example.md"
        self.write_agent(page, PAGE + "Agent addition\n")
        self.write(f"wiki/{page}", PAGE)
        self.assertEqual(wiki_edits.protected_pages(self.brain), {page})
        self.assertEqual(self.run_tool("wiki_edits.py", "record").returncode, 0)
        self.assertEqual(wiki_edits.protected_pages(self.brain), {page})

    def test_record_accepts_declared_deletion_and_reports_undeclared_addition(self):
        self.init_wiki()
        wiki_edits.begin(self.brain)
        (self.brain / "wiki/topics/example.md").unlink()
        result = self.run_tool("wiki_edits.py", "mark-written", "topics/example.md", "--deleted")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.write("wiki/topics/new.md", PAGE)
        result = self.run_tool("wiki_edits.py", "record")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("left unrecorded: wiki/topics/new.md", result.stdout)
        self.assertEqual(wiki_edits.status(self.brain), {"topics/new.md": "added"})

    def test_line_ending_only_changes_are_ignored_by_both_guards(self):
        raw = self.brain / "raw"
        raw_guard.record(raw, init=True)
        self.init_wiki()
        for path in (raw / "source.md", self.brain / "wiki/topics/example.md"):
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(wiki_edits.status(self.brain), {})
        self.assertEqual(wiki_edits.begin(self.brain), [])
        self.assertEqual(raw_guard.check(raw), {})

    def test_legacy_crlf_manifests_survive_lf_checkout(self):
        raw = self.brain / "raw"
        for manifest, name, path in (
            (wiki_edits.manifest(self.brain), "topics/example.md", self.brain / "wiki/topics/example.md"),
            (raw_guard.manifest(raw), "source.md", raw / "source.md"),
        ):
            legacy_digest = sha256(path.read_bytes().replace(b"\n", b"\r\n")).hexdigest()
            wiki_edits.hashes.save(manifest, {name: legacy_digest})
        self.assertEqual(wiki_edits.status(self.brain), {})
        self.assertEqual(raw_guard.check(raw), {})
        raw_guard.record(raw)
        self.write("raw/source.md", "Changed words\n")
        self.assertEqual(raw_guard.check(raw), {"source.md": "changed"})

    def test_reference_merge_recipes_check_citations_before_closing(self):
        reference = (TOOLS.parent / "docs/agent-reference.md").read_text(encoding="utf-8")
        for brain, writer in (("my-course", "merge_staging.py"), ("my-topic", "rule_status.py")):
            with self.subTest(brain=brain):
                recipe = [line for line in reference.splitlines() if f"--brain ../my-brains/{brain}" in line]
                after_writing = next(i for i, line in enumerate(recipe) if f"tools/{writer}" in line)
                closing = next(i for i in range(after_writing + 1, len(recipe))
                               if "tools/build_wiki_index.py" in recipe[i])
                self.assertTrue(any("tools/check_wiki.py" in line for line in recipe[after_writing + 1:closing]))

    def test_pass_stays_open_until_protected_page_is_restored(self):
        self.init_wiki()
        original = PAGE + "Owner addition\n"
        name = "wiki/topics/example.md"
        self.write(name, original)
        wiki_edits.begin(self.brain)
        baseline = wiki_edits.manifest(self.brain).read_bytes()
        pass_path = wiki_edits.pass_file(self.brain)
        saved_pass = pass_path.read_bytes()
        # Even writing back the old baseline over an owner edit must be detected.
        self.write(name, PAGE)
        self.assertEqual(wiki_edits.protected_pages(self.brain), {"topics/example.md"})
        for tool, args in (("wiki_edits.py", ("record",)), ("build_wiki_index.py", ())):
            result = self.run_tool(tool, *args)
            self.assertEqual(result.returncode, 2)
            for expected in ("Protected pages changed", name, "propose", "restore", "accept <page>"):
                self.assertIn(expected, result.stderr)
        self.assertEqual(self.run_tool("wiki_edits.py", "begin").returncode, 2)
        self.assertEqual(self.run_tool("wiki_edits.py", "record", "--init").returncode, 2)
        self.assertEqual(pass_path.read_bytes(), saved_pass)
        self.assertEqual(wiki_edits.manifest(self.brain).read_bytes(), baseline)
        status = self.run_tool("wiki_edits.py", "status")
        self.assertEqual(status.returncode, 1)
        self.assertIn(f"protected page changed during pass: {name}", status.stdout)
        self.write(name, original)
        result = self.run_tool("build_wiki_index.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(pass_path.exists())
        self.assertEqual(wiki_edits.protected_pages(self.brain), {"topics/example.md"})

    def test_explicit_accept_only_acknowledges_named_protected_pages(self):
        self.init_wiki()
        self.write("wiki/topics/example.md", PAGE + "Owner addition\n")
        self.write("wiki/topics/other.md", PAGE)
        wiki_edits.begin(self.brain)
        self.write("wiki/topics/example.md", PAGE + "Owner correction\n")
        (self.brain / "wiki/topics/other.md").unlink()
        self.write_agent("topics/agent.md", PAGE)
        self.assertEqual(self.run_tool("wiki_edits.py", "accept", "--all").returncode, 2)
        result = self.run_tool("wiki_edits.py", "accept", "topics/example.md")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(wiki_edits.changed_during_pass(self.brain), ["topics/other.md"])
        self.assertEqual(self.run_tool("wiki_edits.py", "record").returncode, 2)
        result = self.run_tool("wiki_edits.py", "accept", "topics/other.md")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(wiki_edits.status(self.brain), {"topics/agent.md": "added"})
        result = self.run_tool("wiki_edits.py", "record")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(wiki_edits.pass_file(self.brain).exists())
        self.assertEqual(wiki_edits.status(self.brain), {})

    def test_accept_specific_and_all_including_deletion(self):
        self.init_wiki()
        self.write("wiki/topics/example.md", PAGE + "Human addition\n")
        self.write("wiki/topics/new.md", PAGE)
        result = self.run_tool("wiki_edits.py", "accept", "wiki/topics/example.md")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(wiki_edits.status(self.brain), {"topics/new.md": "added"})
        (self.brain / "wiki/topics/example.md").unlink()
        result = self.run_tool("wiki_edits.py", "accept", "--all")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(wiki_edits.status(self.brain), {})
        self.assertEqual(self.run_tool("wiki_edits.py", "status").returncode, 0)

    def test_propose_lists_header_preserves_page_and_rejects_escape(self):
        self.init_wiki()
        self.write("wiki/topics/example.md", PAGE + "Human addition\n")
        source = self.root / "proposal.md"
        brainlib.write_text(source, PAGE + "Agent proposal\n")
        result = self.run_tool("wiki_edits.py", "propose", "topics/example.md", "--from", source, "--why", "New evidence")
        self.assertEqual(result.returncode, 0, result.stderr)
        proposals = wiki_edits.proposals(self.brain)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].relative_to(self.brain).as_posix(), "ingest/proposals/wiki/topics/example.md")
        text = proposals[0].read_text(encoding="utf-8")
        for expected in ("Date:", "Page: wiki/topics/example.md", "Why: New evidence", "Agent proposal"):
            self.assertIn(expected, text)
        self.assertIn("Human addition", (self.brain / "wiki/topics/example.md").read_text(encoding="utf-8"))
        self.assertIn(proposals[0].name, self.run_tool("wiki_edits.py", "proposals").stdout)
        self.assertEqual(self.run_tool("wiki_edits.py", "propose", "../../notes/note.md", "--from", source).returncode, 2)
        self.assertEqual(self.run_tool("wiki_edits.py", "propose", "topics/example.md", "--from", source).returncode, 2)

    def test_proposals_use_page_paths_and_list_legacy_files(self):
        self.write("ingest/proposals/example.md", "# Proposed wiki change\n\nDate: 2026-01-01\nPage: wiki/methods/example.md\n")
        source = self.root / "proposal.md"
        brainlib.write_text(source, PAGE)
        for name in ("rules/example.md", "topics/example.md"):
            result = self.run_tool("wiki_edits.py", "propose", name, "--from", source)
            self.assertEqual(result.returncode, 0, result.stderr)
        duplicate = self.run_tool("wiki_edits.py", "propose", "methods/example.md", "--from", source)
        self.assertEqual(duplicate.returncode, 2)
        result = self.run_tool("wiki_edits.py", "proposals")
        self.assertEqual(result.stdout.splitlines(), ["ingest/proposals/example.md",
                                                      "ingest/proposals/wiki/rules/example.md",
                                                      "ingest/proposals/wiki/topics/example.md"])

    def test_index_preserves_human_pages_and_records_own_output(self):
        self.write("wiki/sources/lesson.md", "---\ntype: source\nsources: []\nupdated: 2026-01-01\nmodule: Example\nlesson: Lesson\nurl: https://example.com\nduration: 90\n---\n# Lesson\n")
        self.init_wiki()
        original = PAGE + "Human addition\n"
        self.write("wiki/topics/example.md", original)
        result = self.run_tool("build_wiki_index.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("left 1 human-edited pages alone", result.stdout)
        self.assertEqual((self.brain / "wiki/topics/example.md").read_text(encoding="utf-8"), original)
        self.assertEqual(wiki_edits.status(self.brain), {"topics/example.md": "changed"})
        self.assertIn('duration: "1:30"', (self.brain / "wiki/sources/lesson.md").read_text(encoding="utf-8"))
        self.assertEqual(self.run_tool("wiki_edits.py", "accept", "--all").returncode, 0)
        self.assertEqual(wiki_edits.status(self.brain), {})

    def test_index_protects_both_human_indexes_and_duration(self):
        self.write("wiki/sources/lesson.md", "---\ntype: source\nduration: 90\n---\n# Lesson\n")
        self.init_wiki()
        result = self.run_tool("build_wiki_index.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(wiki_edits.status(self.brain), {})
        baseline = wiki_edits.manifest(self.brain).read_bytes()
        self.write("wiki/index.md", "# My index\n")
        self.write("wiki/sources-index.md", "# My sources index\n")
        self.write("wiki/sources/lesson.md", "---\ntype: source\nduration: 120\n---\n# My lesson\n")
        self.assertEqual(self.run_tool("wiki_edits.py", "begin").returncode, 0)
        result = self.run_tool("build_wiki_index.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.brain / "wiki/index.md").read_text(encoding="utf-8"), "# My index\n")
        self.assertEqual((self.brain / "wiki/sources-index.md").read_text(encoding="utf-8"), "# My sources index\n")
        self.assertIn("duration: 120", (self.brain / "wiki/sources/lesson.md").read_text(encoding="utf-8"))
        self.assertEqual(wiki_edits.manifest(self.brain).read_bytes(), baseline)
        self.assertEqual(wiki_edits.status(self.brain), {"index.md": "changed", "sources-index.md": "changed",
                                                       "sources/lesson.md": "changed"})
        proposals = {p.relative_to(self.brain).as_posix(): p.read_text(encoding="utf-8") for p in wiki_edits.proposals(self.brain)}
        self.assertEqual(set(proposals), {"ingest/proposals/wiki/index.md", "ingest/proposals/wiki/sources-index.md"})
        self.assertIn("[[sources-index]]", proposals["ingest/proposals/wiki/index.md"])
        self.assertIn("- [[lesson|My lesson]]", proposals["ingest/proposals/wiki/sources-index.md"])
        # A later rebuild refreshes an existing auto-generated index proposal.
        self.write("wiki/topics/added.md", PAGE.replace("# Example", "# Added Topic"))
        self.assertEqual(self.run_tool("build_wiki_index.py").returncode, 0)
        refreshed = (self.brain / "ingest/proposals/wiki/index.md").read_text(encoding="utf-8")
        self.assertIn("[[added]]", refreshed)
        # A proposal filed with wiki_edits propose is never overwritten by a rebuild.
        (self.brain / "ingest/proposals/wiki/index.md").unlink()  # the auto proposal was reviewed and dropped
        mine = self.brain / "agent-index.md"
        mine.write_text("# Agent's index proposal\n", encoding="utf-8")
        self.assertEqual(self.run_tool("wiki_edits.py", "propose", "index.md", "--from", str(mine)).returncode, 0)
        filed = (self.brain / "ingest/proposals/wiki/index.md").read_text(encoding="utf-8")
        self.assertIn("# Agent's index proposal", filed)
        result = self.run_tool("build_wiki_index.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("open proposal", result.stdout)
        self.assertEqual((self.brain / "ingest/proposals/wiki/index.md").read_text(encoding="utf-8"), filed)

    def test_notes_are_ignored_and_index_lists_them_without_writing(self):
        self.write("notes/unstructured.md", "No frontmatter [[missing]]\n")
        before = (self.brain / "notes/unstructured.md").read_bytes()
        self.init_wiki()
        for tool in ("check_wiki.py", "lint_wiki.py", "rule_status.py", "build_wiki_index.py"):
            result = self.run_tool(tool)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.brain / "notes/unstructured.md").read_bytes(), before)
        index = (self.brain / "wiki/index.md").read_text(encoding="utf-8")
        self.assertIn("## Your notes", index)
        self.assertIn("[[notes/unstructured]]", index)
        self.assertEqual(self.run_tool("check_wiki.py", self.brain / "notes/unstructured.md").returncode, 0)
        self.assertEqual(wiki_edits.status(self.brain), {})

    def test_wiki_must_not_cite_notes(self):
        self.write("notes/idea.md", "An idea\n")
        self.write("wiki/topics/example.md", PAGE.replace("sources: []", "sources: [notes/idea.md]"))
        errors = []
        check_wiki.check_page(self.brain, self.brain / "wiki/topics/example.md", errors)
        self.assertTrue(any("must not cite human-owned notes" in e for e in errors))

    def test_raw_guard_initial_record_check_and_changes(self):
        result = self.run_tool("raw_guard.py", "record", "--init")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.brain / "raw/.capture-hashes.json").exists())
        self.assertEqual(self.run_tool("raw_guard.py", "check").returncode, 0)
        self.write("raw/source.md", "Edited after capture\n")
        self.write("raw/new.md", "Unknown capture\n")
        result = self.run_tool("raw_guard.py", "check")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("changed:", result.stdout)
        self.assertIn("1 raw files have no capture hash yet", result.stdout)
        self.assertEqual(raw_guard.unrecorded(self.brain / "raw"), ["new.md"])
        self.assertNotIn("new.md", raw_guard.check(self.brain / "raw"))
        (self.brain / "raw/source.md").unlink()
        self.assertEqual(raw_guard.check(self.brain / "raw")["source.md"], "deleted")

    def test_partial_manifest_from_capture_is_not_a_change_and_record_adopts_unrecorded(self):
        self.write("raw/older.md", "Captured before the guard\n")
        raw_guard.record_capture(self.brain / "raw/source.md")
        self.assertEqual(raw_guard.check(self.brain / "raw"), {})
        self.assertEqual(raw_guard.unrecorded(self.brain / "raw"), ["older.md"])
        result = self.run_tool("raw_guard.py", "check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("1 raw files have no capture hash yet", result.stdout)
        result = self.run_tool("raw_guard.py", "record")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(raw_guard.unrecorded(self.brain / "raw"), [])
        self.assertEqual(self.run_tool("raw_guard.py", "check").returncode, 0)
        self.write("raw/older.md", "Edited\n")
        self.assertEqual(self.run_tool("raw_guard.py", "record").returncode, 2)

    def test_lint_without_baselines_says_so_instead_of_flagging_everything(self):
        result = self.run_tool("lint_wiki.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no wiki edit baseline yet", result.stdout)
        self.assertNotIn("human-edited", result.stdout)
        self.assertNotIn("raw changed after capture", result.stdout)

    def test_library_shared_writer_records_only_its_own_file(self):
        (self.root / "library").mkdir()
        library_raw.init(self.root)
        first = library_raw.raw_path("publisher", "book", "", "First")
        library_raw.write_raw(first, {}, "Original\n")
        raw = first.parent.parent
        self.assertTrue((raw.parent / ".capture-hashes.json").exists())
        self.assertEqual(raw_guard.check(raw), {})
        first.write_text("Human modification\n", encoding="utf-8")
        second = library_raw.raw_path("publisher", "book", "", "Second")
        library_raw.write_raw(second, {}, "New capture\n")
        self.assertEqual(raw_guard.check(raw), {"book/first.md": "changed"})
        self.assertEqual(self.run_tool("raw_guard.py", "check", scope="workspace").returncode, 1)
        self.assertEqual(self.run_tool("raw_guard.py", "record", "--init", scope="workspace").returncode, 0)
        self.assertEqual(raw_guard.check(raw), {})

    def test_workspace_check_finds_missing_raw_using_capture_manifests(self):
        raw = self.root / "library/acme/raw"
        brainlib.write_text(raw / "source.md", "Captured library words\n")
        raw_guard.record(raw, init=True)
        raw_guard.record(self.brain / "raw", init=True)
        self.assertEqual(self.run_tool("raw_guard.py", "check", scope="workspace").returncode, 0)
        (raw / "source.md").unlink()
        raw.rmdir()
        (self.brain / "raw/source.md").unlink()
        result = self.run_tool("raw_guard.py", "check", scope="workspace")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        for missing in (raw / "source.md", self.brain / "raw/source.md"):
            self.assertIn(f"deleted: {missing}", result.stdout)
        self.assertIn("2 raw files changed after capture", result.stdout)

    def test_lint_fails_for_changed_captures_and_warns_for_edits_and_proposals(self):
        self.init_wiki()
        raw_guard.record(self.brain / "raw", init=True)
        self.write("wiki/topics/example.md", PAGE + "Human addition\n")
        self.write("raw/source.md", "Human modification\n")
        self.write("ingest/proposals/example.md", "Proposed change")
        brainlib.write_text(self.root / "library/cited/raw/source.md", "Captured\n")
        brainlib.write_text(self.root / "library/unrelated/raw/source.md", "Captured\n")
        raw_guard.record(self.root / "library/cited/raw", init=True)
        brainlib.write_text(self.root / "library/cited/raw/source.md", "Human modification\n")
        self.write("wiki/topics/cited.md", PAGE.replace("sources: []", "sources: [library/cited/raw/source.md]") + "([[library/cited/raw/source]] @ page text)\n")
        result = self.run_tool("lint_wiki.py")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("2 human-edited pages; 1 open proposals", result.stdout)
        self.assertEqual(result.stdout.count("raw changed after capture: re-crawl instead of editing"), 2)
        self.assertNotIn("unrelated", result.stdout)

    def test_lint_during_open_pass_distinguishes_agent_edits_from_protected_pages(self):
        self.write("wiki/topics/agent.md", PAGE)
        self.init_wiki()
        self.write("wiki/topics/example.md", PAGE + "Human addition\n")
        self.assertEqual(self.run_tool("wiki_edits.py", "begin").returncode, 0)
        self.write_agent("topics/agent.md", PAGE + "Agent addition\n")
        result = self.run_tool("lint_wiki.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("warning: 1 protected human-edited pages; 0 open proposals", result.stdout)
        self.assertNotIn("2 human-edited", result.stdout)
        self.write("wiki/topics/example.md", PAGE + "Agent clobber\n")
        failed = self.run_tool("lint_wiki.py")
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        self.assertIn("error: protected page changed during pass: wiki/topics/example.md", failed.stdout)

    def test_known_agent_write_does_not_accept_other_edits(self):
        self.init_wiki()
        self.write("wiki/topics/example.md", PAGE + "Human addition\n")
        self.write("wiki/index.md", "# Generated index\n")
        with contextlib.redirect_stdout(io.StringIO()):
            wiki_edits.record(self.brain, written={"index.md": wiki_edits.hashes.digest(self.brain / "wiki/index.md")})
        self.assertEqual(wiki_edits.status(self.brain), {"topics/example.md": "changed"})

    def test_parallel_captures_keep_every_hash(self):
        raw_guard.record(self.brain / "raw", init=True)
        paths = [self.brain / "raw" / f"capture-{n}.md" for n in range(8)]
        for path in paths:
            brainlib.write_text(path, "New capture\n")
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(raw_guard.record_capture, paths))
        self.assertEqual(raw_guard.check(self.brain / "raw"), {})


if __name__ == "__main__":
    unittest.main()

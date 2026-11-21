"""Wiki human-edit protection, human-owned notes and captured-source integrity."""
import contextlib
from concurrent.futures import ThreadPoolExecutor
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import brainlib
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
        self.write("wiki/topics/agent.md", PAGE + "Agent addition\n")
        self.write("wiki/topics/new-agent-page.md", PAGE)
        result = self.run_tool("build_wiki_index.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(wiki_edits.pass_file(self.brain).exists())
        self.assertEqual(wiki_edits.status(self.brain), {"topics/example.md": "changed"})
        result = self.run_tool("wiki_edits.py", "accept", "topics/example.md")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(wiki_edits.status(self.brain), {})

    def test_begin_requires_baseline(self):
        with self.assertRaises(ValueError):
            wiki_edits.begin(self.brain)

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
        self.assertEqual(proposals[0].name, "example.md")
        text = proposals[0].read_text(encoding="utf-8")
        for expected in ("Date:", "Page: wiki/topics/example.md", "Why: New evidence", "Agent proposal"):
            self.assertIn(expected, text)
        self.assertIn("Human addition", (self.brain / "wiki/topics/example.md").read_text(encoding="utf-8"))
        self.assertIn(proposals[0].name, self.run_tool("wiki_edits.py", "proposals").stdout)
        self.assertEqual(self.run_tool("wiki_edits.py", "propose", "../../notes/note.md", "--from", source).returncode, 2)
        self.assertEqual(self.run_tool("wiki_edits.py", "propose", "topics/example.md", "--from", source).returncode, 2)

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

    def test_index_protects_human_index_and_duration(self):
        self.write("wiki/index.md", "# Index\n")
        self.write("wiki/sources/lesson.md", "---\ntype: source\nduration: 90\n---\n# Lesson\n")
        self.init_wiki()
        self.write("wiki/index.md", "# My index\n")
        self.write("wiki/sources/lesson.md", "---\ntype: source\nduration: 120\n---\n# My lesson\n")
        result = self.run_tool("build_wiki_index.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.brain / "wiki/index.md").read_text(encoding="utf-8"), "# My index\n")
        self.assertIn("duration: 120", (self.brain / "wiki/sources/lesson.md").read_text(encoding="utf-8"))
        self.assertEqual(len(wiki_edits.status(self.brain)), 2)
        self.assertEqual(len(wiki_edits.proposals(self.brain)), 1)

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
        self.assertIn("added:", result.stdout)
        (self.brain / "raw/source.md").unlink()
        self.assertEqual(raw_guard.check(self.brain / "raw")["source.md"], "deleted")

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

    def test_lint_warns_for_edits_proposals_and_cited_raw_only(self):
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
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("2 human-edited pages; 1 open proposals", result.stdout)
        self.assertEqual(result.stdout.count("raw changed after capture: re-crawl instead of editing"), 2)
        self.assertNotIn("unrelated", result.stdout)

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

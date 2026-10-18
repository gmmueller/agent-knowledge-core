"""Topic checker contracts with generated fixtures.

Run: python -I tests/test_topic_checkers.py --scratch <private-scratch-dir>.
"""
import argparse
import contextlib
import csv
import datetime as dt
import io
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

sys.dont_write_bytecode = True
SCRATCH = None
TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import check_wiki as check
import lint_wiki as lint
import refresh_due as refresh
import triage_merge as triage
import requote

BOOK = "library/example-publisher/raw/book/example-book"
QUOTE = "These are the exact fixture words."


class TopicCheckers(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="topic-checkers-", dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.brain = self.root / "topic-fixture"
        self.write("topic-fixture/brain.md", "---\nkind: topic\ntriage: {weight_fresh: false}\n---\n")
        self.write(BOOK + ".md", "---\nspeakers: [Alex Author, Blair Author]\n---\n**[p. 2]**\nOther words.\n**[p. 3]**\nA buffer page.\n**[p. 15]**\n" + QUOTE + "\n")
        self.write("library/people.yaml", "sample-expert:\n  name: Sample Expert\n  aliases: [Sample]\n")
        self.write("library/test/raw/yt/interview.md", "---\nspeakers: [Sample Expert, Host Person]\n---\n"
                   "**[12:41]** Sample Expert: Teach the real words.\n"
                   "**[13:12]** Host Person: Different host words.\n"
                   "**[14:00]** Sample Expert: Note: keep this prefix.\n")
        check.frontmatter.cache_clear()
        check._raw_cache.clear()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        check.frontmatter.cache_clear()
        check._raw_cache.clear()
        return path

    def page(self, speaker="Alex Author and Blair Author", quote=QUOTE, at="p. 15", raw=BOOK, **extra):
        fm = {"type": "source", "sources": [raw], "updated": dt.date.today(),
              "publisher": "example-publisher", "item": "book-example-book", "url": "https://example.com", **extra}
        section = "Key claims" if fm["type"] == "source" else "Key points"
        quote_line = f'> "{quote}" — {speaker} ([[{raw}]] @ {at})\n' if quote else ""
        return self.write("topic-fixture/wiki/sources/test-page.md",
                          "---\n" + yaml.safe_dump(fm) + "---\n\n## " + section + "\n"
                          f'- Claim ([[{raw}]] @ {at})\n\n' + quote_line)

    def errors(self, path):
        errors = []
        check.check_page(self.brain, path, errors)
        return "\n".join(errors)

    def test_book_quotes_and_failures(self):
        for speaker in ("Alex Author", "Blair Author", "Alex Author and Blair Author"):
            self.assertEqual(self.errors(self.page(speaker=speaker)), "")
        for kwargs, expected in (({"at": "p. 99999"}, "no block 'p. 99999'"),
                                 ({"at": "p. 2"}, "quote not at p. 2"),
                                 ({"quote": "Invented quote words."}, "quote not at"),
                                 ({"speaker": ""}, "missing speaker"),
                                 ({"speaker": "Someone Else"}, "block speaker 'Alex Author, Blair Author'")):
            self.assertIn(expected, self.errors(self.page(**kwargs)))

    def test_transcript_speakers_aliases_and_text(self):
        raw = "library/test/raw/yt/interview"
        for speaker in ("Sample Expert", "Sample"):
            self.assertEqual(self.errors(self.page(speaker=speaker, quote="Teach the real words.", at="12:41", raw=raw)), "")
        self.assertIn("block speaker 'Sample Expert'", self.errors(self.page(speaker="Host Person", quote="Teach the real words.", at="12:41", raw=raw)))
        self.assertIn("quote not at", self.errors(self.page(speaker="Sample", quote="Different host words.", at="12:41", raw=raw)))
        self.assertEqual(self.errors(self.page(speaker="Sample", quote="Note: keep this prefix.", at="14:00", raw=raw)), "")
        blocks = check.raw_index(self.brain, raw)["blocks"]
        self.assertEqual(blocks[0], ("12:41", "Teach the real words."))
        self.assertEqual(check.raw_index(self.brain, raw)["block_speakers"][0], "Sample Expert")
        self.assertEqual(requote.best_match(check.raw_index(self.brain, raw), "Teach the real words.")[0], 1.0)

    def test_paragraphs_timestamps_and_persona_default(self):
        raw = "library/test/raw/web/article"
        self.write(raw + ".md", "---\nspeakers: [Sample Expert]\n---\n**[¶12]** Note: exact web words.\n")
        self.assertEqual(self.errors(self.page(speaker="Sample", quote="Note: exact web words.", at="¶12", raw=raw)), "")
        self.assertIn("no block '¶99'", self.errors(self.page(speaker="Sample", quote="Note: exact web words.", at="¶99", raw=raw)))
        self.write("topic-fixture/raw/transcript.md", "---\nspeakers: [Sample Expert]\n---\n**[1:02:03]** Sample Expert: Hour words.\n")
        self.assertEqual(self.errors(self.page(speaker="Sample", quote="Hour words.", at="1:02:04", raw="raw/transcript")), "")
        self.write("topic-fixture/brain.md", "---\nkind: persona\ndefault_speaker: Custom Name\n---\n")
        self.assertEqual(self.errors(self.page(speaker="", quote="Hour words.", at="1:02:03", raw="raw/transcript", type="topic")), "")

    def test_schema_types_dates_statuses_and_source_fields(self):
        for kind in ("example", "rubric", "debate", "tool"):
            extra = {"reviewed": "2026-01-01", "recheck_by": "2026-02-01"} if kind == "tool" else {}
            self.assertEqual(self.errors(self.page(type=kind, **extra)), "")
        self.assertIn("evidence must", self.errors(self.page(evidence="unknown")))
        self.assertIn("freshness must", self.errors(self.page(freshness="unknown")))
        self.assertIn("requires 'reviewed' date", self.errors(self.page(type="tool")))
        self.assertIn("requires 'recheck_by' date", self.errors(self.page(type="tool", reviewed="2026-01-01", recheck_by="bad")))
        self.assertEqual(self.errors(self.page(type="rule", status="consensus")), "")
        rule = self.page(type="rule", status="contested")
        self.assertIn("link to a debate page", self.errors(rule))
        self.write("topic-fixture/wiki/debates/disagreement.md", "---\ntype: debate\nsources: []\nupdated: 2026-01-01\n---\n## Key points\n")
        rule.write_text(rule.read_text(encoding="utf-8") + "\n[[disagreement]]\n", encoding="utf-8")
        self.assertEqual(self.errors(rule), "")
        page = self.page()
        page.write_text(page.read_text(encoding="utf-8").replace("publisher: example-publisher\n", ""), encoding="utf-8")
        self.assertIn("source page missing 'publisher'", self.errors(page))
        self.write("topic-fixture/brain.md", "---\nkind: persona\n---\n")
        self.assertIn("rule needs status", self.errors(self.page(type="rule", status="consensus")))

    def test_staging_matches_topic_schema(self):
        concept = {"slug": "test-rule", "type": "rule", "status": "consensus", "quotes": [
            {"speaker": "Alex Author", "text": QUOTE, "cite": {"raw": BOOK, "at": "p. 15"}}]}
        def errors():
            path = self.write("topic-fixture/ingest/staging/test.yaml", yaml.safe_dump({"concepts": [concept]}))
            result = []
            check.check_staging(self.brain, path, result)
            return "\n".join(result)
        self.assertEqual(errors(), "")
        del concept["quotes"][0]["speaker"]
        self.assertIn("missing speaker", errors())
        concept.update(type="tool", evidence="bad", freshness="bad")
        self.assertIn("requires 'reviewed' date", errors())
        self.assertIn("evidence must", errors())
        self.assertIn("freshness must", errors())

    def test_nested_quotes_and_markdown_escapes(self):
        raw = "library/test/raw/yt/nested"
        self.write(raw + ".md", '---\nspeakers: [Sample Expert]\n---\n'
                   '**[0:00]** Sample Expert: Say "hello" before \\(starting\\).\n')
        self.assertEqual(self.errors(self.page(speaker="Sample", quote='Say "hello" before (starting).',
                                              raw=raw, at="0:00")), "")

    def test_custom_evidence_and_additional_staging_citations(self):
        self.assertEqual(self.errors(self.page(evidence="synthesis", freshness="dated")), "")
        self.write("topic-fixture/brain.md", "---\nkind: topic\nevidence_types: [rulebook, expert]\n---\n")
        for evidence in ("rulebook", "expert", "inference"):
            self.assertEqual(self.errors(self.page(evidence=evidence)), "")
        self.assertIn("evidence must", self.errors(self.page(evidence="research")))
        for key in ("findings", "tropes", "equipment", "examples"):
            path = self.write("topic-fixture/ingest/staging/test.yaml", yaml.safe_dump({key: [
                {"cite": {"raw": BOOK, "at": "p. 99999"}}]}))
            errors = []
            check.check_staging(self.brain, path, errors)
            self.assertIn("no block 'p. 99999'", "\n".join(errors))

    def test_example_seconds_sources_and_lint_links(self):
        raw = "library/test/examples/video"
        self.write(raw + ".yaml", "duration_s: 10\n")
        for rel in (raw, raw + ".yaml"):
            self.assertEqual(self.errors(self.page(type="example", raw=rel, at="10.5s", quote="")), "")
        self.assertIn("past the end", self.errors(self.page(type="example", raw=raw, at="10.6s", quote="")))
        self.assertIn("quotes must cite a raw transcript", self.errors(self.page(raw=raw, at="1s")))
        self.assertIn("cite an example as", self.errors(self.page(raw=raw, at="0:00", quote="")))
        self.assertIn("only for examples/ files", self.errors(self.page(at="1s")))
        self.page(type="example", raw=raw, at="1s", quote="")
        with patch.object(sys, "argv", ["lint_wiki.py", "--brain", str(self.brain)]), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                lint.main()
        self.assertEqual(result.exception.code, 0)

    def test_thread_anchors_author_and_default_speaker(self):
        raw = "raw/community/thread"
        self.write("topic-fixture/brain.md", "---\nkind: persona\ndefault_speaker: Sample Expert\n---\n")
        self.write("topic-fixture/" + raw + ".md", "---\nmethod: skool-api\n---\n"
                   "**Sample Expert** (@expert) · 2026-01-01 12:00\nOpening words.\n"
                   "## Comments\n"
                   "**Member Person** (@member) · 2026-01-01 12:01 · c:1234abcd\nMember words.\n"
                   "> **Sample Expert** (@expert) · **ADMIN** · 2026-01-01 12:02 · c:abcd1234\n> Reply words.\n")
        self.assertEqual(self.errors(self.page(type="topic", raw=raw, at="post", quote="Opening words.", speaker="")), "")
        self.assertEqual(self.errors(self.page(type="topic", raw=raw, at="c:1234abcd", quote="Member words.", speaker="Member Person")), "")
        self.assertEqual(self.errors(self.page(type="topic", raw=raw, at="c:abcd1234", quote="Reply words.", speaker="")), "")
        self.assertIn("was written by 'Member Person'", self.errors(self.page(type="topic", raw=raw, at="c:1234abcd", quote="Member words.", speaker="")))
        self.assertIn("found at c:1234abcd", self.errors(self.page(type="topic", raw=raw, at="post", quote="Member words.", speaker="Member Person")))
        self.assertIn("no 'c:ffffffff'", self.errors(self.page(type="topic", raw=raw, at="c:ffffffff", quote="")))

    def test_cli_external_brain(self):
        self.page()
        result = subprocess.run([sys.executable, "-X", "utf8", "-I", "-B", str(TOOLS / "check_wiki.py"), "--brain", str(self.brain)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "ok: 1 files"), result.stderr)

    def test_lint_library_links(self):
        page = self.page(type="example")
        output = io.StringIO()
        with patch.object(sys, "argv", ["lint_wiki.py", "--brain", str(self.brain)]), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as result:
                lint.main()
        self.assertEqual(result.exception.code, 0)
        self.assertIn("broken link targets: 0", output.getvalue())
        page.write_text(page.read_text(encoding="utf-8") + "[[library/missing/raw/nope]]", encoding="utf-8")
        with patch.object(sys, "argv", ["lint_wiki.py", "--brain", str(self.brain)]), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                lint.main()
        self.assertEqual(result.exception.code, 1)

    def test_refresh_library_and_tool_pages(self):
        self.page(type="tool", reviewed="2020-01-01", recheck_by="2020-02-01")
        self.write("library/test/sources.yaml", "sources:\n- id: channel\n  refresh: daily\n  last_crawled: 2020-01-01\n")
        output = io.StringIO()
        with patch.object(sys, "argv", ["refresh_due.py", "--workspace", str(self.root)]), contextlib.redirect_stdout(output):
            refresh.main()
        self.assertIn("library/test / channel", output.getvalue())
        self.assertIn("topic-fixture / wiki/sources/test-page.md", output.getvalue())

    def test_triage_tiers_sort_freshness_and_overrides(self):
        fields = ["item", *triage.SCORES, "example", "speakers", "why"]
        path = self.root / "topic-fixture/ingest/triage/test.tsv"
        path.parent.mkdir(parents=True)
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, delimiter="\t")
            writer.writerow(fields)
            for row in [("p/a", 3, 3, 3, 0, 0, 0), ("p/fresh", 2, 2, 2, 1, 3, 0),
                        ("p/b", 2, 1, 1, 0, 0, 0), ("p/c", 1, 3, 3, 3, 3, 0),
                        ("p/x", 0, 0, 0, 0, 0, 1), ("p/override", 0, 0, 0, 0, 0, 0)]:
                writer.writerow([*row, "Sample; Host Person", "reason"])
        self.write("topic-fixture/selection.yaml", yaml.safe_dump({"items": [
            {"item": "p/override", "tier": "B", "override": "A", "scores": dict.fromkeys(triage.SCORES, 0)}]}))
        with contextlib.redirect_stdout(io.StringIO()) as output:
            triage.merge(self.brain)
        self.assertEqual(output.getvalue().strip(), "A: 1 B: 3 C: 1 X: 1")
        items = yaml.safe_load((self.brain / "selection.yaml").read_text(encoding="utf-8"))["items"]
        self.assertEqual([i["item"] for i in items], ["p/a", "p/fresh", "p/b", "p/override", "p/c", "p/x"])
        self.assertEqual(items[3]["override"], "A")
        self.assertEqual(items[0]["speakers"], ["Sample", "Host Person"])
        self.write("topic-fixture/brain.md", "---\nkind: topic\ntriage: {weight_fresh: true}\n---\n")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            triage.merge(self.brain)
        self.assertEqual(output.getvalue().strip(), "A: 2 B: 2 C: 1 X: 1")
        result = subprocess.run([sys.executable, "-X", "utf8", "-I", "-B", str(TOOLS / "triage_merge.py"), "--brain", str(self.brain)],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "A: 2 B: 2 C: 1 X: 1"), result.stderr)
        original = (self.brain / "selection.yaml").read_text(encoding="utf-8")
        with path.open("a", encoding="utf-8") as stream:
            stream.write("p/invalid\t9\t0\t0\t0\t0\t0\t\tbad\n")
        with self.assertRaises(ValueError):
            triage.merge(self.brain)
        self.assertEqual((self.brain / "selection.yaml").read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=pathlib.Path, required=True)
    args, remaining = parser.parse_known_args()
    SCRATCH = args.scratch.resolve()
    if not SCRATCH.is_dir():
        parser.error("--scratch must be an existing private scratch directory")
    unittest.main(argv=[sys.argv[0], *remaining])

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
        self.root = pathlib.Path(self.temp.name).resolve()
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

    def test_paragraph_quote_must_be_in_the_cited_block(self):
        raw = "library/test/raw/web/paragraphs"
        self.write(raw + ".md", "**[¶1]** Opening text.\n**[¶2]** The exact quoted words.\n")
        self.assertEqual(self.errors(self.page(quote="The exact quoted words.", at="¶2", raw=raw)), "")
        self.assertIn("quote not at ¶1", self.errors(self.page(quote="The exact quoted words.", at="¶1", raw=raw)))
        self.assertEqual(self.errors(self.page(at="p. 3")), "")  # PDF pages still tolerate adjacent quotes

    def test_eval_attribution_handles_unicode_and_parenthetical_speakers(self):
        raw = "library/test/raw/yt/discussion"
        quote = "Keep a fresh copy of each draft."
        answers = self.brain / "answers.md"
        for speaker in ("Éloi Varen", "Tessa Vale (Draft Room)", "Mira O’Venn"):
            with self.subTest(speaker=speaker):
                self.write(raw + ".md", f"---\nspeakers: [{speaker}, Kel Orin]\n---\n"
                           f"**[0:00]** {speaker}: {quote}\n**[0:10]** Kel Orin: {quote}\n")
                for at, code, message in (("0:00", 0, "1 attributed quotes checked, 0 problems"),
                                           ("0:10", 1, "does not match block speaker 'Kel Orin'")):
                    self.write("topic-fixture/answers.md", f'“{quote}” — {speaker} ([[{raw}]] @ {at})\n')
                    result = subprocess.run([sys.executable, "-X", "utf8", "-I", "-B",
                                             str(TOOLS / "verify_eval_quotes.py"), "--brain", str(self.brain), str(answers)],
                                            capture_output=True, text=True, encoding="utf-8")
                    self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                    self.assertIn(message, result.stdout)

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
        self.write("topic-fixture/raw/transcript.md", "---\nduration: 1:02:05\nspeakers: [Sample Expert]\n---\n**[1:02:03]** Sample Expert: Hour words.\n")
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
            {"speaker": "Alex Author", "text": QUOTE, "stance": "supports", "cite": {"raw": BOOK, "at": "p. 15"}}]}
        def errors():
            path = self.write("topic-fixture/ingest/staging/test.yaml", yaml.safe_dump({"concepts": [concept]}))
            result = []
            check.check_staging(self.brain, path, result)
            return "\n".join(result)
        self.assertEqual(errors(), "")
        concept["quotes"][0]["stance"] = "oppose"
        self.assertIn("stance must be one of", errors())
        concept["quotes"][0]["stance"] = "opposes"
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

    def test_inline_code_inside_quotes_is_checked_verbatim(self):
        raw = "library/test/raw/yt/code"
        self.write(raw + ".md", "---\nspeakers: [Sample Expert]\n---\n"
                   "**[0:00]** Sample Expert: Run `example` every day.\n")
        page = self.page(speaker="Sample", quote="Run `example` every day.", raw=raw, at="0:00")
        self.assertEqual(self.errors(page), "")
        self.assertIn("quote not", self.errors(self.page(speaker="Sample", quote="Run `invented` every day.",
                                                          raw=raw, at="0:00")))

    def test_citations_checked_individually_and_evidence_prose_checked(self):
        page = self.page()
        text = page.read_text(encoding="utf-8")
        page.write_text(text + f"\n## Evidence\nAn unsupported paragraph.\n\n"
                              f"A separate supported paragraph.\n([[{BOOK}]] @ p. 15)\n\n"
                              f"## Links\n([[{BOOK}]] @ p. 15; [[{BOOK}]] @ p. 15oops)\n",
                        encoding="utf-8")
        errors = self.errors(page)
        self.assertIn("evidence claim without citation: An unsupported paragraph.", errors)
        self.assertEqual(errors.count("claim without citation"), 1)
        uncited = [line for line in errors.splitlines() if "claim without citation" in line]
        self.assertTrue(uncited[0].startswith(check.WARNING), "uncited prose only warns")
        page.write_text(text + "\n## Key points\n- An unsupported bullet.\n", encoding="utf-8")
        uncited = [line for line in self.errors(page).splitlines() if "claim without citation" in line]
        self.assertIn("key points claim without citation", uncited[0])
        self.assertFalse(uncited[0].startswith(check.WARNING), "uncited bullets in claim sections fail")
        self.assertIn("raw link without a valid '@ <locator>'", errors)
        page.write_text(text + "\n## Key points\n\n", encoding="utf-8")
        self.assertIn("empty 'Key Points' section", self.errors(page))
        page.write_text(text.replace("## Key claims", "## Key points"), encoding="utf-8")
        self.assertEqual(self.errors(page), "")

    def test_claim_sections_allow_list_introductions_and_navigation(self):
        page = self.page(quote="")
        text = page.read_text(encoding="utf-8")
        text = text.replace("## Key claims\n", "## Key claims\nThe following is an outline:\n")
        page.write_text(text + "\nSee [[context]] and [background](https://example.com/).\n\n"
                              "**Local procedure (Inference):** A possible way to apply it.\n", encoding="utf-8")
        self.assertEqual(self.errors(page), "")

    def test_timestamp_bounds_with_and_without_duration(self):
        raw = "library/test/raw/yt/timed"
        blocks = "**[0:10]** Opening words.\n**[0:30]** Last block.\n"
        self.write(raw + ".md", f'---\nduration: "0:45"\n---\n{blocks}')
        self.assertEqual(self.errors(self.page(quote="", at="0:45", raw=raw)), "")
        self.assertIn("past the end", self.errors(self.page(quote="", at="0:46", raw=raw)))
        self.assertEqual(self.errors(self.page(quote="Last block.", at="0:10", raw=raw)), "")
        self.write(raw + ".md", blocks)
        self.assertIn("before first block", self.errors(self.page(quote="", at="0:09", raw=raw)))
        self.assertEqual(self.errors(self.page(quote="", at="0:30", raw=raw)), "")
        self.assertEqual(self.errors(self.page(quote="Last block.", speaker="Sample Expert", at="0:31", raw=raw)), "")
        self.assertIn("quote not at 0:31", self.errors(self.page(quote="Invented words.", at="0:31", raw=raw)))

    def test_page_text_attribution_requires_the_speakers_words(self):
        raw = "library/test/raw/yt/turns"
        self.write(raw + ".md", "---\nspeakers: [Sample Expert, Bea]\n---\n"
                   "**[0:00]** Sample Expert: The start\n"
                   "**[0:05]** Sample Expert: of the turn.\n"
                   "**[0:10]** Bea: Someone else's words.\n"
                   "**[0:15]** Sample Expert: A later turn.\n")
        for speaker, quote in (("Sample", "The start of the turn."), ("Bea", "Someone else's words.")):
            self.assertEqual(self.errors(self.page(speaker=speaker, quote=quote, at="page text", raw=raw)), "")
        for quote in ("Someone else's words.", "of the turn. A later turn."):
            self.assertIn("not spoken by", self.errors(self.page(speaker="Sample", quote=quote, at="page text", raw=raw)))
        mixed = "library/test/raw/yt/mixed"
        self.write(mixed + ".md", "---\nspeakers: [Sample Expert]\n---\n**[0:00]** Sample Expert: Spoken words.\n\n"
                   "## Lesson page text\n\nWritten lesson instructions.\n")
        self.assertEqual(self.errors(self.page(speaker="Sample", quote="Written lesson instructions.",
                                               at="page text", raw=mixed)), "")
        self.write("topic-fixture/brain.md", "---\nkind: persona\ndefault_speaker: Sample Expert\n---\n")
        self.assertIn("not spoken by", self.errors(self.page(type="topic", speaker="", quote="Someone else's words.",
                                                             at="page text", raw=raw)))
        self.write(raw + ".md", "---\nspeakers: [Sample Expert]\n---\nText without labelled turns.\n")
        self.assertEqual(self.errors(self.page(type="topic", speaker="", quote="Text without labelled turns.",
                                                at="page text", raw=raw)), "")

    def test_people_loaded_once_per_workspace(self):
        raw = "library/test/raw/yt/interview"
        with patch.object(check.brainlib, "load_yaml", wraps=check.brainlib.load_yaml) as load:
            for speaker in ("Sample Expert", "Sample"):
                self.assertEqual(self.errors(self.page(speaker=speaker, quote="Teach the real words.", at="12:41", raw=raw)), "")
            load.assert_called_once_with(self.root / "library/people.yaml", {})

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
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "ok: 2 files"), result.stderr)

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

    def test_refresh_due_reports_captured_sources_with_no_date(self):
        self.write("library/acme/sources.yaml", """sources:
- id: captured-docs
  refresh: quarterly
  last_crawled:
  url: https://example.com/docs/
- id: catalogue-only
  refresh: monthly
  last_crawled:
  url: https://other.example/
- id: manual-doc
  refresh: manual
  last_crawled:
""")
        self.write("library/acme/catalogue.tsv", "id\turl\tsource\nweb-pending\thttps://other.example/pending\tcatalogue-only\n")
        self.write("library/acme/raw/web/guide.md", "---\nsource_id: web-guide\nurl: https://example.com/docs/guide\n---\nCaptured.\n")
        for flags in ([], ["--all"]):
            output = io.StringIO()
            argv = ["refresh_due.py", "--workspace", str(self.root), *flags]
            with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output):
                refresh.main()
            text = output.getvalue()
            self.assertIn("**library/acme / captured-docs**: quarterly, date missing", text)
            self.assertNotIn("**library/acme / catalogue-only**", text)
            self.assertEqual("catalogue-only: monthly, not crawled yet" in text, bool(flags))
            self.assertEqual("manual-doc: manual, no reminder" in text, bool(flags))

    def test_triage_tiers_sort_freshness_and_overrides(self):
        fields = ["item", *triage.SCORES, "example", "speakers", "why"]
        path = self.root / "topic-fixture/ingest/triage/test.tsv"
        path.parent.mkdir(parents=True)
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, delimiter="\t")
            writer.writerow(fields)
            for row in [("p/a", 3, 3, 3, 1, 0, 0), ("p/fresh", 2, 2, 2, 1, 3, 0),
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

    def test_triage_keeps_and_sorts_unscored_overrides(self):
        self.write("topic-fixture/selection.yaml", yaml.safe_dump({"items": [
            {"item": "acme/z", "override": "A", "why": "Added by hand"},
            {"item": "acme/a", "override": "A"},
            {"item": "acme/scored", "tier": "A", "scores": dict.fromkeys(triage.SCORES, 1)},
            {"item": "acme/example", "override": "X"}]}))
        with contextlib.redirect_stdout(io.StringIO()):
            triage.merge(self.brain)
        items = yaml.safe_load((self.brain / "selection.yaml").read_text(encoding="utf-8"))["items"]
        self.assertEqual([(i["item"], i["tier"]) for i in items],
                         [("acme/scored", "A"), ("acme/a", "A"), ("acme/z", "A"), ("acme/example", "X")])
        self.assertEqual(items[2]["why"], "Added by hand")
        self.assertNotIn("scores", items[2])

    def test_triage_duplicates_require_an_override_for_tier_a(self):
        self.write("topic-fixture/ingest/triage/acme.tsv", "\t".join(["item", *triage.SCORES, "example", "speakers", "why"])
                   + "\nacme/replay\t3\t3\t3\t0\t3\t0\tAda\tRepeat\nacme/clip\t3\t3\t3\t0\t3\t0\tAda\tClip\n")
        self.write("topic-fixture/selection.yaml", "items: [{item: acme/clip, override: A}]\n")
        with contextlib.redirect_stdout(io.StringIO()):
            triage.merge(self.brain)
        items = yaml.safe_load((self.brain / "selection.yaml").read_text(encoding="utf-8"))["items"]
        self.assertEqual({i["item"]: i["tier"] for i in items}, {"acme/clip": "A", "acme/replay": "B"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=pathlib.Path, required=True)
    args, remaining = parser.parse_known_args()
    SCRATCH = args.scratch.resolve()
    if not SCRATCH.is_dir():
        parser.error("--scratch must be an existing private scratch directory")
    unittest.main(argv=[sys.argv[0], *remaining])

"""Offline regression coverage for PDF/HTML selection and portable brain loaders."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import book_to_raw as book
import generate_persona as persona
import library_raw as lr
import requote
import web_to_raw as web


class ExampleFixes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="example-fixes-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "library").mkdir()
        lr.init(self.root)
        self.brain = self.root / "my-topic"
        self.brain.mkdir()
        self.write(self.brain / "brain.md", "---\nkind: topic\n---\n")

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def call(self, module, *args):
        output = io.StringIO()
        with patch.object(sys, "argv", [module.__name__, *map(str, args)]), contextlib.redirect_stdout(output):
            module.main()
        return output.getvalue()

    def front(self, path):
        return yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])

    def test_book_selection_catalogue_log_and_immutability(self):
        lr.merge_catalogue("author", [{"id": "book-sample", "title": "Old title", "source": "author-books"},
                                     {"id": "book-other", "title": "Other book"}])
        pages = [Mock() for _ in range(4)]
        for i, page in enumerate(pages, 1):
            page.extract_text.return_value = f"Original PDF page {i}."
        args = ["--workspace", self.root, "author", "sample.pdf", "--slug", "sample",
                "--title", "Sample Book", "--author", "An Author", "--published", "1916",
                "--pages", "2,4", "--url", "https://example.com/book"]
        with patch.object(book, "PdfReader", return_value=SimpleNamespace(pages=pages)):
            self.call(book, *args)
            path = self.root / "library/author/raw/book/sample.md"
            original = path.read_bytes()
            body = original.decode("utf-8")
            self.assertIn("**[p. 2]**\nOriginal PDF page 2.", body)
            self.assertIn("**[p. 4]**\nOriginal PDF page 4.", body)
            self.assertNotIn("**[p. 1]**", body)
            self.assertNotIn("**[p. 3]**", body)
            pages[0].extract_text.assert_not_called()
            pages[2].extract_text.assert_not_called()
            self.assertEqual(str(self.front(path)["published"]), "1916")
            self.assertEqual(self.front(path)["publication_precision"], "year")
            rows = lr.read_catalogue("author")
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows["book-sample"]["title"], "Sample Book")
            self.assertEqual(rows["book-sample"]["published"], "1916")
            self.assertEqual(rows["book-sample"]["source"], "author-books")
            log = self.root / "library/author/crawl-log.md"
            logged = log.read_bytes()
            self.assertRegex(logged.decode(), r"^- \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d fetched: library")
            with self.assertRaises(FileExistsError):
                self.call(book, *args)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(log.read_bytes(), logged)

    def test_page_ranges_validate_deduplicate_and_keep_order(self):
        self.assertEqual(book.page_selection("4,1-2,2", 4), {1, 2, 4})
        self.assertEqual(book.page_selection(None, 3), {1, 2, 3})
        for value in ("", "0", "1-5", "3-2", "1,", "x", "-1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                book.page_selection(value, 4)

    def test_partial_dates_and_filenames(self):
        for value, prefix in (("1916", "19160000"), ("1916-02", "19160200"), ("1916-02-29", "19160229")):
            with self.subTest(value=value):
                self.assertEqual(lr.publication_date(value), value)
                self.assertEqual(web.date(value), value)
                self.assertEqual(lr.raw_path("author", "paper", value, "Sample").name, prefix + "-sample.md")
        self.assertEqual(web.date("2026-01-02T12:00:00Z"), "2026-01-02")
        self.assertEqual(web.date("Tue, 10 Oct 2023 00:00:00 GMT"), "2023-10-10")
        self.assertEqual(web.date(""), "")
        self.assertEqual(lr.raw_path("author", "web", "", "Sample").name, "00000000-sample.md")
        for value in ("0000", "1916-00", "1916-13", "1917-02-29", "1916-1", "unknown"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                lr.publication_date(value)

    def test_book_month_precision(self):
        with patch.object(book, "PdfReader", return_value=SimpleNamespace(pages=[Mock(extract_text=lambda: "Page words.")])):
            self.call(book, "--workspace", self.root, "author", "sample.pdf", "--slug", "sample",
                      "--title", "Sample Book", "--author", "An Author", "--published", "1916-02")
        front = self.front(self.root / "library/author/raw/book/sample.md")
        self.assertEqual(front["published"], "1916-02")
        self.assertEqual(front["publication_precision"], "month")

    def test_section_bounds_and_ambiguous_or_missing_headings(self):
        blocks = ["Introduction", "## Keep", "Selected words.", "## Stop", "Excluded words."]
        self.assertEqual(web.select_sections(blocks, "Keep", "Stop"), blocks[1:3])
        self.assertEqual(web.select_sections(blocks, to_heading="Stop"), blocks[:3])
        self.assertEqual(web.select_sections(blocks, from_heading="Keep"), blocks[1:])
        self.assertEqual(web.select_sections(blocks), blocks)
        for start, end in (("Missing", None), (None, "Missing"), ("Stop", "Keep"), ("Keep", "Keep")):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                web.select_sections(blocks, start, end)
        with self.assertRaises(ValueError):
            web.select_sections(blocks + ["## Keep"], "Keep")

    def test_web_selection_is_applied_before_raw_write(self):
        args = SimpleNamespace(publisher="author", items=None, catalogue=False, urls=["https://example.com/book"],
                               limit=None, transcript=False, recapture=False, kind="doc", from_heading="Keep", to_heading="Stop")
        client = Mock()
        client.get.return_value = ("<html></html>", args.urls[0])
        with patch.object(web, "paragraphs", return_value=["Outside", "## Keep", "Selected words.", "## Stop", "Excluded"]), \
                patch.object(web, "metadata", return_value=("Sample", "1916", "")), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(web.fetch(args, {"sources": []}, client), 0)
        path = self.root / "library/author/raw/web/19160000-sample.md"
        text = path.read_text(encoding="utf-8")
        self.assertIn("**[¶1]** ## Keep", text)
        self.assertIn("**[¶2]** Selected words.", text)
        self.assertNotIn("Excluded", text)
        self.assertNotIn("Outside", text)
        self.assertEqual(self.front(path)["publication_precision"], "year")

    def test_core_templates_are_subject_neutral(self):
        for template in (persona.SKILL, persona.TOPIC_SKILL):
            for text in ("platform", "video", "views", "virality", "algorithm"):
                self.assertNotIn(text, template.lower())

    def test_brain_guidance_boundaries_and_examples_folder(self):
        fm = {"skill": {"guidance": ["Date every platform claim."], "boundaries": ["Never promise results."]}}
        values = persona.customization(self.brain, fm)
        self.assertEqual(values["examples_folder"], "")
        self.assertIn("## This brain's guidance\n\n- Date every platform claim.\n", values["guidance"])
        self.assertEqual(values["boundaries"], "- Never promise results.\n")
        self.write(self.brain / "wiki/examples/demo.md", "---\ntype: example\n---\n")
        values = persona.customization(self.brain, {})
        self.assertIn("Worked examples are in `examples/`", values["examples_folder"])
        self.assertEqual((values["guidance"], values["boundaries"]), ("", ""))
        with self.assertRaises(ValueError):
            persona.customization(self.brain, {"skill": {"guidance": [3]}})

    def test_suggestions_follow_brain_contents_and_stop_once_guidance_exists(self):
        self.write(self.brain / "wiki/topics/fact.md", "---\ntype: topic\nfreshness: platform\n---\n")
        fm = {"evidence_types": ["practitioner", "official"], "hosts": ["Interviewer"]}
        hints = " | ".join(persona.suggestions(self.brain, fm))
        for text in ("official sources", "time-sensitive", "practitioner's claim", "interviewers"):
            self.assertIn(text, hints)
        self.assertEqual(persona.suggestions(self.brain, {**fm, "skill": {"guidance": ["x"]}}), [])
        self.assertEqual(persona.suggestions(self.brain / "missing", {}), [])

    def test_relative_paths_for_topic_and_persona_default_unchanged(self):
        for kind in ("topic", "course"):
            self.write(self.brain / "brain.md", "---\nname: my-topic\ndisplay_name: My Topic\nkind: " + kind + "\n"
                       "updated: '2026-01-01'\nskill:\n  description: Consult this topic.\n"
                       "  short_description: Topic methods\n  default_prompt: Use $my-topic.\n---\n")
            out = self.root / "skills"
            self.call(persona, "--brain", self.brain, "--out", out)
            path = out / "my-topic/SKILL.md"
            self.assertIn(str(self.brain / "brain.md"), path.read_text(encoding="utf-8"))
            default = path.read_bytes()
            agent = (out / "my-topic/agents/openai.yaml").read_bytes()
            self.call(persona, "--brain", self.brain, "--out", out, "--relative-to", self.root)
            text = path.read_text(encoding="utf-8")
            self.assertIn("`my-topic/brain.md`", text)
            self.assertNotIn(str(self.root), text)
            self.assertIn("normal generate_persona.py use writes absolute paths", text)
            self.assertEqual((out / "my-topic/agents/openai.yaml").read_bytes(), agent)
            self.call(persona, "--brain", self.brain, "--out", out)
            self.assertEqual(path.read_bytes(), default)

    def test_reference_skill_cites_editions_and_only_names_existing_checks(self):
        card = ("---\nname: my-topic\ndisplay_name: My Topic\nkind: topic\n"
                "skill:\n  description: Consult this topic.\n  short_description: Topic sources\n"
                "  default_prompt: Use $my-topic.\n")
        card_path = self.brain / "brain.md"
        self.write(card_path, card + "evidence_model: reference\n---\n")
        out = self.root / "skills"
        path = out / "my-topic" / "SKILL.md"
        args = ("--brain", self.brain, "--out", out)
        self.call(persona, *args)
        text = path.read_text(encoding="utf-8")
        self.assertIn("source title, its version or publication date", text)
        self.assertNotIn("whose method", text)
        self.assertNotIn("rubric", text)
        self.assertNotIn("checklist", text)
        self.write(self.brain / "wiki/methods/inspect-output.md", "# Inspect output\n\n## Checklist\n")
        self.call(persona, *args)
        text = path.read_text(encoding="utf-8")
        self.assertIn("`inspect-output.md`", text)
        self.assertIn("check the result against the applicable checklist", text)
        self.assertNotIn("rubric", text)
        self.write(card_path, card + "experts: [Sample Expert]\n---\n")
        self.write(self.brain / "wiki/rubrics/sample.md", "# Sample rubric\n")
        self.call(persona, *args)
        text = path.read_text(encoding="utf-8")
        self.assertIn("whose method", text)
        self.assertIn("check the result against the relevant rubric", text)
        self.assertNotIn("checklist", text)

    def test_requote_paragraph_page_and_timestamp_in_markdown_and_staging(self):
        for label, old in (("¶12", "¶2"), ("p. 37", "p. 2"), ("1:30", "0:00")):
            with self.subTest(label=label):
                slug = "sample-" + str(len(list(self.brain.glob("raw/*.md"))))
                self.write(self.brain / f"raw/{slug}.md", f"---\nspeakers: [An Author]\n---\n**[{label}]**\nKeep all these exact words.\n")
                page = self.write(self.brain / "wiki/topics/sample.md", f'> "Keep all these exact words." — An Author and Another Author ([[raw/{slug}]] @ {old})\n')
                staging = self.write(self.brain / "ingest/staging/sample.yaml", f'concepts:\n  - quotes:\n      - text: "Keep all these exact words."\n        cite:\n          raw: raw/{slug}\n          at: "{old}"\n')
                args = ["--brain", self.brain, f"raw/{slug}", page, staging]
                self.assertIn("would fix", self.call(requote, *args))
                self.assertIn(old, page.read_text(encoding="utf-8"))
                self.call(requote, *args, "--apply")
                self.assertIn(f"@ {label})", page.read_text(encoding="utf-8"))
                data = yaml.safe_load(staging.read_text(encoding="utf-8"))
                self.assertEqual(data["concepts"][0]["quotes"][0]["cite"]["at"], label)
                self.assertEqual(self.call(requote, *args, "--apply"), "")


if __name__ == "__main__":
    unittest.main()

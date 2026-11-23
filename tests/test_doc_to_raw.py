"""Offline document fixtures and citation checks."""
import hashlib
import importlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import brainlib
import check_wiki
import doc_to_raw as docs
import library_raw as lr
import raw_guard


class DocumentCapture(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        self.brain = self.root / "reference"
        brainlib.write_text(self.brain / "brain.md", "---\nkind: topic\nevidence_model: reference\n---\n")
        lr.init(self.root)

    def optional(self, name):
        try:
            return importlib.import_module(name)
        except ImportError:
            self.skipTest(f"{name} is not installed")

    def capture(self, src, expected):
        path = docs.capture("standards", src)
        front = brainlib.read_frontmatter(path)
        self.assertEqual(front["source_sha256"], hashlib.sha256(src.read_bytes()).hexdigest())
        self.assertTrue(front["parser"].startswith("local:"))
        self.assertIn(front["source_id"], lr.read_catalogue("standards"))
        raw = lr.pub_dir("standards") / "raw"
        self.assertEqual(raw_guard.unrecorded(raw), [])
        self.assertEqual(raw_guard.check(raw), {})
        rel = path.relative_to(self.root).as_posix()
        for label, quote in expected:
            with self.subTest(label=label):
                cite = check_wiki.CITE.fullmatch(f"[[{rel}]] @ {label}")
                self.assertIsNotNone(cite)
                errors = []
                check_wiki.check_cite(self.brain, *cite.groups(), quote, "fixture", errors)
                self.assertEqual(errors, [])
        return path, rel

    def test_pdf_uses_text_layer_and_warns_for_empty_page(self):
        pypdf = self.optional("pypdf")
        fitz = self.optional("fitz")
        src = self.root / "handbook.pdf"
        with fitz.open() as pdf:
            pdf.new_page().insert_text((72, 72), "Confirm the setting.")
            pdf.new_page()
            pdf.save(src)
        with patch.object(docs, "which", return_value=None), patch.object(docs.sys, "stderr") as stderr:
            path, rel = self.capture(src, [("p. 1", "Confirm the setting."), ("p. 2", None)])
        self.assertIn("no extractable text", "".join(call.args[0] for call in stderr.write.call_args_list))
        self.assertEqual(len(pypdf.PdfReader(src).pages), 2)
        errors = []
        check_wiki.check_cite(self.brain, rel, "p. 2", "Confirm the setting.", "fixture", errors)
        self.assertIn("quote not at p. 2", errors[0])
        self.assertEqual(brainlib.read_frontmatter(path)["parser"], "local:pypdf")

    def test_pdf_only_ocr_pages_without_text(self):
        fitz = self.optional("fitz")
        self.optional("pypdf")
        src = self.root / "scan.pdf"
        with fitz.open() as pdf:
            pdf.new_page().insert_text((72, 72), "Use the text layer.")
            pdf.new_page()
            pdf.save(src)
        with patch.object(docs, "which", return_value="tesseract"), \
                patch.object(docs.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"Scanned page.")) as ocr:
            path, _ = self.capture(src, [("p. 1", "Use the text layer."), ("p. 2", "Scanned page.")])
        ocr.assert_called_once()
        self.assertTrue(ocr.call_args.kwargs["input"].startswith(b"\x89PNG"))
        self.assertEqual(brainlib.read_frontmatter(path)["parser"], "local:pypdf+tesseract")

    def test_docx_paragraphs_and_table(self):
        docx = self.optional("docx")
        src = self.root / "manual.docx"
        document = docx.Document()
        document.add_paragraph("First paragraph.")
        document.add_table(rows=1, cols=1).cell(0, 0).text = "Table text."
        document.add_paragraph("Last paragraph.")
        document.save(src)
        self.capture(src, [("¶ 1", "First paragraph."), ("¶2", "Table text."), ("¶3", "Last paragraph.")])

    def test_pptx_uses_exact_slide(self):
        pptx = self.optional("pptx")
        src = self.root / "slides.pptx"
        presentation = pptx.Presentation()
        for title in ("First slide.", "Second slide."):
            presentation.slides.add_slide(presentation.slide_layouts[0]).shapes.title.text = title
        presentation.save(src)
        _, rel = self.capture(src, [("slide 1", "First slide."), ("slide 2", "Second slide.")])
        errors = []
        check_wiki.check_cite(self.brain, rel, "slide 1", "Second slide.", "fixture", errors)
        check_wiki.check_cite(self.brain, rel, "slide 3", None, "fixture", errors)
        self.assertIn("quote not at slide 1", errors[0])
        self.assertIn("no block 'slide 3'", errors[1])
        answers = self.root / "answers.md"
        brainlib.write_text(answers, f'"Second slide." ([[{rel}]] @ slide 1)\n')
        result = subprocess.run([sys.executable, "-X", "utf8", "-I", str(TOOLS / "verify_eval_quotes.py"),
                                 "--brain", str(self.brain), str(answers)],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("quote not at slide 1", result.stdout)

    def test_xlsx_cells_and_quoted_sheet_names(self):
        openpyxl = self.optional("openpyxl")
        src = self.root / "budget.xlsx"
        workbook = openpyxl.Workbook()
        workbook.active["A1"] = 0
        workbook.create_sheet("Team's Budget")["B2"] = "=Sheet!A1+5"
        workbook.save(src)
        _, rel = self.capture(src, [("Sheet!A1", "0"), ("'Team''s Budget'!B2", "=Sheet!A1+5")])
        errors = []
        check_wiki.check_cite(self.brain, rel, "Sheet!A1", "=Sheet!A1+5", "fixture", errors)
        self.assertIn("quote not at Sheet!A1", errors[0])

    def test_text_markdown_and_html_paragraphs(self):
        self.optional("bs4")
        fixtures = {"notes.txt": "First line.\n\nSecond line.",
                    "notes.md": "# Heading\n\nSecond line.",
                    "notes.html": "<head><title>Hidden</title></head><section>"
                                  "<p>First <b>line.</b></p><p>Second line.</p></section><script>Hidden</script>"}
        for name, content in fixtures.items():
            with self.subTest(name=name):
                src = self.root / name
                src.write_text(content, encoding="utf-8")
                path, _ = self.capture(src, [("¶1", "# Heading" if name.endswith(".md") else "First line."),
                                             ("¶2", "Second line.")])
                self.assertNotIn("Hidden", path.read_text(encoding="utf-8"))

    def test_model_and_local_are_distinct_immutable_captures(self):
        src = self.root / "guide.txt"
        src.write_text("Local extraction.", encoding="utf-8")
        command = self.root / "parser.py"
        command.write_text("import json, pathlib, sys\n"
                           "assert pathlib.Path(sys.argv[1]).read_bytes() == b'Local extraction.'\n"
                           "print(json.dumps({'blocks': [{'at': '\\u00b6 1', 'text': 'Model extraction.'}]}))\n",
                           encoding="utf-8")
        brainlib.write_text(self.root / "workspace.yaml", yaml.safe_dump(
            {"doc_parser": {"command": [sys.executable, "-I", str(command)], "model": "fake-model"}}))
        model = docs.model_config(self.root)
        local = docs.capture("standards", src, slug="guide-v1")
        parsed = docs.capture("standards", src, config=model, slug="guide-v1")
        self.assertNotEqual(parsed, local)
        self.assertIn("Model extraction.", parsed.read_text(encoding="utf-8"))
        front = brainlib.read_frontmatter(parsed)
        self.assertEqual(front["parser"], "model:fake-model")
        self.assertEqual(front["source_id"], brainlib.read_frontmatter(local)["source_id"])
        with patch.object(docs, "model_blocks", side_effect=AssertionError("parser should not run again")):
            self.assertEqual(parsed, docs.capture("standards", src, config=model, slug="guide-v1"))
        self.assertIn("Local extraction.", local.read_text(encoding="utf-8"))

    def test_invalid_model_locators_rejected(self):
        src = self.root / "data.xlsx"
        payload = {"blocks": [{"at": "sheet 1 row 2", "text": "A row."}]}
        with patch.object(docs.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(payload))):
            self.assertEqual(docs.model_blocks(src, (["parser"], "fake"))[0], [("sheet 1 row 2", "A row.")])
            self.assertIsNotNone(check_wiki.CITE.fullmatch("[[library/standards/raw/data]] @ sheet 1 row 2"))
        payload["blocks"].append({"at": "sheet 1 row 2", "text": "Duplicate."})
        with patch.object(docs.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(payload))):
            with self.assertRaisesRegex(ValueError, "duplicate"):
                docs.model_blocks(src, (["parser"], "fake"))

    def test_folder_cli_captures_supported_files(self):
        brainlib.write_text(self.root / "inputs" / "nested" / "guide.md", "A guide.")
        brainlib.write_text(self.root / "inputs" / "ignore.jpg", "Ignored.")
        result = subprocess.run([sys.executable, "-X", "utf8", "-I", str(TOOLS / "doc_to_raw.py"),
                                 "--workspace", str(self.root), "standards", str(self.root / "inputs")],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(lr.read_catalogue("standards")), 1)
        self.assertIn("fetched:", (lr.pub_dir("standards") / "crawl-log.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

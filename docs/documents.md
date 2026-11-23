# Capture local documents

`doc_to_raw.py` reads local PDF, DOCX, PPTX, XLSX, TXT, Markdown and HTML files. Give it file paths or folders. It walks folders recursively and skips unsupported files inside them.

```sh
python -m pip install -r requirements-docs.txt
python -X utf8 -I tools/doc_to_raw.py --workspace ../my-brains standards handbook.pdf --slug handbook-v2 --published 2026-03-01
python -X utf8 -I tools/doc_to_raw.py --workspace ../my-brains standards ./reference-files
```

Captures go in `library/<publisher>/raw/doc/`. Each one records `source_sha256` for the input bytes and `parser` for the backend and library or model. The tool registers the raw hash and updates the publisher's catalogue and crawl log. It reuses an identical recorded capture. New bytes or a different parser configuration get a new raw file. Use a distinct `--slug` for each edition, such as `handbook-v2`, which gives it the source ID `doc-handbook-v2`. Without a slug, the ID includes a short input hash. The source ID stays the same when you change backends for the same document.

| Format | Citation locator |
|---|---|
| PDF | `p. 3` for the third PDF page |
| PPTX | `slide 2` |
| XLSX | `Sheet1!A1` or `'Budget Q1'!A1` for a cell. Model commands can also emit `sheet 1 row 2` for a row |
| DOCX, TXT, Markdown, HTML | `¶2` or `¶ 2` |

Cite the actual raw path with the locator, for example `([[library/standards/raw/doc/<capture>]] @ p. 3)`. To quote a reference document without a named author, use `> "Quoted words." — ([[library/standards/raw/doc/<capture>]] @ p. 3)`.

## Choose a backend

The default `--backend local` is free and works well for clean digital documents. It extracts visible text and spreadsheet cell values or formulas. Layout, charts and embedded images can need a different parser. For a PDF page with no text layer, it tries OCR if Tesseract is on PATH. It warns when a page still has no text.

Use `--backend model` when scans or difficult layouts need a model. Configure your own command in the private workspace's `workspace.yaml`. The framework supplies no provider or credentials. If you have OpenAI access, `gpt-6.1-terra` is a suggested cost and accuracy balance. It beat traditional OCR on PDFs in the maintainer's use.

```yaml
doc_parser:
  command: ["python", "/path/to/your_document_parser.py"]
  model: gpt-6.1-terra
```

The tool appends the absolute input file path to the argument list and runs the command without a shell. It expects UTF-8 JSON on stdout with one `{at, text}` object per block in document order. For a PDF or presentation, return one block per page or slide and preserve its original number. The command can render pages to images and call a model endpoint. Keep diagnostics on stderr and provider credentials in your own environment.

```json
{"blocks": [{"at": "p. 1", "text": "Extracted first page."}]}
```

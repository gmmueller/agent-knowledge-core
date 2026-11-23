"""Capture local documents into the shared library. See docs/documents.md."""
import argparse
import datetime as dt
import hashlib
import importlib
import io
import json
import pathlib
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib
import document_locators as locators
import library_raw as lr
import raw_guard

FORMATS = {".pdf": "pypdf", ".docx": "python-docx", ".pptx": "python-pptx", ".xlsx": "openpyxl",
           ".txt": "text", ".md": "text", ".html": "beautifulsoup4", ".htm": "beautifulsoup4"}
PACKAGES = {"python-docx": "docx", "python-pptx": "pptx", "beautifulsoup4": "bs4", "pymupdf": "fitz"}
LABELS = {".pdf": r"p\. [1-9]\d*", ".pptx": r"slide [1-9]\d*",
          ".xlsx": rf"(?:sheet [1-9]\d* row [1-9]\d*|{locators.SHEET_CELL})"}


def dependency(package):
    try:
        return importlib.import_module(PACKAGES.get(package, package))
    except ImportError as exc:
        raise ValueError(f"install {package} to capture this format (see requirements-docs.txt)") from exc


def pdf_blocks(src, content):
    reader = dependency("pypdf").PdfReader(io.BytesIO(content))
    tesseract = shutil.which("tesseract")
    renderer = None
    used_ocr = False
    blocks = []
    try:
        for number, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip()
            if not text and tesseract:
                try:
                    if renderer is None:
                        renderer = dependency("pymupdf").open(stream=content, filetype="pdf")
                    image = renderer[number - 1].get_pixmap(dpi=300).tobytes("png")
                    result = subprocess.run([tesseract, "stdin", "stdout"], input=image, capture_output=True,
                                            check=True, timeout=120)
                    text = result.stdout.decode("utf-8").strip()
                    used_ocr = True
                except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                    print(f"warning: {src.name} p. {number}: OCR failed: {exc}", file=sys.stderr)
            if not text:
                hint = "use the model backend" if tesseract else "install Tesseract or use the model backend"
                print(f"warning: {src.name} p. {number}: no extractable text; {hint}", file=sys.stderr)
            blocks.append((f"p. {number}", text))
    finally:
        if renderer is not None:
            renderer.close()
    return blocks, "local:pypdf+tesseract" if used_ocr else "local:pypdf"


def docx_paragraphs(container):
    for element in container.iter_inner_content():
        if hasattr(element, "text"):
            yield element.text
        else:
            for row in element.rows:
                for cell in row.cells:
                    yield from docx_paragraphs(cell)


def slide_text(shapes):
    for shape in shapes:
        if shape.has_text_frame:
            yield shape.text
        elif shape.has_table:
            for row in shape.table.rows:
                yield " | ".join(cell.text for cell in row.cells)
        elif hasattr(shape, "shapes"):
            yield from slide_text(shape.shapes)


def html_paragraphs(parser, content):
    soup = parser.BeautifulSoup(content, "html.parser")
    for node in soup(["script", "style", "head", "template", "noscript"]):
        node.decompose()
    for node in soup.find_all(["address", "article", "blockquote", "br", "div", "dl", "dt", "dd",
                               "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "pre", "section", "td", "th"]):
        node.insert_before("\n\n")
        node.insert_after("\n\n")
    return re.split(r"\n[ \t]*\n", soup.get_text())


def local_blocks(src, content):
    suffix = src.suffix.lower()
    package = FORMATS[suffix]
    if suffix == ".pdf":
        return pdf_blocks(src, content)
    stream = io.BytesIO(content)
    if suffix == ".pptx":
        slides = dependency(package).Presentation(stream).slides
        blocks = [(f"slide {i}", "\n".join(slide_text(slide.shapes))) for i, slide in enumerate(slides, 1)]
    elif suffix == ".xlsx":
        workbook = dependency(package).load_workbook(stream, read_only=True)
        try:
            blocks = [(locators.cell(sheet.title, cell.coordinate), str(cell.value))
                      for sheet in workbook.worksheets for row in sheet.iter_rows() for cell in row
                      if cell.value is not None]
        finally:
            workbook.close()
    else:
        if suffix == ".docx":
            paragraphs = docx_paragraphs(dependency(package).Document(stream))
        elif suffix in {".html", ".htm"}:
            paragraphs = html_paragraphs(dependency(package), content)
        else:
            paragraphs = re.split(r"\n[ \t]*\n", content.decode("utf-8-sig").replace("\r\n", "\n"))
        blocks = [(f"¶{i}", paragraph) for i, paragraph in enumerate((p for p in paragraphs if p.strip()), 1)]
    return blocks, f"local:{package}"


def model_config(workspace):
    config = (brainlib.load_yaml(workspace / "workspace.yaml") or {}).get("doc_parser") or {}
    command, model = config.get("command"), config.get("model")
    if not (isinstance(command, list) and command and all(isinstance(arg, str) and arg for arg in command)
            and isinstance(model, str) and model.strip()):
        raise ValueError("--backend model requires doc_parser.command (argument list) and doc_parser.model in workspace.yaml")
    return command, model


def model_blocks(src, config):
    command, model = config
    # The command receives an absolute path. The owner configures the parser, including any provider access.
    result = subprocess.run([*command, str(src)], capture_output=True, check=True, timeout=300)
    try:
        rows = json.loads(result.stdout)["blocks"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("document parser must return a JSON object containing a blocks array") from exc
    if not isinstance(rows, list) or not rows:
        raise ValueError("document parser blocks must be a non-empty JSON array")
    blocks = []
    seen = set()
    allowed = LABELS.get(src.suffix.lower(), r"¶[1-9]\d*")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("at"), str) or not isinstance(row.get("text"), str):
            raise ValueError("each document parser block must have string at and text fields")
        label = locators.normalize(row["at"])
        if label in seen or not re.fullmatch(allowed, label):
            raise ValueError(f"invalid or duplicate document parser locator: {label!r}")
        seen.add(label)
        blocks.append((label, row["text"]))
    return blocks, f"model:{model}"


def capture(publisher, src, *, config=None, slug=None, published=None):
    content = src.read_bytes()
    source_hash = hashlib.sha256(content).hexdigest()
    suffix = src.suffix.lower()
    identity = f"doc-{slug}" if slug else f"doc-{lr.slugify(src.stem)}-{suffix[1:]}-{source_hash[:12]}"
    capture_key = f"{identity}-{source_hash[:12]}" if slug else identity
    parser_key = json.dumps(config) if config is not None else f"local:{FORMATS[suffix]}"
    if config is None and suffix == ".pdf" and shutil.which("tesseract"):
        parser_key += "+tesseract"
    parser_hash = hashlib.sha256(parser_key.encode("utf-8")).hexdigest()[:12]
    raw = lr.pub_dir(publisher) / "raw"
    target = raw / "doc" / f"{capture_key}-{parser_hash}.md"
    if target.exists():
        recorded = raw_guard.hashes.load(raw_guard.manifest(raw)) or {}
        expected = recorded.get(target.relative_to(raw).as_posix())
        if not raw_guard.hashes.matches(raw_guard.hashes.file_hashes(target), expected):
            raise ValueError(f"existing capture has no matching recorded hash: {target}")
        front = brainlib.read_frontmatter(target)
        if front.get("source_sha256") != source_hash or front.get("source_id") != identity:
            raise FileExistsError(f"source identity or hash differs from existing capture: {target}")
        lr.merge_catalogue(publisher, [dict(id=identity, kind="doc", title=front["title"],
                                            published=front.get("published"))])
        print(f"already captured {target.relative_to(lr.ROOT).as_posix()}")
        return target
    if config is None:
        blocks, parser = local_blocks(src, content)
    else:
        blocks, parser = model_blocks(src, config)
        if hashlib.sha256(src.read_bytes()).hexdigest() != source_hash:
            raise ValueError(f"input changed during parsing: {src.name}")
    front = {"source_id": identity, "publisher": publisher, "title": src.stem, "kind": "doc", "file": src.name,
             "method": "document", "parser": parser, "source_sha256": source_hash}
    if published:
        front["published"] = published
    body = "\n".join(f"**[{label}]** {lr.clean_field(text.replace(chr(0), '�'))}\n"
                     for label, text in blocks)
    if not any(text.strip() for _, text in blocks):
        print(f"warning: {src.name}: captured no text", file=sys.stderr)
    lr.write_raw(target, front, body)
    lr.merge_catalogue(publisher, [dict(id=identity, kind="doc", title=src.stem, published=published)])
    rel = target.relative_to(lr.ROOT)
    with (lr.pub_dir(publisher) / "crawl-log.md").open("a", encoding="utf-8") as log:
        log.write(f"- {dt.datetime.now().isoformat(timespec='seconds')} fetched: {rel.as_posix()} ({parser})\n")
    print(f"wrote {rel.as_posix()} ({len(blocks)} blocks, {parser})")
    return target


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_workspace_arg(ap)
    ap.add_argument("publisher", help="publisher slug under library/")
    ap.add_argument("paths", nargs="+", type=pathlib.Path, help="local files or folders (searched recursively)")
    ap.add_argument("--backend", choices=("local", "model"), default="local")
    ap.add_argument("--slug", help="source slug for one file")
    ap.add_argument("--published", type=lr.publication_date, help="publication date, YYYY, YYYY-MM or YYYY-MM-DD")
    args = ap.parse_args()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.publisher):
        ap.error("publisher must be a kebab-case slug")
    inputs = set()
    for path in args.paths:
        path = path.expanduser().resolve()
        if path.is_dir():
            inputs.update(p for p in brainlib.iter_files(path) if p.suffix.lower() in FORMATS)
        elif path.is_file() and path.suffix.lower() in FORMATS:
            inputs.add(path)
        else:
            ap.error(f"missing file or unsupported format: {path}")
    if not inputs:
        ap.error("no supported documents found")
    if args.slug and (len(inputs) != 1 or len(args.slug) > 60
                      or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.slug)):
        ap.error("--slug requires one input file and a kebab-case slug of up to 60 characters")
    lr.init(args.workspace)
    try:
        config = model_config(lr.ROOT) if args.backend == "model" else None
        for src in sorted(inputs):
            capture(args.publisher, src, config=config, slug=args.slug, published=args.published)
    except subprocess.CalledProcessError as exc:
        ap.exit(2, f"document parser command exited with code {exc.returncode}\n")
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        ap.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()

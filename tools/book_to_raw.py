"""Turn a user-supplied ebook PDF (text layer) into library/<publisher>/raw/book/<slug>.md, one block per page.

Usage:
  tools/.venv/Scripts/python -I tools/book_to_raw.py <publisher> <pdf> --workspace <workspace> --slug example-book \
      --title "Example Book" --author "Example Author" --published 2026-01-01 [--url URL] [--isbn ISBN] [--drop-line REGEX]

--drop-line drops whole lines matching REGEX (repeatable), e.g. a watermark: --drop-line "ExampleWatermark".
--page-numbering TEXT replaces the default page_numbering note; --extra key=value (repeatable) adds frontmatter fields
(venue, version, licence...). Typographic ligatures (U+FB00-FB06, e.g. "fi") are expanded to plain letters.

Line wraps are joined; a line ending in "-" joins the next line without a space (the hyphen is kept).
p. N = PDF page N. Check the first pages first (docs/build-pipeline.md: user-supplied PDFs). Refuses to overwrite.
"""
import argparse
import os
import pathlib
import re
import sys

from pypdf import PdfReader

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib
import library_raw as lr  # noqa: E402


LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}


def join_lines(text: str, drop: list[re.Pattern] = ()) -> str:
    out = ""
    for line in (l.strip() for l in text.splitlines()):
        if not line or any(d.fullmatch(line) for d in drop):
            continue
        out += line if (not out or out.endswith("-")) else " " + line
    for lig, plain in LIGATURES.items():
        out = out.replace(lig, plain)
    out = out.replace("\x00", "�")  # unmapped glyphs (often CJK) arrive as NUL, which breaks text tools
    return re.sub(r"[ \t]+", " ", out).strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    brainlib.add_workspace_arg(ap)
    ap.add_argument("publisher")
    ap.add_argument("pdf", type=pathlib.Path)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--author", required=True, action="append")
    ap.add_argument("--published", required=True)
    ap.add_argument("--url", default=None)
    ap.add_argument("--isbn", default=None)
    ap.add_argument("--page-numbering", default=None)
    ap.add_argument("--extra", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--drop-line", action="append", default=[], help="regex; whole lines matching it are dropped (watermarks)")
    a = ap.parse_args()
    lr.init(a.workspace)

    drop = [re.compile(d) for d in a.drop_line]
    pages = [join_lines(p.extract_text() or "", drop) for p in PdfReader(a.pdf).pages]
    front = {
        "source_id": f"book-{a.slug}",
        "publisher": a.publisher,
        "title": a.title,
        "url": a.url,
        "kind": "book",
        "published": a.published,
        "method": "pdf",
        "speakers": a.author,
        "speaker_method": "single",
        "authors": a.author,
        "page_numbering": a.page_numbering or "pdf (p. N = PDF page N of the ebook; no printed page numbers)",
    }
    for kv in a.extra:
        k, v = kv.split("=", 1)
        front[k] = v
    if a.isbn:
        front["isbn"] = a.isbn
    path = lr.pub_dir(a.publisher) / "raw" / "book" / f"{a.slug}.md"
    lr.write_raw(path, front, lr.render_pages(pages))
    kept = sum(1 for p in pages if p)
    print(f"{path.relative_to(lr.ROOT)}: {kept} page blocks of {len(pages)}, {sum(len(p.split()) for p in pages)} words")


if __name__ == "__main__":
    main()

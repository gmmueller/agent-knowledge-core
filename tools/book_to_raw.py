"""Turn a user-supplied ebook PDF (text layer) into library/<publisher>/raw/book/<slug>.md, one block per page.

Usage:
  python -I tools/book_to_raw.py <publisher> <pdf> --workspace <workspace> --slug example-book \
      --title "Example Book" --author "Example Author" --published 2026-01-01 [--url URL] [--isbn ISBN] [--drop-line REGEX]

--drop-line drops whole lines matching REGEX (repeatable), e.g. a watermark: --drop-line "ExampleWatermark".
--page-numbering TEXT replaces the default page_numbering note; --extra key=value (repeatable) adds frontmatter fields
(venue, version, licence...). Typographic ligatures (U+FB00-FB06, e.g. "fi") are expanded to plain letters.

Line wraps are joined; a line ending in "-" joins the next line without a space (the hyphen is kept).
p. N = PDF page N. Check the first pages first (docs/build-pipeline.md: user-supplied PDFs). Refuses to overwrite.
"""
import argparse
import datetime as dt
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


def page_selection(value: str | None, count: int) -> set[int]:
    """One-based inclusive ranges; retain PDF order and original page labels."""
    if value is None:
        return set(range(1, count + 1))
    selected = set()
    for part in value.split(","):
        match = re.fullmatch(r"\s*(\d+)(?:\s*-\s*(\d+))?\s*", part)
        if not match:
            raise ValueError("--pages requires comma-separated page numbers or ranges (e.g. 1-12,40-55)")
        start, end = int(match[1]), int(match[2] or match[1])
        if not 1 <= start <= end <= count:
            raise ValueError(f"--pages range {part!r} must be within 1-{count} and ascending")
        selected.update(range(start, end + 1))
    return selected


def main() -> None:
    ap = argparse.ArgumentParser()
    brainlib.add_workspace_arg(ap)
    ap.add_argument("publisher")
    ap.add_argument("pdf", type=pathlib.Path)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--author", required=True, action="append")
    ap.add_argument("--published", required=True, type=lr.publication_date, metavar="DATE", help="YYYY, YYYY-MM or YYYY-MM-DD")
    ap.add_argument("--pages", help="PDF pages to capture, inclusive (e.g. 1-12,40-55); original page numbers are preserved")
    ap.add_argument("--url", default=None)
    ap.add_argument("--isbn", default=None)
    ap.add_argument("--page-numbering", default=None)
    ap.add_argument("--extra", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--drop-line", action="append", default=[], help="regex; whole lines matching it are dropped (watermarks)")
    a = ap.parse_args()
    lr.init(a.workspace)

    drop = [re.compile(d) for d in a.drop_line]
    reader = PdfReader(a.pdf)
    try:
        selected = page_selection(a.pages, len(reader.pages))
    except ValueError as e:
        ap.error(str(e))
    pages = [join_lines(p.extract_text() or "", drop) if i in selected else "" for i, p in enumerate(reader.pages, 1)]
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
    if len(a.published) < 10:
        front["publication_precision"] = "year" if len(a.published) == 4 else "month"
    if a.pages:
        front["selected_pdf_pages"] = a.pages
    if a.isbn:
        front["isbn"] = a.isbn
    path = lr.pub_dir(a.publisher) / "raw" / "book" / f"{a.slug}.md"
    lr.write_raw(path, front, lr.render_pages(pages))
    kept = sum(1 for p in pages if p)
    lr.merge_catalogue(a.publisher, [dict(id=front["source_id"], kind="book", title=a.title,
                                        published=a.published, url=a.url)])
    message = f"fetched: {path.relative_to(lr.ROOT)}; {kept} page blocks of {len(pages)}; {sum(len(p.split()) for p in pages)} words; speakers={a.author}"
    with (lr.pub_dir(a.publisher) / "crawl-log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {dt.datetime.now().isoformat(timespec='seconds')} {message}\n")
    print(message)


if __name__ == "__main__":
    main()

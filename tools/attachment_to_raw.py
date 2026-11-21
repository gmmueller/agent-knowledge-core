"""Convert a downloaded PDF into raw/_attachments/ without overwriting raw files."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from source_helpers import configure

import argparse
import datetime as dt
import json
import pathlib
import re

import yaml
from pypdf import PdfReader

TITLE_PREFIX = r"^(DOWNLOAD|AUDIO( FILE)?):\s*"


def references(filename: str, brain: pathlib.Path) -> tuple[list[str], str, str]:
    """Lesson ids that link this file, plus the first URL and link title seen."""
    o = yaml.safe_load((brain / "outline.yaml").read_text(encoding="utf-8"))
    ids, url, title = [], None, None

    def walk(cats):
        nonlocal url, title
        for c in cats or []:
            for l in c.get("lessons") or []:
                for a in l.get("attachments") or []:
                    slug = a["url"].rstrip("/").rsplit("/", 1)[-1]
                    if re.sub(r"-(\w+)$", r".\1", slug) == filename:
                        ids.append(l["id"])
                        url, title = url or a["url"], title or a["title"]
            walk(c.get("categories"))

    for p in o["products"]:
        walk(p["categories"])
    return ids, url, title


def write_pdf_raw(src: pathlib.Path, ids: list[str], url: str, title: str, *, brain: pathlib.Path) -> pathlib.Path:
    """Write raw/_attachments/<stem>.md for a PDF; refuses to overwrite (raw/ is immutable)."""
    out = brain / "raw" / "_attachments" / f"{src.stem}.md"
    if out.exists():
        raise FileExistsError(f"refusing to overwrite existing raw file: {out}")
    pages = [(pg.extract_text() or "").strip() for pg in PdfReader(src).pages]
    front = [
        "---",
        f"source_id: att-{src.stem.replace('_', '-')}",
        f"title: {json.dumps(re.sub(TITLE_PREFIX, '', title or src.stem, flags=re.I), ensure_ascii=False)}",
        f"file: {src.name}",
        f"url: {url}",
        f"referenced_by: [{', '.join(ids)}]",
        f"pages: {len(pages)}",
        f"captured: {dt.date.today().isoformat()}",
        "method: pdf-text",
        "---",
        "",
    ]
    body = [f"**[p. {i}]**\n\n{t if t else '_(no extractable text)_'}\n" for i, t in enumerate(pages, 1)]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(front) + "\n".join(body), encoding="utf-8", newline="\n")
    print(f"wrote {out.relative_to(brain)}  ({len(pages)} pages, {sum(map(len, pages)):,} chars, {len(ids)} lessons)")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("file")
    args = ap.parse_args()
    brain, _ = configure(args)
    src = pathlib.Path(args.file).resolve()
    ids, url, title = references(src.name, brain)
    try:
        write_pdf_raw(src, ids, url, title, brain=brain)
    except FileExistsError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()

"""Shared helpers for the library (docs/library.md): paths, slugs, catalogue.tsv, and writing raw files.

Import from other tools (run them with -I, so add the tools dir to sys.path first):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import library_raw as lr
    lr.init(workspace)  # explicit private workspace; never the framework checkout
"""
import datetime as dt
import hashlib
import json
import pathlib
import re
import unicodedata

import argparse
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib
import raw_guard

ROOT: pathlib.Path | None = None
LIBRARY: pathlib.Path | None = None


def init(workspace: str | pathlib.Path) -> None:
    """Bind path helpers to an explicit workspace; call before filesystem operations."""
    global ROOT, LIBRARY
    ROOT = brainlib.workspace_dir(workspace)
    LIBRARY = brainlib.library_dir(ROOT)


CATALOGUE_COLUMNS = ["id", "kind", "title", "published", "duration_s", "views", "url", "source", "description"]
PARA_MIN_S = 30  # new transcript block after ~30 s at a sentence end
PARA_MAX_S = 45  # ...or forced at 45 s
SENTENCE_END = re.compile(r"[.!?][\"')\]]*$")


def pub_dir(publisher: str) -> pathlib.Path:
    if LIBRARY is None:
        raise RuntimeError("call library_raw.init(workspace) before using library paths")
    return LIBRARY / publisher


def audio_path(publisher: str, video_id: str) -> pathlib.Path:
    """Where any tool downloads an item's audio (gitignored). Reuse it if present."""
    return pub_dir(publisher) / "media" / "audio" / f"{video_id}.m4a"


def video_path(publisher: str, video_id: str) -> pathlib.Path:
    return pub_dir(publisher) / "media" / "video" / f"{video_id}.mp4"


def staging_path(publisher: str, item_id: str, suffix: str) -> pathlib.Path:
    """library/<publisher>/staging/<item-id>.<suffix> (suffix: lines.json | diar.json | names.yaml)."""
    return pub_dir(publisher) / "staging" / f"{item_id}.{suffix}"


def slugify(text: str, max_len: int = 60) -> str:
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:max_len].rstrip("-") or "untitled"


def ts(seconds: float) -> str:
    s = int(seconds)
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def yaml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)  # JSON strings are valid YAML scalars


def clean_field(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def publication_date(value: str) -> str:
    """Validate an ISO publication date without adding unknown month/day precision."""
    value = str(value)
    if not re.fullmatch(r"\d{4}(?:-\d{2}(?:-\d{2})?)?", value):
        raise ValueError("publication date must be YYYY, YYYY-MM or YYYY-MM-DD")
    dt.date.fromisoformat(value + {4: "-01-01", 7: "-01", 10: ""}[len(value)])
    return value


# --- catalogue.tsv ---------------------------------------------------------------------------------

def read_catalogue(publisher: str) -> dict[str, dict]:
    path = pub_dir(publisher) / "catalogue.tsv"
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return {}
    header = lines[0].split("\t")
    return {r["id"]: r for r in (dict(zip(header, ln.split("\t"))) for ln in lines[1:] if ln.strip())}


def write_catalogue(publisher: str, rows: dict[str, dict]) -> pathlib.Path:
    """Write all rows, newest first (unknown dates last)."""
    path = pub_dir(publisher) / "catalogue.tsv"
    with brainlib.file_lock(path):
        write_catalogue_locked(path, rows)
    return path


def write_catalogue_locked(path, rows):
    ordered = sorted(rows.values(), key=lambda r: (r.get("published") or "0000-00-00", r["id"]), reverse=True)
    # plain TSV: clean_field already removed tabs and newlines, so no quoting or escaping is needed
    out = ["\t".join(CATALOGUE_COLUMNS)]
    out += ["\t".join(clean_field(r.get(c, "")) for c in CATALOGUE_COLUMNS) for r in ordered]
    brainlib.atomic_write(path, "\n".join(out) + "\n")


def merge_catalogue(publisher: str, new_rows: list[dict], *, match_url=False) -> tuple[int, int]:
    """Merge metadata and return (added, updated). With match_url, fill in each row's stable ID."""
    path = pub_dir(publisher) / "catalogue.tsv"
    with brainlib.file_lock(path):
        rows = read_catalogue(publisher)
        ids = {(item.split("-", 1)[0], row.get("url")): item for item, row in rows.items()} if match_url else {}
        added = updated = 0
        for incoming in new_rows:
            row = {c: clean_field(incoming.get(c, "")) for c in CATALOGUE_COLUMNS}
            row["description"] = row["description"][:500]
            item = row["id"]
            if match_url:
                url = row["url"]
                key = (item.split("-", 1)[0], url)
                if key in ids:
                    item = ids[key]
                elif item in rows and rows[item].get("url") != url:
                    base = item[:55] + "-" + hashlib.sha256(url.encode()).hexdigest()[:12]
                    item, suffix = base, 2
                    while item in rows:
                        item = f"{base}-{suffix}"
                        suffix += 1
                ids[key] = row["id"] = incoming["id"] = item
            old = rows.get(item)
            if old is None:
                added += 1
                rows[item] = row
            else:
                merged = {c: (row[c] or old.get(c, "")) for c in CATALOGUE_COLUMNS}
                if merged != old:
                    updated += 1
                rows[item] = merged
        write_catalogue_locked(path, rows)
    return added, updated


# --- raw files -------------------------------------------------------------------------------------

def raw_path(publisher: str, sub: str, published: str, slug_source: str, item_id: str = "") -> pathlib.Path:
    """library/<publisher>/raw/<sub>/<YYYYMMDD>-[<videoid>-]<slug>.md (sub: yt | pod | web | book)."""
    date = publication_date(published).replace("-", "").ljust(8, "0") if published else "00000000"
    if sub == "book":
        return pub_dir(publisher) / "raw" / "book" / f"{slugify(slug_source)}.md"
    vid = f"{item_id.split('-', 1)[1]}-" if sub == "yt" and item_id.startswith("yt-") else ""
    return pub_dir(publisher) / "raw" / sub / f"{date}-{vid}{slugify(slug_source)}.md"


def transcript_blocks(lines: list[dict]) -> list[tuple[float, str | None, str]]:
    """Caption/whisper lines {start, end, text, speaker?} -> [(start, speaker, text)].

    New block at every speaker change, else after PARA_MIN_S at a sentence end, forced at PARA_MAX_S.
    """
    blocks, start, spk, buf = [], None, None, []
    for ln in lines:
        text = clean_field(ln["text"] if isinstance(ln["text"], str) else " ".join(ln["text"]))
        if not text:
            continue
        s = ln.get("speaker")
        if buf and s != spk:
            blocks.append((start, spk, " ".join(buf)))
            start, buf = None, []
        if start is None:
            start, spk = ln["start"], s
        buf.append(text)
        age = ln.get("end", ln["start"]) - start
        if (age >= PARA_MIN_S and SENTENCE_END.search(text)) or age >= PARA_MAX_S:
            blocks.append((start, spk, " ".join(buf)))
            start, buf = None, []
    if buf:
        blocks.append((start, spk, " ".join(buf)))
    return blocks


def render_front(front: dict) -> str:
    out = ["---"]
    for k, v in front.items():
        if v is None:
            out.append(f"{k}: null")
        elif isinstance(v, list):
            out.append(f"{k}: [{', '.join(yaml_str(x) for x in v)}]")
        elif isinstance(v, (int, float)):
            out.append(f"{k}: {v}")
        else:
            v = str(v)
            plain = re.fullmatch(r"[A-Za-z0-9][\w./:@+-]*", v) and not re.fullmatch(r"(?i)true|false|null|yes|no|on|off", v)
            out.append(f"{k}: {v if plain else yaml_str(v)}")
    out.append("---")
    return "\n".join(out) + "\n\n"


def render_transcript(blocks: list[tuple[float, str | None, str]]) -> str:
    return "\n".join(f"**[{ts(t)}]** {f'{spk}: ' if spk else ''}{text}\n" for t, spk, text in blocks)


def render_paragraphs(paras: list[str]) -> str:
    """Web/doc text -> '**[¶n]** text' blocks (headings passed in as '## ...' stay their own block)."""
    return "\n".join(f"**[¶{i}]** {clean_field(p)}\n" for i, p in enumerate((p for p in paras if clean_field(p)), 1))


def render_pages(pages: list[str]) -> str:
    """Book/PDF pages (index 0 = page 1) -> '**[p. n]**' blocks."""
    return "\n".join(f"**[p. {i}]**\n{text.strip()}\n" for i, text in enumerate(pages, 1) if text.strip())


def write_raw(path: pathlib.Path, front: dict, body: str) -> pathlib.Path:
    """Write a raw file once. Raw is immutable: refuses to overwrite."""
    with brainlib.file_lock(path):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite raw file: {path.relative_to(ROOT) if ROOT is not None and path.is_relative_to(ROOT) else path}")
        front = {**front}
        front.setdefault("captured", dt.date.today().isoformat())
        brainlib.atomic_write(path, render_front(front) + body)
        raw_guard.record_capture(path)
    return path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    brainlib.add_workspace_arg(parser)
    args = parser.parse_args()
    init(args.workspace)
    print(LIBRARY)

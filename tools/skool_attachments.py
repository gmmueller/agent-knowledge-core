"""Download Skool lesson attachments and extract their text into raw/ (incremental, read-only).

Usage: python -I tools/skool_attachments.py --brain <brain> [--port <port>]
         [--only <source_id> ...] [--limit N] [--dry-run]

Run after skool_classroom_crawl.py: file ids come from its module cache (.secrets/scratch/<short>/modules).
Per file: one throttled Skool request (POST api2 /files/<file_id>/download-url?expire=N, from Skool's app JS
`getResourceUrl`) for a signed URL, then a plain HTTPS download into <brain>/media/attachments/<file_id>/
(untrusted data, one directory per file; nothing is ever opened with anything but a text extractor).
Text goes to raw/classroom/<course dir>/files/<NNN>-<file slug>.md:
  pdf (PyMuPDF), docx/pptx (XML text), md/txt/csv/json (as is; n8n workflows get a node summary first),
  zip (member listing plus the text of text-like members, read in memory, never extracted to disk),
  images/video (recorded, no text).
State: <brain>/state/attachments.json maps file_id -> {raw_path, file, bytes, sha1, captured}. Files already in
state are skipped; a file id that reappears in another lesson is not downloaded twice.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
import raw_guard
from skool_session import configure, scratch_dir

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import pathlib
import re
import urllib.request
import zipfile

import yaml
from playwright.sync_api import sync_playwright

from skool_classroom_crawl import slug
from skool_session import BudgetExhausted, NotLoggedIn, RateLimited, api_get
from wistia_to_raw import yaml_str

sys.stdout.reconfigure(encoding="utf-8")
TEXT_EXT = {"md", "txt", "csv", "json", "yaml", "yml", "html", "htm", "xml", "py", "js", "ts", "sh", "ps1", "sql", "toml", "ini"}
MAX_MEMBER = 300_000      # bytes of text per zip member / per file
MAX_ZIP_TEXT = 1_500_000  # total text bytes taken from one zip


def xml_text(blob: bytes) -> str:
    t = blob.decode("utf-8", "replace")
    t = re.sub(r"</w:p>|</a:p>", "\n", t)
    return re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", "", t)).strip()


def office_text(data: bytes, ext: str) -> str:
    z = zipfile.ZipFile(io.BytesIO(data))
    if ext == "docx":
        return xml_text(z.read("word/document.xml"))
    slides = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                    key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
    return "\n\n".join(f"### Slide {i}\n\n{xml_text(z.read(n))}" for i, n in enumerate(slides, 1))


def pdf_text(data: bytes) -> str:
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    return "\n\n".join(f"### Page {i}\n\n{p.get_text().strip()}" for i, p in enumerate(doc, 1) if p.get_text().strip())


def n8n_summary(obj) -> str:
    nodes = obj.get("nodes") if isinstance(obj, dict) else None
    if not isinstance(nodes, list) or not all(isinstance(n, dict) for n in nodes):
        return ""
    out = [f"n8n workflow: {obj.get('name') or '(unnamed)'}, {len(nodes)} nodes", ""]
    notes = []
    for n in nodes:
        typ = str(n.get("type", "")).rsplit(".", 1)[-1]
        if typ == "stickyNote":
            notes.append(str((n.get("parameters") or {}).get("content", "")).strip())
        else:
            out.append(f"- {n.get('name')} ({typ})")
    if notes:
        out += ["", "Sticky notes:", ""] + [f"> {x}".replace("\n", "\n> ") + "\n" for x in notes if x]
    return "\n".join(out)


def text_of(name: str, data: bytes, depth=0) -> tuple[str, str]:
    """(markdown body, extraction kind) for one file's bytes."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext == "pdf":
        return pdf_text(data), "pdf"
    if ext in ("docx", "pptx"):
        return office_text(data, ext), ext
    if ext in TEXT_EXT:
        t = data[:MAX_MEMBER].decode("utf-8", "replace")
        more = "\n\n(truncated)" if len(data) > MAX_MEMBER else ""
        if ext == "json":
            try:
                summary = n8n_summary(json.loads(data))
            except ValueError:
                summary = ""
            if summary:
                return f"{summary}\n\n```json\n{t}\n```{more}", "n8n-json"
        fence = "```" + ("json" if ext == "json" else "")
        return (f"{fence}\n{t}\n```{more}" if ext != "md" else t + more), "text"
    if ext == "zip" and depth == 0:
        z = zipfile.ZipFile(io.BytesIO(data))
        infos = [i for i in z.infolist() if not i.is_dir() and "__MACOSX" not in i.filename]
        out = ["Contents:", ""] + [f"- {i.filename} ({i.file_size:,} bytes)" for i in infos] + [""]
        taken = 0
        for i in infos:
            mext = i.filename.rsplit(".", 1)[-1].lower() if "." in i.filename else ""
            if mext not in TEXT_EXT | {"pdf", "docx", "pptx"} or i.file_size > 20_000_000 or taken > MAX_ZIP_TEXT:
                continue
            body, _ = text_of(i.filename, z.read(i), depth + 1)
            if body.strip():
                taken += len(body)
                out += [f"### {i.filename}", "", body, ""]
        return "\n".join(out), "zip"
    return "", "binary"


def main():
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    brain, config = configure(args)
    ROOT = brainlib.workspace(brain)
    outline = yaml.safe_load((brain / "outline.yaml").read_text(encoding="utf-8"))
    cache_dir = scratch_dir(brain, "modules")
    crawled = json.loads((brain / "state" / "classroom_crawled.json").read_text(encoding="utf-8"))
    state_p = brain / "state" / "attachments.json"
    state = json.loads(state_p.read_text(encoding="utf-8")) if state_p.exists() else {}
    today = dt.date.today().isoformat()

    todo, seen, missing = [], set(state), 0
    for c in outline["courses"]:
        if not c.get("access"):
            continue
        for sec in c.get("sections") or []:
            for les in sec.get("lessons") or []:
                if les.get("duplicate_of") or not any(not r.get("url") for r in les.get("resources") or []):
                    continue
                if args.only and les["source_id"] not in args.only:
                    continue
                cp = cache_dir / f"{les['id']}.json"
                if not cp.exists():
                    missing += 1
                    continue
                res = json.loads(json.loads(cp.read_text(encoding="utf-8"))["module"]["metadata"].get("resources") or "[]")
                for r in res:
                    fid = r.get("file_id")
                    if fid and fid not in seen:
                        seen.add(fid)
                        todo.append((c, les, r))
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} files to fetch ({missing} lessons with files lack a module cache: crawl them first)", flush=True)
    if args.dry_run:
        for c, les, r in todo:
            try:
                print(les["source_id"], r["file_id"][:8], r.get("file_name"))
            except (RateLimited, BudgetExhausted, NotLoggedIn):
                raise
            except Exception as e:  # one bad item must not stop a long unattended run; it is retried next run
                errors += 1
                print(f"{r['file_id']}: ERROR {type(e).__name__}: {str(e)[:300]}", flush=True)
        return

    def save_state():
        state_p.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")

    done = errors = 0
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{args.port}")
        try:
            for c, les, r in todo:
                fid, fname = r["file_id"], r.get("file_name") or r["file_id"]
                d = api_get(browser, f"https://api2.skool.com/files/{fid}/download-url?expire=600", method="POST", raw=True, brain=brain).strip()
                if d.startswith("{"):
                    j = json.loads(d)
                    d = j.get("url") or j.get("download_url") or j.get("signed_url") or ""
                url = d.strip('"')
                if not url.startswith("https://"):
                    raise RuntimeError(f"no URL in download-url response: {str(d)[:200]}")
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=120) as resp:
                    data = resp.read()
                fdir = brain / "media" / "attachments" / fid
                fdir.mkdir(parents=True, exist_ok=True)
                safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", fname).strip(" .") or fid
                (fdir / safe).write_bytes(data)
                try:
                    body, kind = text_of(fname, data)
                except Exception as e:  # corrupt or unusual file: keep the download, note the failure
                    body, kind = f"(text extraction failed: {type(e).__name__}: {e})", "failed"
                sid = les["source_id"]
                n = sid.rsplit("-", 1)[1]
                out = brain / "raw" / "classroom" / f"{c['code']}-{slug(c['title'], 40)}" / "files" / f"{n}-{slug(fname)}.md"
                if out.exists():
                    out = out.with_name(out.stem + f"-{fid[:8]}.md")
                sha1 = hashlib.sha1(data).hexdigest()
                front = ["---", f"source_id: {sid}-f-{fid[:8]}", f"title: {yaml_str(r.get('title') or fname)}",
                         f"lesson: {crawled.get(sid, {}).get('raw_path') or sid}", f"file_name: {yaml_str(fname)}",
                         f"file_id: {fid}", f"content_type: {r.get('file_content_type') or 'unknown'}",
                         f"bytes: {len(data)}", f"sha1: {sha1}", f"captured: {today}", "method: skool-file",
                         f"extracted: {kind}", "---", ""]
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text("\n".join(front) + (body.rstrip() or "(no text: binary file)") + "\n", encoding="utf-8", newline="\n")
                raw_guard.record_capture(out)
                rel = str(out.relative_to(ROOT)).replace("\\", "/")
                state[fid] = {"raw_path": rel, "file": fname, "lesson": sid, "bytes": len(data), "sha1": sha1,
                              "extracted": kind, "captured": today}
                done += 1
                print(f"{sid}: {fname} ({len(data):,} bytes, {kind}) -> {rel}", flush=True)
                if done % 10 == 0:
                    save_state()
        except (RateLimited, BudgetExhausted) as e:
            print(f"stopped: {type(e).__name__}: {e}", flush=True)
        finally:
            save_state()
    print(f"done: {done} written, {errors} errors", flush=True)


if __name__ == "__main__":
    main()

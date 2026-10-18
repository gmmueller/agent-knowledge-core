"""Split a Skool brain's raw/ into ingest batches -> <brain>/ingest/batches.yaml (offline).

Usage: tools/.venv/Scripts/python -I tools/skool_ingest_batches.py --brain <brain> [--lesson-words 60000]
         [--thread-words 70000] [--max-pages 50] [--only-new]

Item kinds (each item: id, raw, kind, words, published; lessons may carry `files:` with prose attachments):
  lesson  one source page per lesson, id = source_id (<prefix>-<course code>-<NNN>); batches follow course order.
          Prose attachments (pdf, pptx, docx, md/txt) ride with their lesson; zips and n8n JSON are skipped
          (their file pages stay in raw/ for search).
  thread  expert threads (voice: expert): one source page per thread, id = <prefix>-post-<post id8>; batches by month.
  qa      member threads with staff replies (voice: replied): one digest page per month, id = <prefix>-qa-<YYYY-MM>;
          every thread of that month is an item with the digest's id. A month never spans two batches.
--only-new keeps only items whose raw file is neither in their source page's `sources` nor in an earlier
ingest/batches*.yaml (incremental ingest after a refresh): new lessons and threads, edited lessons and re-captured threads (a new dated raw file with `supersedes:`),
and new member threads in a month whose qa digest already exists. Items for an existing page get `update: true`.
Batch names: l01.. (lessons), t01.. (threads), q01.. (qa), with --prefix (e.g. u1017-) for incremental runs so
they don't collide with earlier staging files. --out defaults to ingest/batches.yaml.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from skool_session import configure, raw_path, source_prefix

import argparse
import json
import pathlib
import re

import yaml

sys.stdout.reconfigure(encoding="utf-8")
PROSE = {"pdf", "pptx", "docx", "text"}


def front(path: pathlib.Path) -> dict:
    t = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", t, re.S)
    return (yaml.safe_load(m.group(1)) or {}) if m else {}


def words(path: pathlib.Path) -> int:
    return len(path.read_text(encoding="utf-8").split())


def pack(items, limit, prefix, key=lambda it: it["id"], max_pages=50):
    """Greedy split in order; items sharing key() stay together."""
    groups, cur, cur_key = [], [], None
    for it in items:
        if cur and key(it) != cur_key:
            groups.append(cur)
            cur = []
        cur.append(it)
        cur_key = key(it)
    if cur:
        groups.append(cur)
    batches, b, n = {}, [], 0
    for g in groups:
        gw = sum(it["words"] for it in g)
        if b and (n + gw > limit or len({it["id"] for it in b}) >= max_pages):
            batches[f"{prefix}{len(batches) + 1:02d}"] = b
            b, n = [], 0
        b += g
        n += gw
    if b:
        batches[f"{prefix}{len(batches) + 1:02d}"] = b
    return batches


def main():
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("--lesson-words", type=int, default=60000)
    ap.add_argument("--thread-words", type=int, default=70000)
    ap.add_argument("--max-pages", type=int, default=50, help="source pages per batch")
    ap.add_argument("--only-new", action="store_true")
    ap.add_argument("--prefix", default="", help="batch name prefix, e.g. u1017-")
    ap.add_argument("--out", default=None, help="default <brain>/ingest/batches.yaml")
    args = ap.parse_args()
    brain, config = configure(args)
    prefix = source_prefix(brain)
    st = brain / "state"
    rel = lambda p: p.relative_to(brain).as_posix()
    out_p = pathlib.Path(args.out) if args.out else brain / "ingest" / "batches.yaml"
    cited = {}  # source page id -> raw paths in its frontmatter `sources`
    batched = set()  # raw paths in earlier batch files (qa digests don't cite brief-reply threads)
    if args.only_new:
        for sp in (brain / "wiki" / "sources").glob("*.md"):
            cited[sp.stem] = {str(x) for x in front(sp).get("sources") or []}
        for bp in (brain / "ingest").glob("batches*.yaml"):
            if bp.resolve() != out_p.resolve():
                for b in (yaml.safe_load(bp.read_text(encoding="utf-8")) or {}).values():
                    batched.update(it["raw"] for it in b["items"])

    def keep(it):
        """--only-new: drop items already cited by their page; flag items for an existing page."""
        if not args.only_new:
            return True
        if it["raw"] in batched:  # in an earlier batch file, ingested or in flight
            return False
        if it["id"] not in cited:
            return True
        if it["raw"] in cited[it["id"]]:
            return False
        it["update"] = True
        return True

    outline = yaml.safe_load((brain / "outline.yaml").read_text(encoding="utf-8"))
    crawled = json.loads((st / "classroom_crawled.json").read_text(encoding="utf-8"))
    att = json.loads((st / "attachments.json").read_text(encoding="utf-8")) if (st / "attachments.json").exists() else {}
    files_by_lesson = {}
    for rec in att.values():
        if rec.get("extracted") in PROSE:
            files_by_lesson.setdefault(rec["lesson"], []).append(raw_path(brain, rec["raw_path"]).relative_to(brain).as_posix())
    lessons = []
    for c in outline["courses"]:
        if not c.get("access"):
            continue
        for s in c.get("sections") or []:
            for les in s.get("lessons") or []:
                rec = crawled.get(les["source_id"])
                if les.get("duplicate_of") or not rec or not rec.get("raw_path"):
                    continue
                p = raw_path(brain, rec["raw_path"])
                it = {"id": les["source_id"], "raw": rel(p), "kind": "lesson", "words": words(p),
                      "published": str(front(p).get("published") or str(front(p).get("lesson_updated") or "")[:10])}
                fl = sorted(files_by_lesson.get(les["source_id"], []))
                if fl:
                    it["files"] = fl
                    it["words"] += sum(words(brain / f) for f in fl)
                if keep(it):
                    lessons.append(it)

    threads, qa = [], []
    for pid, rec in json.loads((st / "threads_crawled.json").read_text(encoding="utf-8")).items():
        p = raw_path(brain, rec["raw_path"])
        fm = front(p)
        created = str(fm.get("created") or "")[:10]
        it = {"raw": rel(p), "words": words(p), "published": created}
        if rec.get("voice") == "expert":
            it.update(id=f"{prefix}-post-{pid[:8]}", kind="thread")
            if keep(it):
                threads.append(it)
        else:
            it.update(id=f"{prefix}-qa-{created[:7]}", kind="qa")
            if keep(it):
                qa.append(it)
    threads.sort(key=lambda it: it["published"])
    qa.sort(key=lambda it: it["published"])

    batches = {}
    batches.update(pack(lessons, args.lesson_words, args.prefix + "l", key=lambda it: it["id"], max_pages=args.max_pages))
    batches.update(pack(threads, args.thread_words, args.prefix + "t", key=lambda it: it["id"], max_pages=args.max_pages))
    batches.update(pack(qa, args.thread_words, args.prefix + "q", key=lambda it: it["id"], max_pages=args.max_pages))
    out = {name: {"words": sum(it["words"] for it in items), "items": items} for name, items in batches.items()}
    (brain / "ingest").mkdir(exist_ok=True)
    out_p.write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True, width=200), encoding="utf-8")
    for name, b in out.items():
        ids = sorted({it["id"] for it in b["items"]})
        print(f"{name}: {len(b['items']):3} items, {len(ids):3} pages, {b['words']:7} words, {ids[0]} .. {ids[-1]}")
    print(f"{len(out)} batches, {len(lessons)} lessons, {len(threads)} threads, {len(qa)} qa threads")


if __name__ == "__main__":
    main()

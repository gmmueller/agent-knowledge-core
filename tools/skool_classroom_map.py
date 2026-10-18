"""Map a Skool classroom into outline.yaml (incremental, read-only).

Usage: tools/.venv/Scripts/python -I -X utf8 tools/skool_classroom_map.py \
         --brain <brain> [--group <community>] [--port <port>] [--out <brain>/outline.yaml] \
         --cache .secrets/scratch/<cache-name>/modules [--only <course code>]

Per course: one request for the tree (redirects to the first lesson, so 2 HTTP calls; that first
lesson's full metadata comes with it). Per lesson: one request, only if the cache at
<cache>/<module id>.json is missing or holds a different `updatedAt` than the tree (skipped with
--tree-only). Sequential, paced by skool_session._throttle (~3-4.5 s per request). Never types or clicks.
Raises NotLoggedIn if logged out, RateLimited on a WAF block.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from skool_session import configure, scratch_dir, source_prefix

import argparse
import datetime
import hashlib
import json
import os
import re
import time
from collections import Counter

import yaml
from playwright.sync_api import sync_playwright

from skool_session import next_data
from skool_text import lesson_hash

sys.stdout.reconfigure(encoding="utf-8")

TIMINGS = []  # (kind, seconds)


def timed(kind, *a, **kw):
    t = time.time()
    try:
        return next_data(*a, **kw)
    finally:
        TIMINGS.append((kind, time.time() - t))


def find_node(tree, mid):
    if tree["course"]["id"] == mid:
        return tree
    for ch in tree.get("children") or []:
        r = find_node(ch, mid)
        if r:
            return r
    return None


def parse_video(meta, video_pp):
    link = (meta.get("videoLink") or "").strip()
    if link:
        m = re.search(r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:.*&)?v=|embed/|live/|shorts/|v/))([\w-]{6,})", link)
        if m:
            return f"youtube:{m.group(1)}", "youtube"
        m = re.search(r"loom\.com/(?:share|embed)/([\w]+)", link)
        if m:
            return f"loom:{m.group(1)}", "loom"
        m = re.search(r"vimeo\.com/(?:video/)?(\d+)", link)
        if m:
            return f"vimeo:{m.group(1)}", "vimeo"
        return f"other:{link}", "other"
    stream = meta.get("videoStream")
    if not stream and video_pp:
        stream = video_pp.get("id") if isinstance(video_pp, dict) else video_pp
    if stream:
        if isinstance(stream, dict):
            stream = stream.get("id") or json.dumps(stream)[:60]
        return f"skool:{stream}", "skool"
    return None, None


def desc_text(desc):
    """Return (plain text, number of links) from a Skool rich-text desc."""
    if not desc:
        return "", 0
    if not desc.startswith("[v2]"):
        return desc, len(re.findall(r"https?://", desc))
    try:
        doc = json.loads(desc[4:])
    except ValueError:
        return desc, len(re.findall(r"https?://", desc))
    parts, links = [], set()

    def walk(n):
        if isinstance(n, list):
            for x in n:
                walk(x)
            return
        if not isinstance(n, dict):
            return
        if n.get("type") == "text":
            parts.append(n.get("text", ""))
            for mk in n.get("marks") or []:
                if mk.get("type") == "link":
                    links.add((mk.get("attrs") or {}).get("href"))
        elif n.get("type") in ("paragraph", "heading", "listItem", "blockquote", "codeBlock", "hardBreak"):
            parts.append("\n")
        for k in ("content", "children"):
            if k in n:
                walk(n[k])

    walk(doc)
    text = "".join(parts)
    # raw URLs typed as plain text without a link mark
    links |= set(re.findall(r"https?://[^\s\"')]+", text))
    return text.strip(), len(links)


def parse_resources(raw):
    if not raw:
        return []
    try:
        lst = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []
    out = []
    for r in lst or []:
        e = {"title": r.get("title")}
        if r.get("file_name"):
            e["file_name"] = r["file_name"]
            e["type"] = r.get("file_content_type")
        url = r.get("link") or r.get("url")
        if url:
            e["url"] = url
        out.append(e)
    return out


def load_cache(cache, mid):
    p = os.path.join(cache, f"{mid}.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return None


def save_cache(cache, mid, module, video_pp, course_code):
    rec = {
        "updatedAt": module["updatedAt"],
        "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "course_code": course_code,
        "module": {k: v for k, v in module.items()},
        "video": video_pp,
    }
    with open(os.path.join(cache, f"{mid}.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)
    return rec


def collect_modules(tree):
    """Flatten a course tree into [(section_id, section_title, module_node)] in order."""
    out = []

    def walk(children, sid, stitle):
        for ch in children or []:
            c = ch["course"]
            if c["unitType"] == "set":
                title = c["metadata"].get("title")
                walk(ch.get("children"), c["id"], f"{stitle} / {title}" if stitle else title)
            else:
                out.append((sid, stitle, c))
                if ch.get("children"):  # modules nested under modules (not seen so far)
                    walk(ch["children"], sid, stitle)

    walk(tree.get("children"), None, None)
    return out


def load_ids(path, outline_path):
    """Stable source ids: {"<course code>/<module id>": "<prefix>-<code>-NNN"}.

    Ids used to be positional, so a lesson added at the top of a course renumbered every lesson below
    it (and its raw file, state entry and wiki page). The registry keeps an id once assigned, also for
    lessons later removed. First run seeds it from the existing outline.
    """
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    ids = {}
    if os.path.exists(outline_path):
        with open(outline_path, encoding="utf-8") as f:
            old = yaml.safe_load(f) or {}
        for c in old.get("courses") or []:
            for s in c.get("sections") or []:
                for l in s.get("lessons") or []:
                    ids[f"{c['code']}/{l['id']}"] = l["source_id"]
    return ids


def assign_id(ids, code, mid, prefix):
    key = f"{code}/{mid}"
    if key not in ids:
        used = [int(v.rsplit("-", 1)[1]) for k, v in ids.items() if k.startswith(code + "/")]
        ids[key] = f"{prefix}-{code}-{max(used, default=0) + 1:03d}"
    return ids[key]


def blank_totals():
    return {"sections": 0, "lessons": 0, "videos": 0, "video_hosts": {}, "duration_s": 0, "with_resources": 0, "text_chars": 0}


def main():
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("--group", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--cache", default=None)
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--tree-only", action="store_true",
                    help="no per-lesson fetches: use course-tree metadata (video, length, resources) and cached "
                         "lesson bodies; lessons without a cached body get text_chars: null")
    args = ap.parse_args()
    brain, config = configure(args)
    prefix = source_prefix(brain)
    args.out = str(Path(args.out).resolve()) if args.out else str(brain / "outline.yaml")
    args.cache = args.cache or str(scratch_dir(brain, "modules"))
    args.only = args.only or config.get("courses", [])
    os.makedirs(args.cache, exist_ok=True)
    ids_path = os.path.join(os.path.dirname(args.out), "state", "lesson_ids.json")
    ids = load_ids(ids_path, args.out)
    group = args.group
    site = config["site"]
    stats = Counter()

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{args.port}")
        cr = timed("classroom", browser, f"{group}/classroom", brain=brain)
        pp = cr["pageProps"]
        group_id = (pp.get("currentGroup") or {}).get("id")
        all_courses = pp["allCourses"]
        courses = []
        for ci, c in enumerate(all_courses):
            code, meta = c["name"], c["metadata"]
            if args.only and code not in args.only:
                continue
            access = bool(meta.get("hasAccess"))
            entry = {
                "code": code,
                "id": c["id"],
                "title": meta.get("title"),
                "url": f"{site}/classroom/{code}",
                "access": access,
                "updated": c.get("updatedAt"),
                "declared_modules": meta.get("numModules"),
                "privacy": meta.get("privacy"),
            }
            if not access:
                entry["totals"] = blank_totals()
                entry["sections"] = []
                courses.append(entry)
                print(f"[{code}] {meta.get('title')}: locked, skipped", flush=True)
                continue
            first = timed("tree", browser, f"{group}/classroom/{code}", brain=brain)
            ppc = first["pageProps"]
            tree = ppc["course"]
            first_id = ppc.get("selectedModule")
            node = find_node(tree, first_id) if first_id else None
            if node:  # the redirect already delivered the first lesson's full metadata
                cached = load_cache(args.cache, first_id)
                if not cached or cached["updatedAt"] != node["course"]["updatedAt"]:
                    save_cache(args.cache, first_id, node["course"], ppc.get("video"), code)
                    stats["from_tree"] += 1
            mods = collect_modules(tree)
            sections, by_sid, n = [], {}, 0
            totals = blank_totals()
            for sid, stitle, mc in mods:
                if (sid, stitle) not in by_sid:
                    sec = {"id": sid, "title": stitle, "lessons": []}
                    by_sid[(sid, stitle)] = sec
                    sections.append(sec)
                    if sid:
                        totals["sections"] += 1
                sec = by_sid[(sid, stitle)]
                mid = mc["id"]
                cached = load_cache(args.cache, mid)
                if args.tree_only and (not cached or cached["updatedAt"] != mc.get("updatedAt")):
                    cached = {"module": mc, "video": None, "updatedAt": mc.get("updatedAt"), "tree_only": True}
                    stats["tree_only"] += 1
                elif not cached or cached["updatedAt"] != mc.get("updatedAt"):
                    d = timed("module", browser, f"{group}/classroom/{code}", {"md": mid}, brain=brain)
                    node = find_node(d["pageProps"]["course"], mid)
                    if not node:
                        raise RuntimeError(f"module {mid} not found in response for {code}")
                    cached = save_cache(args.cache, mid, node["course"], d["pageProps"].get("video"), code)
                    stats["fetched"] += 1
                    if stats["fetched"] % 25 == 0:
                        print(f"  ... {stats['fetched']} modules fetched", flush=True)
                else:
                    stats["cache_hit"] += 1
                m = cached["module"]
                meta = m["metadata"]
                n += 1
                text, nlinks = desc_text(meta.get("desc"))
                video, host = parse_video(meta, cached.get("video"))
                dur = (meta.get("videoLenMs") or 0) / 1000
                res = parse_resources(meta.get("resources"))
                lesson = {
                    "id": mid,
                    "source_id": assign_id(ids, code, mid, prefix),
                    "title": meta.get("title"),
                    "url": f"{site}/classroom/{code}?md={mid}",
                    "updated": m.get("updatedAt"),
                    "video": video,
                    "duration_s": round(dur) if video else 0,
                    "resources": res,
                    "text_chars": None if cached.get("tree_only") else len(text),
                    "links_in_text": None if cached.get("tree_only") else nlinks,
                    # null = unknown (stale cache under --tree-only): the crawler fetches and compares
                    "content_hash": None if cached.get("tree_only") else lesson_hash(meta),
                }
                if meta.get("hasAccess") in (0, None):
                    lesson["module_access"] = False
                sec["lessons"].append(lesson)
                totals["lessons"] += 1
                if video:
                    totals["videos"] += 1
                    totals["video_hosts"][host] = totals["video_hosts"].get(host, 0) + 1
                    totals["duration_s"] += lesson["duration_s"]
                if res:
                    totals["with_resources"] += 1
                totals["text_chars"] += len(text)
            entry["totals"] = totals
            entry["sections"] = sections
            courses.append(entry)
            print(f"[{code}] {entry['title']}: {totals['lessons']} lessons, {totals['videos']} videos "
                  f"(declared {entry['declared_modules']}); fetched so far {stats['fetched']}", flush=True)

    mark_duplicates(courses)
    write_outline(args, site, group_id, courses)
    os.makedirs(os.path.dirname(ids_path), exist_ok=True)
    with open(ids_path, "w", encoding="utf-8") as f:
        json.dump(ids, f, indent=1, sort_keys=True)
    t_mod = [s for k, s in TIMINGS if k == "module"]
    print("stats", dict(stats), "requests", len(TIMINGS),
          "mean module s", round(sum(t_mod) / len(t_mod), 2) if t_mod else None)
    run = {"timings": TIMINGS, "stats": dict(stats), "run_at": datetime.datetime.now().isoformat(timespec="seconds")}
    with open(scratch_dir(brain) / "classroom_map_run.json", "w", encoding="utf-8") as f:
        json.dump(run, f)


def norm_title(t):
    return re.sub(r"\W+", " ", (t or "").lower()).strip()


def mark_duplicates(courses):
    """Flag lessons repeated in another course: same video id, or (no video) same content hash.

    Canonical copy = the first one met when courses are ordered with the biggest aggregate course
    ("All Lessons...") last, so topic courses own their lessons and the aggregate points to them.
    """
    order = sorted(
        [c for c in courses if c["access"]],
        key=lambda c: (c["totals"]["lessons"] >= 100, 0),  # stable: aggregate course goes last
    )
    seen = {}
    for c in order:
        for sec in c["sections"]:
            for l in sec["lessons"]:
                key = l["video"] or f"hash:{l['content_hash']}"
                if key.startswith("hash:") and not l["text_chars"]:
                    continue  # body unknown (--tree-only) or empty: can't tell, keep as unique
                if key in seen and seen[key][0] != c["code"]:
                    l["duplicate_of"] = seen[key][1]
                else:
                    seen.setdefault(key, (c["code"], l["source_id"]))


def lesson_list_hash(courses):
    """Refresh cursor: changes when any lesson is added, removed, moved or edited (updatedAt)."""
    items = sorted(f"{c['code']}/{l['id']}@{l.get('updated')}" for c in courses for s in c["sections"] for l in s["lessons"])
    return f"lessons:{len(items)}:sha256:{hashlib.sha256(chr(10).join(items).encode()).hexdigest()[:16]}"


def write_outline(args, site, group_id, courses):
    tot = {"courses": len(courses), "accessible_courses": sum(c["access"] for c in courses), "sections": 0, "lessons": 0,
           "videos": 0, "video_hosts": {}, "duration_s": 0, "with_resources": 0, "text_chars": 0,
           "duplicate_lessons": 0, "unique_lessons": 0}
    for c in courses:
        t = c["totals"]
        c["totals"]["duplicate_lessons"] = sum(1 for s in c["sections"] for l in s["lessons"] if "duplicate_of" in l)
        for k in ("sections", "lessons", "videos", "duration_s", "with_resources", "text_chars"):
            tot[k] += t[k]
        for h, n in t["video_hosts"].items():
            tot["video_hosts"][h] = tot["video_hosts"].get(h, 0) + n
        tot["duplicate_lessons"] += t["duplicate_lessons"]
    tot["unique_lessons"] = tot["lessons"] - tot["duplicate_lessons"]
    doc = {
        "generated": datetime.date.today().isoformat(),
        "site": site,
        "group_id": group_id,
        "cursor": lesson_list_hash(courses),
        "totals": tot,
        "courses": courses,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False, width=200)
    print("wrote", args.out, tot)


if __name__ == "__main__":
    main()

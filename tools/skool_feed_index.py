"""Index a Skool community feed into posts.jsonl (metadata only, no post content). Incremental, read-only.

Usage: python -I tools/skool_feed_index.py --mode backfill|refresh|recache [--until YYYY-MM-DD]          [--group <brain>] [--port <port>] [--out <brain>/state/posts.jsonl] [--max-pages N]

backfill: pages `?s=newest` (creation order, newest first) to the end. Resumable: progress is saved
          to the cursor file every 10 pages and after a RateLimited/BudgetExhausted stop; the next
          backfill run restarts 2 pages before where it stopped (rows merge by post id).
refresh:  pages `?s=newest-cm` (ordered by last comment time; pinned posts repeat at the top) and
          stops at the first page whose unpinned posts all have activity older than the cursor's
          `activity_ns`. Catches new posts AND new comments on old threads. Rows whose comment
          count, last-comment time or content hash changed stay in `pending_changes` until captured.
recache:  pages `?s=newest` from page 1 until a page's unpinned posts were all created before --until,
          rewriting the post cache and index rows (so the thread crawler can skip per-post fetches).
          Resumable via the cursor's `recache` entry; backfill state is untouched.
Edits without new comments are only caught by a periodic full backfill (compares content_sha1).
Pacing and WAF handling come from skool_session (~3-4.5 s per request). Never types or clicks.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from skool_session import configure, scratch_dir
from source_helpers import stamp_skool

import argparse
import datetime
import hashlib
import json
import os
import re
import time

from playwright.sync_api import sync_playwright

from skool_session import BudgetExhausted, RateLimited, next_data

sys.stdout.reconfigure(encoding="utf-8")


def parse_json(s, default):
    try:
        return json.loads(s) if isinstance(s, str) and s else default
    except ValueError:
        return default


def row_from_post(post, site):
    m = post.get("metadata") or {}
    u = post.get("user") or {}
    um = u.get("metadata") or {}
    sp = parse_json(um.get("spData"), {})
    contribs = parse_json(m.get("contributors"), None)
    if contribs is None:  # truncated JSON: salvage the ids
        contribs_ids = re.findall(r'"id":"([0-9a-f]{32})"', m.get("contributors") or "")
    else:
        contribs_ids = [c.get("id") for c in contribs if isinstance(c, dict)]
    vids = [v for v in re.split(r"[,\s]+", m.get("videoIds") or "") if v]
    att = m.get("attachments")
    return {
        "id": post["id"],
        "name": post.get("name"),
        "title": m.get("title"),
        "url": f"{site}/{post.get('name')}",
        "created": post.get("createdAt"),
        "updated": post.get("updatedAt"),
        "author_id": post.get("userId"),
        "author_handle": u.get("name"),
        "author_name": " ".join(x for x in (u.get("firstName"), u.get("lastName")) if x) or None,
        "author_role": sp.get("role"),
        "label_id": post.get("labelId"),
        "comments": m.get("comments") or 0,
        "upvotes": m.get("upvotes") or 0,
        "pinned": bool(m.get("pinned")),
        "last_comment_ns": m.get("lastComment"),
        "contributor_ids": contribs_ids,
        "has_attachments": bool(att and att not in ("[]", "{}", "")),
        "video_ids": vids,
        "content_chars": len(m.get("content") or ""),
        "content_sha1": content_sha1(post),
    }


def content_sha1(post):
    """Short hash of a post's title + body, used to detect edits."""
    m = post.get("metadata") or {}
    return hashlib.sha1(((m.get("title") or "") + "\n" + (m.get("content") or "")).encode("utf-8")).hexdigest()[:16]


def post_version(row):
    return [int(row.get("comments") or 0), int(row.get("last_comment_ns") or 0), row.get("content_sha1")]


def pending_changes(cursor, index):
    if "pending_changes" in cursor:
        return cursor["pending_changes"].copy()
    return {pid: post_version(index[pid]) for pid in (cursor.get("last_run") or {}).get("changed", [])
            if pid in index}


def activity_ns(r):
    """Last activity as ns epoch: last comment, else creation time."""
    if r.get("last_comment_ns"):
        return int(r["last_comment_ns"])
    created = datetime.datetime.fromisoformat(r["created"].replace("Z", "+00:00"))
    return int(created.timestamp() * 1e9)


def load_index(path):
    idx = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    idx[r["id"]] = r
    return idx


def write_index(path, idx):
    rows = sorted(idx.values(), key=lambda r: r["created"] or "", reverse=True)
    brainlib.atomic_write(Path(path), "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def main():
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("--mode", choices=["backfill", "refresh", "recache"], required=True)
    ap.add_argument("--until", default=None, help="recache: stop after posts created before YYYY-MM-DD")
    ap.add_argument("--group", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--cursor", default=None)
    ap.add_argument("--max-pages", type=int, default=1000)
    ap.add_argument("--post-cache", default=None,
                    help="full post JSON per id (gitignored); lets the thread crawler skip the post fetch")
    args = ap.parse_args()
    brain, config = configure(args)
    args.out = str(Path(args.out).resolve()) if args.out else str(brain / "state" / "posts.jsonl")
    args.post_cache = args.post_cache or str(scratch_dir(brain, "posts"))
    os.makedirs(args.post_cache, exist_ok=True)
    cursor_path = args.cursor or os.path.join(os.path.dirname(os.path.abspath(args.out)), "feed_cursor.json")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    site = config["site"]

    idx = load_index(args.out)
    cursor_path = Path(cursor_path)
    cur = json.loads(cursor_path.read_text(encoding="utf-8")) if cursor_path.exists() else {}
    since_ns = int(cur.get("activity_ns") or 0)
    backfill = cur.get("backfill") or {"complete": False, "next_page": 1}
    if args.mode == "refresh" and not backfill["complete"]:
        sys.exit("backfill not complete; run --mode backfill first")
    page_no = max(1, backfill["next_page"] - 2) if args.mode == "backfill" and not backfill["complete"] else 1
    recache = cur.get("recache") or {}
    if args.mode == "recache":
        if not args.until:
            sys.exit("--mode recache needs --until YYYY-MM-DD")
        if recache.get("until") != args.until or recache.get("complete"):
            recache = {"until": args.until, "next_page": 1, "complete": False}
        page_no = max(1, recache["next_page"] - 1)
    sort = "newest-cm" if args.mode == "refresh" else "newest"
    print(f"{args.mode}: index {len(idx)} posts, start page {page_no}, cursor activity_ns={since_ns or None}", flush=True)

    pending = pending_changes(cur, idx)
    pages, timings, stop_reason, newest_activity = 0, [], "max-pages", since_ns
    violations, last_key, labels, total_reported = 0, None, cur.get("labels"), cur.get("total_reported")

    def save():
        # Publish the queue before index rows that would otherwise hide these changes on a retry.
        cur["pending_changes"] = pending
        if args.mode != "recache":
            cur["scan_complete"] = False
        brainlib.atomic_write(cursor_path, json.dumps(cur, indent=1, ensure_ascii=False))
        write_index(args.out, idx)
        rows = list(idx.values())
        if args.mode != "recache":
            cur["scan_complete"] = stop_reason in {"reached-cursor", "end"}
        if args.mode == "refresh" and cur["scan_complete"]:
            cur["activity_ns"] = newest_activity or None
        elif args.mode == "backfill" and stop_reason == "end":
            cur["activity_ns"] = max((activity_ns(r) for r in rows), default=None)
        cur.update({
            "newest_created": max((r["created"] for r in rows), default=None),
            "total_indexed": len(idx),
            "total_reported": total_reported,
            "labels": labels,
            "backfill": backfill,
            **({"recache": recache} if recache else {}),
            "last_run": {"mode": args.mode, "pages": pages, "stop": stop_reason, "order_violations": violations,
                         "changed": sorted(pending), "mean_page_s": round(sum(timings) / len(timings), 2) if timings else None,
                         "at": datetime.datetime.now().isoformat(timespec="seconds")},
        })
        brainlib.atomic_write(cursor_path, json.dumps(cur, indent=1, ensure_ascii=False))

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{args.port}")
        try:
            while pages < args.max_pages:
                t = time.time()
                d = next_data(browser, args.group, {"p": page_no, "s": sort}, brain=brain)
                timings.append(time.time() - t)
                pp = d["pageProps"]
                trees = pp.get("postTrees") or []
                total_reported = pp.get("total", total_reported)
                if not labels:
                    labels = [{"id": l["id"], "name": l["metadata"].get("displayName"), "posts": l["metadata"].get("posts")}
                              for l in (pp.get("currentGroup") or {}).get("labels") or []]
                if not trees:
                    stop_reason = "end"
                    if args.mode == "recache":
                        recache["complete"] = True
                    if args.mode == "backfill":
                        backfill = {"complete": True, "next_page": None, "completed_at": datetime.datetime.now().isoformat(timespec="seconds")}
                    break
                pages += 1
                unpinned_activity = []
                for tr in trees:
                    r = row_from_post(tr["post"], site)
                    pid = r["id"]
                    cache_path = Path(args.post_cache) / f"{pid}.json"
                    brainlib.atomic_write(cache_path, json.dumps(tr["post"], ensure_ascii=False))
                    old = idx.get(pid)
                    version = post_version(r)
                    if (old and post_version(old) != version) or (not old and args.mode != "backfill"):
                        pending[pid] = version
                    idx[pid] = r
                    active = activity_ns(r)
                    newest_activity = max(newest_activity, active)
                    if r["pinned"]:
                        continue
                    key = activity_ns(r) if args.mode == "refresh" else r["created"]
                    if last_key is not None and key > last_key:
                        violations += 1
                    last_key = key
                    unpinned_activity.append(active)
                if args.mode == "backfill":
                    backfill["next_page"] = page_no + 1
                    if pages % 10 == 0:
                        save()
                        print(f"page {page_no}: {len(idx)} indexed ({sum(timings)/len(timings):.1f}s/page)", flush=True)
                elif args.mode == "recache":
                    recache["next_page"] = page_no + 1
                    if pages % 10 == 0:
                        save()
                        print(f"page {page_no}: recached through {min(t['post']['createdAt'] for t in trees)[:10]}", flush=True)
                    if all(t["post"]["createdAt"][:10] < args.until for t in trees if not t["post"]["metadata"].get("pinned")):
                        recache["complete"] = True
                        stop_reason = "reached-until"
                        break
                elif unpinned_activity and max(unpinned_activity) < since_ns and not violations:
                    stop_reason = "reached-cursor"
                    break
                page_no += 1
        except (RateLimited, BudgetExhausted) as e:
            stop_reason = f"{type(e).__name__}: {e}"
            print(stop_reason, flush=True)
        finally:
            save()
    if args.mode != "recache" and stop_reason in {"end", "reached-cursor"}:
        threads = brain / "state" / "threads_crawled.json"
        tracked = json.loads(threads.read_text(encoding="utf-8")) if threads.exists() else {}
        if not pending.keys() & tracked.keys():
            stamp_skool(brain, site)
    print("done", cur["last_run"] | {"total_indexed": len(idx)})


if __name__ == "__main__":
    main()

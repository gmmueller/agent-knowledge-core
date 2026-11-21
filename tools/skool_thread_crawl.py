"""Crawl Skool community threads (post + all comments) into raw/ files (incremental, read-only).

Usage: python -I tools/skool_thread_crawl.py --brain <brain> [--port <port>]
         (--ids <post id> ... | --tier expert|replied|replied_other|changed) [--since YYYY-MM-DD | --days N]
         [--limit N] [--dry-run]

Tiers (from <brain>/state/posts.jsonl and threads_tiers.json):
  expert   posts authored by the owner or an admin (ids in state/staff.json)
  replied  member posts where the owner/admin commented (ids listed in state/threads_tiers.json,
           built from comment fetches); member posts are context, never the expert's view
  replied_other  the same for Chat/Wins/Intros (threads_tiers.json `replied_other`)
  changed  tracked threads whose comment count / last comment / content hash moved since capture
           (feed_cursor.json `last_run.changed` from `skool_feed_index.py --mode refresh`)
--since / --days keep only posts created on or after that date (an age window for tiers that go stale).
Per thread: comments-API requests (25 top-level per page), plus one `_next/data` request for the post
unless the feed indexer's post cache (.secrets/scratch/<cache-name>/posts) holds a current copy. Writes raw/community/<YYYY-MM>/<YYYY-MM-DD>-<slug>.md; a later capture of a changed thread is a
new file `...-<slug>@<captured date>.md` with `supersedes:` (raw/ is immutable).
State: <brain>/state/threads_crawled.json. Stops cleanly on RateLimited.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from skool_session import configure, scratch_dir, source_prefix

import argparse
import datetime as dt
import json
import os
import pathlib

from playwright.sync_api import sync_playwright

from skool_classroom_crawl import slug
from skool_feed_index import content_sha1
from skool_session import BudgetExhausted, NotLoggedIn, RateLimited, api_get, next_data
from skool_thread import comment_items, role_of, thread_markdown

sys.stdout.reconfigure(encoding="utf-8")


def fetch_comments(browser, post_id, group_id, max_pages=40, *, brain):
    """All comment trees for a post. Returns (trees, pages, complete)."""
    base = f"https://api2.skool.com/posts/{post_id}/comments?group-id={group_id}&limit=25"
    trees, after, pages = [], None, 0
    while pages < max_pages:
        url = base + ("&pinned=true" if after is None else f"&created-gt={after}")  # Skool app: getPostComments(createdAfter)
        d = api_get(browser, url, brain=brain)
        pages += 1
        if after is None and d.get("pinned_post_tree"):
            trees.append(d["pinned_post_tree"])
        trees.append(d.get("post_tree") or {})
        last = str(d.get("last") or "0")
        if last in ("0", "", "None") or last == after:
            return trees, pages, True
        after = last
    return trees, pages, False


def load_jsonl(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def main():
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("--group", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--ids", nargs="*", default=[])
    ap.add_argument("--tier", choices=["expert", "replied", "replied_other", "changed"])
    ap.add_argument("--since", default=None, help="only posts created on/after YYYY-MM-DD")
    ap.add_argument("--days", type=int, default=0, help="only posts created in the last N days")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    brain, config = configure(args)
    prefix = source_prefix(brain)
    ROOT = brainlib.workspace(brain)
    group = args.group
    st = brain / "state"
    index = {r["id"]: r for r in load_jsonl(st / "posts.jsonl")}
    cursor = json.loads((st / "feed_cursor.json").read_text(encoding="utf-8")) if (st / "feed_cursor.json").exists() else {}
    labels = {l["id"]: l["name"] for l in cursor.get("labels") or []}
    staff_p = st / "staff.json"  # user id -> {name, handle, role: owner|admin|moderator}
    staff = {k: v["role"] for k, v in json.loads(staff_p.read_text(encoding="utf-8")).items()} if staff_p.exists() else {}
    tiers = json.loads((st / "threads_tiers.json").read_text(encoding="utf-8")) if (st / "threads_tiers.json").exists() else {}
    state_p = st / "threads_crawled.json"
    state = json.loads(state_p.read_text(encoding="utf-8")) if state_p.exists() else {}
    today = dt.date.today().isoformat()

    if args.ids:
        ids = args.ids
    elif args.tier == "expert":
        if not staff:
            sys.exit("state/staff.json missing: list owner/admin ids first")
        ids = [i for i, r in index.items() if r.get("author_id") in staff]
    elif args.tier in ("replied", "replied_other"):
        ids = tiers.get(args.tier, [])
    elif args.tier == "changed":
        ids = [i for i in (cursor.get("last_run") or {}).get("changed", []) if i in state]
        # the list predates this run's expert/replied crawls: skip threads already captured at the indexed state
        moved = lambda s, r: (r.get("comments") or 0) > (s.get("comments") or 0) or \
            (r.get("last_comment_ns") or 0) > (s.get("last_comment_ns") or 0) or \
            (r.get("content_sha1") and r.get("content_sha1") != s.get("content_sha1"))
        ids = [i for i in ids if moved(state[i], index.get(i, {}))]
    else:
        sys.exit("give --ids or --tier")
    if args.tier in ("expert", "replied", "replied_other"):
        ids = [i for i in ids if i not in state]
    since = args.since or ((dt.date.today() - dt.timedelta(days=args.days)).isoformat() if args.days else None)
    if since:
        ids = [i for i in ids if (index.get(i, {}).get("created") or "")[:10] >= since]
    if args.limit:
        ids = ids[: args.limit]
    print(f"{len(ids)} threads to crawl", flush=True)
    if args.dry_run:
        for i in ids:
            r = index.get(i, {})
            print(i, r.get("created", "")[:10], r.get("comments"), r.get("title"))
        return

    def save_state():
        st.mkdir(parents=True, exist_ok=True)
        state_p.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")

    done = errors = 0
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{args.port}")
        try:
            for pid in ids:
                try:
                    row = index.get(pid)
                    name = row["name"] if row else None
                    if not name:
                        print(f"{pid}: not in posts.jsonl; run the feed index first", flush=True)
                        continue
                    cached = scratch_dir(brain, "posts") / f"{pid}.json"
                    post = json.loads(cached.read_text(encoding="utf-8")) if cached.exists() else None
                    if post and row and content_sha1(post) != row.get("content_sha1"):
                        post = None  # cache is older than the index row
                    if not post:
                        post = next_data(browser, f"{group}/{name}", brain=brain)["pageProps"]["postTree"]["post"]
                    group_id = post["groupId"]
                    trees, pages, complete = fetch_comments(browser, pid, group_id, brain=brain)
                    author_role = role_of(post.get("user") or {"id": post.get("userId")}, staff)
                    staff_comments = sum(1 for t in trees for _, c in comment_items(t)
                                         if (c.get("user_id") or (c.get("user") or {}).get("id")) in staff)
                    voice = "expert" if author_role != "member" else ("replied" if staff_comments else "member")
                    created = post["createdAt"][:10]
                    out_dir = brain / "raw" / "community" / created[:7]
                    out = out_dir / f"{created}-{slug(post['metadata'].get('title') or name)}.md"
                    prev = state.get(pid, {})
                    supersedes = None
                    if not prev.get("raw_path") and out.exists():
                        # a different post with the same date and title slug: disambiguate by post id
                        out = out.with_name(out.stem + f"-{pid[:8]}.md")
                    if prev.get("raw_path") or out.exists():
                        supersedes = prev.get("raw_path") or str(out.relative_to(ROOT)).replace("\\", "/")
                        out = out.with_name(pathlib.Path(supersedes).stem.split("@")[0] + f"@{today}.md")
                        if out.exists():
                            print(f"{pid}: {out.name} exists, skipping", flush=True)
                            continue
                    md = thread_markdown(post, trees, staff, labels, group, f"{prefix}-post-{pid[:8]}", voice, today)
                    if supersedes:
                        md = md.replace("\n---\n", f"\nsupersedes: {json.dumps(supersedes)}\n---\n", 1)
                    if not complete:
                        md = md.replace("\n---\n", "\ncomments_complete: false\n---\n", 1)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    out.write_text(md, encoding="utf-8", newline="\n")
                    rel = str(out.relative_to(ROOT)).replace("\\", "/")
                    m = post["metadata"]
                    state[pid] = {"raw_path": rel, "captured": today, "comments": m.get("comments"),
                                  "last_comment_ns": m.get("lastComment"), "content_sha1": (row or {}).get("content_sha1"),
                                  "comment_pages": pages, "voice": voice, "staff_comments": staff_comments}
                    done += 1
                    print(f"{pid}: wrote {rel} ({m.get('comments')} comments, {pages} comment pages)", flush=True)
                    if done % 10 == 0:
                        save_state()
                except (RateLimited, BudgetExhausted, NotLoggedIn):
                    raise
                except Exception as e:  # one bad item must not stop a long unattended run; it is retried next run
                    errors += 1
                    print(f"{pid}: ERROR {type(e).__name__}: {str(e)[:300]}", flush=True)
        except (RateLimited, BudgetExhausted) as e:
            print(f"stopped: {type(e).__name__}: {e}", flush=True)
        finally:
            save_state()
    print(f"done: {done} written, {errors} errors", flush=True)


if __name__ == "__main__":
    main()

"""Offline stats over a Skool feed index (posts.jsonl): volume by role, year and category.

Usage: python -I tools/skool_feed_stats.py --brain <brain> [--json out.json]
No network. This preserves legacy role-code estimates; member_role_code comes from crawl.yaml.
Use state/staff.json for authoritative staff membership, not the gamification role codes.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from skool_session import configure

import argparse
import collections
import json
import pathlib

sys.stdout.reconfigure(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("--json")
    args = ap.parse_args()
    brain, config = configure(args)
    st = brain / "state"
    MEMBER = config.get("member_role_code", 4)
    rows = [json.loads(x) for x in (st / "posts.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    cur = json.loads((st / "feed_cursor.json").read_text(encoding="utf-8"))
    labels = {l["id"]: l["name"] for l in cur.get("labels") or []}

    staff = collections.defaultdict(lambda: {"posts": 0, "comments_on": 0, "chars": 0, "first": None, "last": None})
    by_role = collections.Counter()
    for r in rows:
        by_role[r.get("author_role")] += 1
        if r.get("author_role") not in (None, MEMBER):
            s = staff[(r["author_id"], r.get("author_name"), r.get("author_handle"), r.get("author_role"))]
            s["posts"] += 1
            s["comments_on"] += r["comments"]
            s["chars"] += r["content_chars"]
            s["first"] = min(filter(None, [s["first"], r["created"]]))
            s["last"] = max(filter(None, [s["last"], r["created"]]))

    staff_ids = {k[0] for k in staff}
    expert = [r for r in rows if r["author_id"] in staff_ids]
    member = [r for r in rows if r["author_id"] not in staff_ids]
    member_cmt = [r for r in member if r["comments"] > 0]
    contrib_flag = [r for r in member_cmt if staff_ids & set(r.get("contributor_ids") or [])]
    out = {
        "posts": len(rows),
        "reported_total": cur.get("total_reported"),
        "oldest": min(r["created"] for r in rows),
        "newest": max(r["created"] for r in rows),
        "by_role_code": dict(by_role),
        "staff": [{"id": k[0], "name": k[1], "handle": k[2], "role": k[3], **v} for k, v in
                  sorted(staff.items(), key=lambda kv: -kv[1]["posts"])],
        "tier_expert_posts": {"posts": len(expert), "comments": sum(r["comments"] for r in expert),
                              "chars": sum(r["content_chars"] for r in expert)},
        "member_posts": len(member),
        "member_posts_with_comments": {"posts": len(member_cmt), "comments": sum(r["comments"] for r in member_cmt)},
        "member_posts_staff_in_contributors": len(contrib_flag),
        "by_year": dict(sorted(collections.Counter(r["created"][:4] for r in rows).items())),
        "expert_by_year": dict(sorted(collections.Counter(r["created"][:4] for r in expert).items())),
        "by_category": {labels.get(k, k): v for k, v in collections.Counter(r["label_id"] for r in rows).most_common()},
        "expert_by_category": {labels.get(k, k): v for k, v in collections.Counter(r["label_id"] for r in expert).most_common()},
    }
    print(json.dumps(out, indent=1, ensure_ascii=False))
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

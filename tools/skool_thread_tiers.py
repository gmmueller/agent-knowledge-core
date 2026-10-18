"""Classify indexed Skool posts into crawl tiers -> <brain>/state/threads_tiers.json (offline, no network).

Usage: tools/.venv/Scripts/python -I tools/skool_thread_tiers.py --brain <brain>

Tiers (staff = owner/admins/moderators in state/staff.json):
  expert         posts authored by staff (the persona's own voice)
  replied        member posts in PRIORITY categories where staff appear in `contributor_ids`
  replied_other  member posts in other categories (Chat, Wins, Intros) with staff in contributors
  member_only    everything else: kept in the index, not crawled
Caveat: Skool lists at most 5 contributors per post, so staff replies on busy threads can be missed.
`skool_thread_crawl.py` refines this: any crawled member thread whose comments contain staff is
re-tagged `replied` in threads_crawled.json.
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
    args = ap.parse_args()
    brain, config = configure(args)
    st = brain / "state"
    PRIORITY = config.get("priority_categories", [])
    rows = [json.loads(x) for x in (st / "posts.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    staff = json.loads((st / "staff.json").read_text(encoding="utf-8"))
    labels = {l["id"]: l["name"] for l in json.loads((st / "feed_cursor.json").read_text(encoding="utf-8")).get("labels") or []}

    def priority(label_id):
        name = labels.get(label_id, "")
        return any(name.endswith(p) for p in PRIORITY)

    tiers = collections.defaultdict(list)
    for r in sorted(rows, key=lambda r: r["created"], reverse=True):
        if r["author_id"] in staff:
            tiers["expert"].append(r["id"])
        elif set(staff) & set(r.get("contributor_ids") or []):
            tiers["replied" if priority(r["label_id"]) else "replied_other"].append(r["id"])
        else:
            tiers["member_only"].append(r["id"])

    by_id = {r["id"]: r for r in rows}
    summary = {}
    for t, ids in tiers.items():
        rs = [by_id[i] for i in ids]
        summary[t] = {"posts": len(rs), "comments": sum(r["comments"] for r in rs),
                      "comment_pages_est": sum(1 + r["comments"] // 40 for r in rs),
                      "chars": sum(r["content_chars"] for r in rs)}
    summary["expert_by_author"] = dict(collections.Counter(staff[by_id[i]["author_id"]]["name"] for i in tiers["expert"]))
    (st / "threads_tiers.json").write_text(json.dumps({"summary": summary, **tiers}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Offline checks on a Skool brain's raw/ after a crawl (no network). Exit 1 if anything needs attention.

Usage: python -I tools/skool_verify.py --brain <brain>

Checks:
  classroom  every accessible, non-duplicate lesson in outline.yaml has a state entry and a raw file;
             no `needs_whisper` left; video lessons with a transcript under 50 words (warning)
  files      every attachment in state has its raw file
  community  every state entry's raw file exists; captured vs reported comment counts (warning, deleted
             comments make small gaps normal); `comments_complete: false`; a `supersedes:` that points at a
             file with a different post_id (filename collision)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from skool_session import configure, raw_path

import argparse
import json
import pathlib
import re

import yaml

sys.stdout.reconfigure(encoding="utf-8")


def front(path: pathlib.Path) -> dict:
    t = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", t, re.S)
    out = {}
    for ln in (m.group(1) if m else "").splitlines():
        k, _, v = ln.partition(":")
        out[k.strip()] = v.strip().strip('"')
    out["_body"] = t[m.end():] if m else t
    return out


def main():
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    args = ap.parse_args()
    brain, config = configure(args)
    ROOT = brainlib.workspace(brain)
    st = brain / "state"
    problems, warnings = [], []

    outline = yaml.safe_load((brain / "outline.yaml").read_text(encoding="utf-8"))
    crawled = json.loads((st / "classroom_crawled.json").read_text(encoding="utf-8"))
    lessons = [les for c in outline["courses"] if c.get("access") for s in c.get("sections") or []
               for les in s.get("lessons") or [] if not les.get("duplicate_of") and les.get("module_access") is not False]
    for les in lessons:
        rec = crawled.get(les["source_id"])
        if not rec:
            problems.append(f"lesson not crawled: {les['source_id']} {les['title']}")
        elif rec.get("method") == "needs_whisper":
            problems.append(f"lesson needs whisper: {les['source_id']} {rec.get('video')}")
        elif not (raw_path(brain, rec["raw_path"])).exists():
            problems.append(f"lesson raw file missing: {rec['raw_path']}")
        else:
            f = front(raw_path(brain, rec["raw_path"]))
            if f.get("method") in ("captions", "whisper"):
                tr = f["_body"].split("## Lesson page text")[0]
                if len(re.sub(r"\*\*\[[\d:]+\]\*\*", "", tr).split()) < 50:
                    warnings.append(f"short transcript: {rec['raw_path']}")
    print(f"classroom: {len(lessons)} lessons, {len(crawled)} in state")

    att_p = st / "attachments.json"
    att = json.loads(att_p.read_text(encoding="utf-8")) if att_p.exists() else {}
    for fid, rec in att.items():
        if not (raw_path(brain, rec["raw_path"])).exists():
            problems.append(f"attachment raw file missing: {rec['raw_path']}")
    print(f"files: {len(att)} attachments")

    threads = json.loads((st / "threads_crawled.json").read_text(encoding="utf-8"))
    by_path = {}
    for pid, rec in threads.items():
        p = raw_path(brain, rec["raw_path"])
        if not p.exists():
            problems.append(f"thread raw file missing: {rec['raw_path']}")
            continue
        by_path[rec["raw_path"]] = pid
    for p in sorted((brain / "raw" / "community").rglob("*.md")):
        f = front(p)
        rel = p.relative_to(ROOT).as_posix()
        if f.get("comments_complete") == "false":
            problems.append(f"comments incomplete: {rel}")
        rep, cap = f.get("comments"), f.get("comments_captured")
        if rep and cap and rep != cap:
            warnings.append(f"comments {cap}/{rep}: {rel}")
        sup = f.get("supersedes")
        if sup and (raw_path(brain, sup)).exists() and front(raw_path(brain, sup)).get("post_id") != f.get("post_id"):
            problems.append(f"false supersedes (different post): {rel} -> {sup}")
    print(f"community: {len(threads)} threads in state")

    for w in warnings:
        print("warn:", w)
    for pr in problems:
        print("PROBLEM:", pr)
    print(f"{len(problems)} problems, {len(warnings)} warnings")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

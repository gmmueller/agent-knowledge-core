"""List brains and sources that are due for a refresh (no browser, no network). Used by the scheduled reminder.

Usage: python -I tools/refresh_due.py --root <workspace> [--all]
  --root         folder containing brain folders and optional shared library
  --all          also list sources that aren't due, and brains with reminders switched off

Configuration (docs/updates.md):
  brain.md frontmatter   refresh: { reminders: true | false }      # false = never remind for this brain (default true)
  sources.yaml (each)    refresh: daily | weekly | monthly | quarterly | yearly | manual | never
                         last_crawled: <date or datetime>          # null = not crawled yet (reported, not "due")
A source is due when reminders are on, its cadence is a period, and last_crawled + period <= today.
"""
import argparse
import datetime as dt
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # python -I drops the script dir
import brainlib

PERIODS = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 91, "yearly": 365}


frontmatter = brainlib.read_frontmatter


def as_date(v) -> dt.date | None:
    if v in (None, "", "null"):
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v)[:10])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", "--workspace", required=True, help="workspace containing brain folders")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    show_all = a.all
    root = pathlib.Path(a.root).expanduser().resolve()
    if not root.is_dir():
        ap.error(f"workspace not found: {root}")
    today = dt.date.today()
    due_lines, other_lines, off = [], [], []
    entries = [(p.parent, frontmatter(p), p.parent.name) for p in sorted(root.glob("*/brain.md"))]
    entries += [(p.parent, {}, f"library/{p.parent.name}") for p in sorted(root.glob("library/*/sources.yaml"))]
    for brain, fm, identifier in entries:
        if brain.name.startswith("_"):
            continue  # hidden template folders
        name = fm.get("display_name") or identifier
        if not (fm.get("refresh") or {}).get("reminders", True):
            off.append(f"- {name} (`{brain.name}`): reminders off")
            continue
        for page in sorted((brain / "wiki").rglob("*.md")):
            metadata = frontmatter(page)
            if metadata.get("type") == "tool":
                recheck = as_date(metadata.get("recheck_by"))
                if recheck and recheck < today:
                    due_lines.append(f"- **{name} / {page.relative_to(brain).as_posix()}**: tool recheck overdue since {recheck}")
        src_file = brain / "sources.yaml"
        sources = (yaml.safe_load(src_file.read_text(encoding="utf-8")) or {}).get("sources") or [] if src_file.exists() else []
        for s in sources:
            cadence = str(s.get("refresh") or "manual").lower()
            last = as_date(s.get("last_crawled"))
            label = f"{name} / {s.get('title') or s.get('id')}"
            if cadence not in PERIODS:
                other_lines.append(f"- {label}: {cadence}, no reminder")
            elif last is None:
                other_lines.append(f"- {label}: {cadence}, not crawled yet (status: {s.get('status', '?')})")
            else:
                next_due = last + dt.timedelta(days=PERIODS[cadence])
                login = " (needs the logged-in browser)" if str(s.get("access", "")).startswith("login") else ""
                if next_due <= today:
                    due_lines.append(f"- **{label}**: {cadence}, last crawled {last}, due since {next_due}{login}")
                else:
                    other_lines.append(f"- {label}: {cadence}, next due {next_due}")
    print(f"# Brain refresh check ({today})\n")
    if due_lines:
        print(f"Due for refresh ({len(due_lines)}):")
        print("\n".join(due_lines))
        print("\nTo refresh, follow docs/updates.md (session check, diff, crawl the delta, ingest, lint, report).")
    else:
        print("Nothing is due.")
    if show_all:
        if other_lines:
            print("\nNot due:\n" + "\n".join(other_lines))
        if off:
            print("\nReminders off:\n" + "\n".join(off))


if __name__ == "__main__":
    main()

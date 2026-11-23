"""Cut library catalogues into triage input files for one brain (docs/triage.md).

Usage: python -I tools/triage_inputs.py --brain <brain> <publisher> [--kinds video,short] [--chunk 300]
                                       [--shorts-prefilter 150:20] [--since YYYY-MM-DD]

Writes <brain>/ingest/triage/input/<publisher>-<n>.tsv with columns
item, kind, title, published, duration_s, views, description (first 200 chars).
Items already scored in <brain>/ingest/triage/<publisher>.tsv or <publisher>-<n>.tsv, or already listed in
<brain>/selection.yaml, are skipped, so it can be re-run after new crawls.
--since DATE keeps only rows published on or after DATE, for refreshing a publisher whose first triage
covered a filtered subset of its catalogue. Rows with no published date are skipped (and counted), so
date new rows first with library_yt.py catalogue --details N.
--shorts-prefilter TOP:PER_YEAR keeps only the TOP most-viewed shorts plus the PER_YEAR most-viewed per year
(for publishers with thousands of Shorts, where Shorts are wanted as examples).
"""
import argparse
import os
import pathlib
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib
import library_raw as lr  # noqa: E402
from reference_sources import ReferenceSources, enabled as reference_mode

COLS = ["item", "kind", "title", "published", "duration_s", "views", "description"]


def views(r):
    try:
        return int(float(r.get("views") or 0))
    except ValueError:
        return 0


def already_scored(brain: pathlib.Path, publisher: str) -> set:
    """Item ids already scored for this publisher: triage outputs (whole or chunked) and selection.yaml."""
    done = set()
    triage = brain / "ingest" / "triage"
    for scored in [triage / f"{publisher}.tsv", *sorted(triage.glob(f"{publisher}-*.tsv"))]:
        if scored.exists():
            done |= {ln.split("\t", 1)[0] for ln in scored.read_text(encoding="utf-8").splitlines()[1:]}
    selection = brain / "selection.yaml"
    if selection.exists():
        data = yaml.safe_load(selection.read_text(encoding="utf-8")) or {}
        done |= {str(entry["item"]) for entry in data.get("items") or []
                 if isinstance(entry, dict) and str(entry.get("item", "")).startswith(f"{publisher}/")}
    return done


def main() -> None:
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("publisher")
    ap.add_argument("--kinds", default="")
    ap.add_argument("--chunk", type=int, default=300)
    ap.add_argument("--shorts-prefilter", default="")
    ap.add_argument("--since", default="", help="only rows published on or after this date (YYYY-MM-DD)")
    a = ap.parse_args()

    brain = brainlib.brain_dir(a.brain)
    lr.init(brainlib.workspace(brain))
    settings = brainlib.read_frontmatter(brain / "brain.md")
    references = ReferenceSources(brain, settings) if reference_mode(settings) else None
    cols = COLS + ["authority", "version", "superseded"] if references is not None else COLS
    rows = list(lr.read_catalogue(a.publisher).values())
    if a.kinds:
        rows = [r for r in rows if r["kind"] in a.kinds.split(",")]
    if a.shorts_prefilter:
        top, per_year = (int(x) for x in a.shorts_prefilter.split(":"))
        shorts = sorted((r for r in rows if r["kind"] == "short"), key=views, reverse=True)
        keep = {r["id"] for r in shorts[:top]}
        by_year: dict[str, list] = {}
        for r in shorts:
            by_year.setdefault((r.get("published") or "")[:4] or "unknown", []).append(r)
        for yr in by_year.values():
            keep |= {r["id"] for r in yr[:per_year]}
        rows = [r for r in rows if r["kind"] != "short" or r["id"] in keep]

    if a.since:
        undated = sum(1 for r in rows if not r.get("published"))
        rows = [r for r in rows if (r.get("published") or "") >= a.since]
        if undated:
            print(f"--since skipped {undated} rows with no published date; "
                  "date new rows first with library_yt.py catalogue --details N")

    done = already_scored(brain, a.publisher)
    rows = [r for r in rows if f"{a.publisher}/{r['id']}" not in done]

    out_dir = brain / "ingest" / "triage" / "input"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{a.publisher}-*.tsv"):
        old.unlink()
    for n, i in enumerate(range(0, len(rows), a.chunk), 1):
        part = rows[i:i + a.chunk]
        lines = ["\t".join(cols)]
        for r in part:
            vals = [f"{a.publisher}/{r['id']}", r["kind"], r["title"], r.get("published", ""),
                    r.get("duration_s", ""), r.get("views", ""), (r.get("description") or "")[:200]]
            if references is not None:
                meta = references.metadata(a.publisher, r["id"], source=r.get("source"))
                vals += [meta["authority"] or "unknown", meta["version"], "yes" if meta["superseded"] else "no"]
            lines.append("\t".join(lr.clean_field(v) for v in vals))
        p = out_dir / f"{a.publisher}-{n}.tsv"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        print(f"{p.relative_to(lr.ROOT)}: {len(part)} rows")
    if not rows:
        print("nothing to triage")


if __name__ == "__main__":
    main()

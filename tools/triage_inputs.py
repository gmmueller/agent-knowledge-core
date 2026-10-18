"""Cut library catalogues into triage input files for one brain (docs/triage.md).

Usage: tools/.venv/Scripts/python -I tools/triage_inputs.py --brain <brain> <publisher> [--kinds video,short] [--chunk 300]
                                       [--shorts-prefilter 150:20]

Writes <brain>/ingest/triage/input/<publisher>-<n>.tsv with columns
item, kind, title, published, duration_s, views, description (first 200 chars).
Items already scored in <brain>/ingest/triage/<publisher>.tsv are skipped, so it can be re-run after new crawls.
--shorts-prefilter TOP:PER_YEAR keeps only the TOP most-viewed shorts plus the PER_YEAR most-viewed per year
(for publishers with thousands of Shorts, where Shorts are wanted as examples).
"""
import argparse
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib
import library_raw as lr  # noqa: E402

COLS = ["item", "kind", "title", "published", "duration_s", "views", "description"]


def views(r):
    try:
        return int(float(r.get("views") or 0))
    except ValueError:
        return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("publisher")
    ap.add_argument("--kinds", default="")
    ap.add_argument("--chunk", type=int, default=300)
    ap.add_argument("--shorts-prefilter", default="")
    a = ap.parse_args()

    brain = brainlib.brain_dir(a.brain)
    lr.init(brainlib.workspace(brain))
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

    done = set()
    scored = brain / "ingest" / "triage" / f"{a.publisher}.tsv"
    if scored.exists():
        done = {ln.split("\t", 1)[0] for ln in scored.read_text(encoding="utf-8").splitlines()[1:]}
    rows = [r for r in rows if f"{a.publisher}/{r['id']}" not in done]

    out_dir = brain / "ingest" / "triage" / "input"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{a.publisher}-*.tsv"):
        old.unlink()
    for n, i in enumerate(range(0, len(rows), a.chunk), 1):
        part = rows[i:i + a.chunk]
        lines = ["\t".join(COLS)]
        for r in part:
            vals = [f"{a.publisher}/{r['id']}", r["kind"], r["title"], r.get("published", ""),
                    r.get("duration_s", ""), r.get("views", ""), (r.get("description") or "")[:200]]
            lines.append("\t".join(lr.clean_field(v) for v in vals))
        p = out_dir / f"{a.publisher}-{n}.tsv"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        print(f"{p.relative_to(lr.ROOT)}: {len(part)} rows")
    if not rows:
        print("nothing to triage")


if __name__ == "__main__":
    main()

"""Merge ingest/triage/*.tsv into selection.yaml. Usage: triage_merge.py --brain <brain>."""
import argparse
import collections
import csv
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib
from reference_sources import enabled as reference_mode

frontmatter = brainlib.read_frontmatter

SCORES = ("relevance", "density", "voice", "unique", "fresh")
REFERENCE_SCORES = ("relevance", "density", "authority", "unique", "currency")
TIERS = ("A", "B", "C", "X")


def merge(brain):
    settings = frontmatter(brain / "brain.md")
    reference = reference_mode(settings)
    score_keys = REFERENCE_SCORES if reference else SCORES
    minimum = ("relevance", "density", "authority", "currency") if reference else ("relevance", "density", "voice")
    weight_fresh = (settings.get("triage") or {}).get("weight_fresh", False)
    selection = brain / "selection.yaml"
    data = yaml.safe_load(selection.read_text(encoding="utf-8")) or {} if selection.exists() else {}
    items = {entry["item"]: entry for entry in data.get("items") or []}
    for entry in items.values():
        if "override" in entry:
            entry.setdefault("tier", entry["override"])
            if entry["tier"] not in TIERS or entry["override"] not in TIERS:
                raise ValueError(f"{selection}: invalid tier/override for {entry['item']}")

    def total(scores):
        return sum(scores.get(key, 0) for key in score_keys if key != "fresh" or weight_fresh)

    seen = set()
    for path in sorted((brain / "ingest" / "triage").glob("*.tsv")):
        with path.open(encoding="utf-8", newline="") as stream:
            rows = csv.DictReader(stream, delimiter="\t")
            required = {"item", "example", "speakers", "why", *score_keys}
            if not required.issubset(rows.fieldnames or []):
                raise ValueError(f"{path}: missing columns {sorted(required - set(rows.fieldnames or []))}")
            for line, row in enumerate(rows, 2):
                where = f"{path}:{line}"
                item = row["item"]
                if not item or item in seen:
                    raise ValueError(f"{where}: empty or duplicate item '{item}'")
                seen.add(item)
                scores = {key: int(row[key]) for key in score_keys}
                example = int(row["example"])
                if any(value not in range(4) for value in scores.values()) or example not in (0, 1):
                    raise ValueError(f"{where}: scores must be 0-3 and example 0-1")
                qualifies = (min(scores[k] for k in minimum) >= 2
                             and scores["unique"] >= 1 and total(scores) >= 9)
                tier = "X" if example else "A" if qualifies else "B" if scores["relevance"] >= 2 else "C"
                previous = items.get(item, {})
                if "override" in previous:
                    tier = previous["tier"]
                items[item] = {**previous, "item": item, "tier": tier, "scores": scores,
                               "speakers": [s.strip() for s in row["speakers"].split(";") if s.strip()], "why": row["why"]}
    def order(entry):
        score = total(entry["scores"]) if entry.get("scores") else -1
        return TIERS.index(entry["tier"]), -score, entry["item"]
    merged = sorted(items.values(), key=order)
    data.update(brain=brain.name, triage_version=1, items=merged)
    selection.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    counts = collections.Counter(entry["tier"] for entry in merged)
    print(" ".join(f"{tier}: {counts[tier]}" for tier in TIERS))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(ap)
    args = ap.parse_args()
    try:
        merge(brainlib.brain_dir(args.brain))
    except ValueError as exc:
        sys.exit(str(exc))

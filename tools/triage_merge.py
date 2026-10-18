"""Merge ingest/triage/*.tsv into selection.yaml. Usage: triage_merge.py --brain <brain>."""
import argparse
import collections
import csv
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib

frontmatter = brainlib.read_frontmatter

SCORES = ("relevance", "density", "voice", "unique", "fresh")
TIERS = "ABCX"


def merge(brain):
    weight_fresh = (frontmatter(brain / "brain.md").get("triage") or {}).get("weight_fresh", False)
    selection = brain / "selection.yaml"
    data = yaml.safe_load(selection.read_text(encoding="utf-8")) or {} if selection.exists() else {}
    items = {entry["item"]: entry for entry in data.get("items") or []}
    seen = set()
    for path in sorted((brain / "ingest" / "triage").glob("*.tsv")):
        with path.open(encoding="utf-8", newline="") as stream:
            rows = csv.DictReader(stream, delimiter="\t")
            required = {"item", "example", "speakers", "why", *SCORES}
            if not required.issubset(rows.fieldnames or []):
                raise ValueError(f"{path}: missing columns {sorted(required - set(rows.fieldnames or []))}")
            for line, row in enumerate(rows, 2):
                where = f"{path}:{line}"
                item = row["item"]
                if not item or item in seen:
                    raise ValueError(f"{where}: empty or duplicate item '{item}'")
                seen.add(item)
                scores = {key: int(row[key]) for key in SCORES}
                example = int(row["example"])
                if any(value not in range(4) for value in scores.values()) or example not in (0, 1):
                    raise ValueError(f"{where}: scores must be 0-3 and example 0-1")
                score = sum(scores[key] for key in SCORES if key != "fresh" or weight_fresh)
                tier = ("X" if example else "A" if min(scores[k] for k in ("relevance", "density", "voice")) >= 2 and score >= 9
                        else "B" if scores["relevance"] >= 2 else "C")
                previous = items.get(item, {})
                if "override" in previous:
                    tier = previous.get("tier", previous["override"])
                    if tier not in TIERS or previous["override"] not in TIERS:
                        raise ValueError(f"{where}: invalid tier/override")
                items[item] = {**previous, "item": item, "tier": tier, "scores": scores,
                               "speakers": [s.strip() for s in row["speakers"].split(";") if s.strip()], "why": row["why"]}
    def order(entry):
        score = sum(entry["scores"][key] for key in SCORES if key != "fresh" or weight_fresh)
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

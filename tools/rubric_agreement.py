"""Compare two graders' rubric scores and report agreement per criterion.

Each input is a TSV with header `rubric	item	criterion	score` (score 0, 1, 2 or n/a).
Exact agreement is the share of shared (rubric, item, criterion) rows scored identically;
quadratic-weighted kappa corrects for chance on the 0-2 scale. Criteria below the
--threshold exact agreement are listed with their disagreements, so their anchors can be tightened.

Usage: python tools/rubric_agreement.py grader-a.tsv grader-b.tsv [--threshold 0.8]
"""
import argparse
import collections
import csv
import sys


def load(path):
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return {(r["rubric"].strip(), r["item"].strip(), r["criterion"].strip()): r["score"].strip().lower()
            for r in rows}


def kappa(pairs, k=3):
    """Quadratic-weighted Cohen's kappa for integer scores 0..k-1."""
    if not pairs:
        return float("nan")
    n = len(pairs)
    observed = [[0] * k for _ in range(k)]
    for a, b in pairs:
        observed[a][b] += 1
    rows = [sum(observed[i]) for i in range(k)]
    cols = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    weight = lambda i, j: (i - j) ** 2 / (k - 1) ** 2
    num = sum(weight(i, j) * observed[i][j] for i in range(k) for j in range(k))
    den = sum(weight(i, j) * rows[i] * cols[j] / n for i in range(k) for j in range(k))
    return 1 - num / den if den else 1.0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("a")
    parser.add_argument("b")
    parser.add_argument("--threshold", type=float, default=0.8)
    args = parser.parse_args()
    a, b = load(args.a), load(args.b)
    shared = sorted(set(a) & set(b))
    missing = len(set(a) ^ set(b))
    by_criterion = collections.defaultdict(list)
    for key in shared:
        by_criterion[(key[0], key[2])].append((key[1], a[key], b[key]))

    out = sys.stdout
    out.write(f"{len(shared)} shared scores ({missing} only in one file)\n\n")
    out.write("| Rubric | Criterion | n | Exact | Within 1 | Kappa |\n|---|---|---|---|---|---|\n")
    totals = collections.defaultdict(list)
    weak = []
    for (rubric, criterion), items in sorted(by_criterion.items()):
        numeric = [(int(x), int(y)) for _, x, y in items if x.isdigit() and y.isdigit()]
        exact = sum(x == y for _, x, y in items) / len(items)
        near = sum(abs(x - y) <= 1 for x, y in numeric) / len(numeric) if numeric else 1.0
        out.write(f"| {rubric} | {criterion} | {len(items)} | {exact:.0%} | {near:.0%} | {kappa(numeric):.2f} |\n")
        totals[rubric].extend(items)
        if exact < args.threshold:
            weak.append((rubric, criterion, [(i, x, y) for i, x, y in items if x != y]))
    out.write("\n")
    for rubric, items in sorted(totals.items()):
        numeric = [(int(x), int(y)) for _, x, y in items if x.isdigit() and y.isdigit()]
        exact = sum(x == y for _, x, y in items) / len(items)
        out.write(f"{rubric}: exact {exact:.0%} over {len(items)} scores, kappa {kappa(numeric):.2f}\n")
    if weak:
        out.write(f"\nBelow {args.threshold:.0%} exact agreement:\n")
        for rubric, criterion, diffs in weak:
            out.write(f"- {rubric} {criterion}: " + "; ".join(f"{i} {x} vs {y}" for i, x, y in diffs) + "\n")


if __name__ == "__main__":
    main()

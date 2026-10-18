"""Set hand overrides in <brain>/selection.yaml (they survive tools/triage_merge.py re-runs).

Usage: tools/.venv/Scripts/python -I tools/selection_override.py --brain <brain> <tier> <item> [<item> ...] [--why "reason"]
  tier: A | B | C | X     item: <publisher>/<id>
"""
import argparse
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib



def main() -> None:
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("tier", choices=list("ABCX"))
    ap.add_argument("items", nargs="+")
    ap.add_argument("--why", default="")
    a = ap.parse_args()
    path = brainlib.brain_dir(a.brain) / "selection.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    by_item = {it["item"]: it for it in data["items"]}
    missing = [i for i in a.items if i not in by_item]
    for i in a.items:
        if i in by_item:
            by_item[i]["tier"] = by_item[i]["override"] = a.tier
            if a.why:
                by_item[i]["override_why"] = a.why
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    print(f"set {len(a.items) - len(missing)} item(s) to {a.tier}" + (f"; not in selection: {missing}" if missing else ""))


if __name__ == "__main__":
    main()

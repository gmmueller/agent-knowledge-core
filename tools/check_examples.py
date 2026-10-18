"""Check that every example page cites only its own video (examples file and raw transcript).

Usage: tools/.venv/Scripts/python -I tools/check_examples.py --brain <brain>
Exit code 1 if any page cites another item's examples/ file or another video's raw transcript.
"""
import argparse
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib

CITE = re.compile(r"\[\[library/([^/\]]+)/(examples|raw)/([^\]|]+?)(?:\.md|\.yaml)?\]\]")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(ap)
    args = ap.parse_args()
    brain = brainlib.brain_dir(args.brain)
    bad = 0
    pages = sorted((brain / "wiki" / "examples").glob("*.md"))
    for p in pages:
        text = p.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        fm = (yaml.safe_load(m.group(1)) or {}) if m else {}
        item = str(fm.get("item", ""))
        pub, _, iid = item.partition("/")
        vid = iid[3:] if iid.startswith("yt-") else iid
        wrong = set()
        for cpub, kind, rest in CITE.findall(text):
            if kind == "examples" and (cpub != pub or rest != iid):
                wrong.add(f"{cpub}/examples/{rest}")
            if kind == "raw" and (cpub != pub or vid not in rest):
                wrong.add(f"{cpub}/raw/{rest}")
        if wrong:
            bad += 1
            print(f"{p.relative_to(brainlib.workspace(brain))} ({item}): cites {sorted(wrong)}")
    print(f"{len(pages)} example pages, {bad} with foreign citations")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

"""Recompute rule status on a topic brain's wiki/rules pages (rule audit, pipeline step 6).

Usage: python -I tools/rule_status.py --brain <brain> [--write]

Speakers behind a rule = its bundle's speakers (<brain>/ingest/bundles/<slug>.yaml). Quotes on the page don't count:
writers also quote parallel or contrasting voices. A page with no bundle (a merged rule) falls back to its quote
speakers. Status, with brain.md's `experts`, `expert_aliases`, `voice_aliases` and `hosts`:
  consensus  2+ listed experts
  active     2+ independent voices (rule_status: voices) or, without that option, 2+ speakers
  bench      otherwise
`contested` is kept as the page writer set it, and so is any status on a page with `status_locked: true`
(orchestrator's call, e.g. a second voice that only partly supports the rule; say why in `status_note`). Prints changes; --write rewrites the `status:` line.
"""
import argparse
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib

QUOTE_SPEAKER = re.compile(r'^>\s*["“].+?["”]\s*[—–-]+\s*(.+?)\s*\(\[\[', re.M)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(ap)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    brain = brainlib.brain_dir(args.brain)
    write = args.write
    front = yaml.safe_load(re.match(r"^---\n(.*?)\n---\n", (brain / "brain.md").read_text(encoding="utf-8"), re.S).group(1))
    experts = set(front.get("experts") or [])
    ealias = front.get("expert_aliases") or {}
    valias = front.get("voice_aliases") or {}
    hosts = set(front.get("hosts") or [])
    counts = {}
    for page in sorted((brain / "wiki" / "rules").glob("*.md")):
        text = page.read_text(encoding="utf-8")
        m = re.search(r"^status:\s*(\S+)", text, re.M)
        old = m.group(1) if m else None
        bundle = brain / "ingest" / "bundles" / f"{page.stem}.yaml"
        speakers = set((yaml.safe_load(bundle.read_text(encoding="utf-8")) or {}).get("speakers") or []) if bundle.exists() else set()
        if not bundle.exists():
            speakers = set(QUOTE_SPEAKER.findall(text))
        named = {ealias.get(s, s) for s in speakers if s and s not in hosts}
        voices = {valias.get(v, v) for v in named}
        backing = named & experts
        locked = re.search(r"^status_locked:\s*true", text, re.M)
        new = (old if locked else "contested" if old == "contested" else "consensus" if len(backing) >= 2 else
               "active" if len(voices) >= 2 else "bench")
        counts[new] = counts.get(new, 0) + 1
        if new != old:
            print(f"{page.stem:60} {old} -> {new}  ({', '.join(sorted(voices))})")
            if write and m:
                page.write_text(text[:m.start()] + f"status: {new}" + text[m.end():], encoding="utf-8", newline="\n")
    print(counts)


if __name__ == "__main__":
    main()

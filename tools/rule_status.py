"""Recompute rule status on a topic brain's wiki/rules pages.

Usage: python -I tools/rule_status.py --brain <brain> [--write]

Use supporting points and quotes from the bundle. Without a bundle, use the page's attributed quotes.
Both tools read `experts`, `expert_aliases`, `voice_aliases` and `hosts` from brain.md:
  consensus  2+ listed experts support the rule and no listed expert opposes it
  active     2+ independent voices (rule_status: voices), otherwise 2+ publishers or 3+ items
  bench      otherwise
Flags opposition for review. Keeps `contested` and any status with `status_locked: true`.
Prints changes by default. --write updates status lines on unprotected pages.
"""
import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib
import rule_evidence
import wiki_edits

QUOTE_SOURCE = re.compile(r'^>\s*["“].+?["”]\s*[—–-]+\s*(.+?)\s*\(\[\[([^\]|]+)(?:\|[^\]]*)?\]\]', re.M)
STATUS_LINE = re.compile(r"^(status:[ \t]*)[^\s#]+", re.M)


def evidence_for(brain, slug, body):
    bundle = brainlib.load_yaml(brain / "ingest" / "bundles" / f"{slug}.yaml")
    if bundle is not None:
        evidence = (bundle.get("points") or []) + (bundle.get("quotes") or [])
        # Older bundles may carry only flat speaker and item lists.
        return evidence or ([{"speaker": speaker} for speaker in bundle.get("speakers") or []]
                            + [{"item": item} for item in bundle.get("items") or []])
    workspace = brainlib.workspace(brain)
    return [{"speaker": speaker, "item": rule_evidence.raw_item(workspace, raw)}
            for speaker, raw in QUOTE_SOURCE.findall(body)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(ap)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    brain = brainlib.brain_dir(args.brain)
    settings = brainlib.read_frontmatter(brain / "brain.md")
    counts = {}
    protected = wiki_edits.protected_pages(brain) if args.write else set()
    for page in sorted((brain / "wiki" / "rules").glob("*.md")):
        text = page.read_text(encoding="utf-8")
        front, body = brainlib.split_frontmatter(text)
        old = front.get("status")
        result = rule_evidence.assess(settings, evidence_for(brain, page.stem, body), front)
        new = result.status
        rule_evidence.report_opposition(page.stem, result.opposing)
        counts[new] = counts.get(new, 0) + 1
        if new != old:
            print(f"{page.stem:60} {old} -> {new}  ({', '.join(sorted(result.voices))})")
            if args.write and page.relative_to(brain / "wiki").as_posix() not in protected:
                header = text[:len(text) - len(body)]
                updated = STATUS_LINE.sub(lambda match: match[1] + new, header, count=1) + body
                if updated != text:
                    page.write_text(updated, encoding="utf-8", newline="\n")
    print(counts)


if __name__ == "__main__":
    main()

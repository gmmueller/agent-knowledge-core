"""Recompute rule status on a topic brain's wiki/rules pages.

Usage: python -I tools/rule_status.py --brain <brain> [--write]

Use supporting points and quotes from the bundle. Without a bundle, use the page's attributed quotes.
Both tools read `experts`, `expert_aliases`, `voice_aliases` and `hosts` from brain.md:
  consensus  2+ listed experts support the rule and no listed expert opposes it
  active     2+ independent voices (rule_status: voices), otherwise 2+ publishers or 3+ items
  bench      otherwise
Flags opposition and discrepancies on rule pages for review. Keeps `contested` and locked statuses.
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
STATUS = re.compile(r"^\s*(?:[-*+]\s+)?(?:status\s*:\s*|this rule is\s+)"
                    r"`?(active|bench|consensus|contested)\b", re.I | re.M)
FENCED_CODE = re.compile(r"^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?(?:^[ \t]*\1[ \t]*$|\Z)", re.M | re.S)
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|(?<!\w)\x27[^\x27\n]*\x27(?!\w)')
DISSENT = re.compile(r"^#{1,6}\s+(?:dissent|contested by|official contradiction)\b([^\n]*)(.*?)(?=^#{1,6}\s|\Z)",
                     re.I | re.M | re.S)
OPPOSES = re.compile(r"\bstance\s*:\s*[`*_]*opposes\b", re.I)
OFFICIAL_CONTRADICTION = re.compile(r"\bofficial\s+(?:contradiction|(?:source|policy|guidance|rule)\s+"
                                    r"(?:contradicts|opposes|rejects))\b", re.I)
RAW_LINK = re.compile(r"\[\[((?:raw|library)/[^\]|#]+)")


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


def report_page_warnings(brain, slug, settings, body, evidence, old, new):
    body = FENCED_CODE.sub("", body)
    prose = "\n".join(QUOTED.sub("", line).replace("**", "").replace("__", "")
                      for line in body.splitlines() if not line.lstrip().startswith(">"))
    for status in sorted({m.lower() for m in STATUS.findall(prose)} - {old}):
        print(f"warning: {slug}: body says {status}, frontmatter says {old}")
    if new != "consensus":
        return

    dissent = [match[0] for match in DISSENT.finditer(body)]
    for line in body.splitlines():
        outside_quote = QUOTED.sub("", line).replace("**", "").replace("__", "")
        if OPPOSES.search(outside_quote) or OFFICIAL_CONTRADICTION.search(outside_quote):
            dissent.append(outside_quote)

    def mentions(name, text):
        return bool(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.I))

    aliases = {name: name for name in settings.get("experts") or []}
    aliases.update(settings.get("expert_aliases") or {})
    experts = set(settings.get("experts") or [])
    hosts = set(settings.get("hosts") or [])
    opponents = {expert for name, expert in aliases.items() if expert in experts and not {name, expert} & hosts
                 and any(mentions(name, section) for section in dissent)}
    if opponents:
        print(f"warning: {slug}: computes as consensus, but the page records dissent from {', '.join(sorted(opponents))}")

    official = settings.get("official") or []
    if (any(OFFICIAL_CONTRADICTION.search(QUOTED.sub("", section))
            or any(mentions(name, section) for name in official)
            or any(is_official_raw(brain, raw) for raw in RAW_LINK.findall(section))
            for section in dissent)
            or any(row.get("stance") == "opposes" and
                   (row.get("kind") == "official" or row.get("evidence") == "official"
                    or row.get("speaker") in official or is_official_raw(brain, row.get("raw")))
                   for row in evidence)):
        print(f"warning: {slug}: computes as consensus, but an official source is recorded as contradicting the rule")


def is_official_raw(brain, raw):
    if not raw:
        return False
    root = brainlib.workspace(brain) if raw.startswith("library/") else brain
    path = (root / (raw.removesuffix(".md") + ".md")).resolve()
    return (path.is_relative_to(root) and path.is_file()
            and brainlib.read_frontmatter(path).get("evidence") == "official")


def audit(brain, *, write):
    settings = brainlib.read_frontmatter(brain / "brain.md")
    counts = {}
    protected = wiki_edits.protected_pages(brain) if write else set()
    for page in sorted((brain / "wiki" / "rules").glob("*.md")):
        text = page.read_text(encoding="utf-8")
        front, body = brainlib.split_frontmatter(text)
        old = front.get("status")
        evidence = evidence_for(brain, page.stem, body)
        result = rule_evidence.assess(settings, evidence, front)
        new = result.status
        rule_evidence.report_opposition(page.stem, result.opposing)
        if not write:
            report_page_warnings(brain, page.stem, settings, body, evidence, old, new)
        counts[new] = counts.get(new, 0) + 1
        if new != old:
            print(f"{page.stem:60} {old} -> {new}  ({', '.join(sorted(result.voices))})")
            name = page.relative_to(brain / "wiki").as_posix()
            if write and name not in protected:
                header = text[:len(text) - len(body)]
                updated = STATUS_LINE.sub(lambda match: match[1] + new, header, count=1) + body
                if updated != text:
                    wiki_edits.write_page(brain, name, updated, expected=wiki_edits.hashes.digest_bytes(text.encode("utf-8")),
                                         require_pass=False)
    print(counts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(ap)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    try:
        audit(brainlib.brain_dir(args.brain), write=args.write)
    except (ValueError, OSError) as exc:
        ap.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()

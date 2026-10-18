"""Lint a brain's wiki: broken [[links]], orphan pages, rule status vs evidence, missing sections.

Usage: python -I tools/lint_wiki.py --brain <brain-folder> [--fix-slug-map]
  --fix-slug-map  rewrite [[old-slug]] links using <brain>/ingest/slug-map.yaml before linting

Complements tools/check_wiki.py (which verifies citations and quotes). Exit code 1 if broken links remain.
"""
import argparse
import collections
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # python -I drops the script dir
import brainlib
from check_wiki import TYPES, frontmatter

LINK = re.compile(r"\[\[([^\]|#]+?)(?:\|[^\]]*)?\]\]")
SPECIAL = {"index", "hot", "log"}


def pages(wiki: pathlib.Path) -> dict[str, pathlib.Path]:
    return {p.stem: p for p in wiki.rglob("*.md") if p.stem not in SPECIAL}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(ap)
    ap.add_argument("--fix-slug-map", action="store_true")
    a = ap.parse_args()
    brain = brainlib.brain_dir(a.brain)
    wiki = brain / "wiki"
    if a.fix_slug_map:
        slug_map = yaml.safe_load((brain / "ingest" / "slug-map.yaml").read_text(encoding="utf-8")) or {}
        n = 0
        for p in wiki.rglob("*.md"):
            t = p.read_text(encoding="utf-8")
            new = LINK.sub(lambda m: m.group(0).replace(m.group(1), slug_map[m.group(1)]) if m.group(1) in slug_map else m.group(0), t)
            if new != t:
                p.write_text(new, encoding="utf-8", newline="\n")
                n += 1
        print(f"slug map applied to {n} pages")
    all_pages = pages(wiki)
    inbound = collections.Counter()
    broken = collections.defaultdict(set)
    for name, p in all_pages.items():
        for target in LINK.findall(p.read_text(encoding="utf-8")):
            if target.startswith("raw/"):
                continue
            if target.startswith("library/"):
                raw = brainlib.workspace(brain) / (target if target.endswith((".md", ".yaml")) else target + ".md")
                if not raw.is_file() and not (brainlib.workspace(brain) / (target + ".yaml")).is_file():
                    broken[target].add(name)
                continue
            if target in all_pages:
                if target != name:
                    inbound[target] += 1
            else:
                broken[target].add(name)
    concept_pages = {n: p for n, p in all_pages.items() if p.parent.name != "sources"}
    orphans = sorted(n for n in concept_pages if inbound[n] == 0)
    print(f"{len(all_pages)} pages ({len(concept_pages)} concept, {len(all_pages) - len(concept_pages)} source)")
    print(f"broken link targets: {len(broken)}")
    for target, srcs in sorted(broken.items(), key=lambda kv: -len(kv[1])):
        print(f"  [[{target}]] from {len(srcs)}: {', '.join(sorted(srcs)[:6])}{' ...' if len(srcs) > 6 else ''}")
    print(f"orphan concept pages (no inbound links): {len(orphans)}")
    for o in orphans:
        print(f"  {o}")
    types = collections.Counter(frontmatter(p).get("type", "missing") for p in all_pages.values())
    print(f"page types: {dict(types)}")
    for kind in types.keys() - TYPES:
        print(f"unknown page type: {kind}")
    rules = [p for p in concept_pages.values() if frontmatter(p).get("type") == "rule"]
    status = collections.Counter()
    for p in rules:
        m = re.search(r"^status:\s*(\w+)", p.read_text(encoding="utf-8"), re.M)
        status[m.group(1) if m else "missing"] += 1
    print(f"rules: {dict(status)}")
    sys.exit(1 if broken else 0)


if __name__ == "__main__":
    main()

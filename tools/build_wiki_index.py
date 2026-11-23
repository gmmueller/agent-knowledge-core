"""Rebuild a brain's concept and source indexes and normalise source-page durations.

Usage: python -I tools/build_wiki_index.py --brain <brain-folder>

wiki/index.md lists concept pages by type with a [[link]], one-line summary and source count.
wiki/sources-index.md lists source pages by product and module or by publisher and year.
Durations given in seconds in source-page frontmatter are rewritten as m:ss / h:mm:ss.
"""
import argparse
import collections
import datetime as dt
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # python -I drops the script dir
import brainlib
import wiki_edits

AUTO_PROPOSAL = "# Proposed index rebuild"  # header marking a proposal this tool wrote and may refresh
TYPES = [("topic", "Topics"), ("principle", "Principles"), ("framework", "Frameworks"), ("method", "Methods"),
         ("rule", "Rules"), ("rubric", "Rubrics"), ("debate", "Debates"), ("tool", "Tools and platform facts"),
         ("glossary", "Glossary"), ("example", "Examples")]


def product_names(brain: pathlib.Path) -> dict[str, str]:
    """Source titles in registry order; outline titles cover products absent from the registry."""
    outline = (brainlib.load_yaml(brain / "outline.yaml", {}) or {}).get("products") or []
    config = brainlib.crawl_config(brain).get("products") or []
    names = {}
    for source in (brainlib.load_yaml(brain / "sources.yaml", {}) or {}).get("sources") or []:
        code = source.get("product") or source.get("code")
        if not code:
            code = next((p["code"] for p in config if p.get("source_id") == source.get("id")), None)
        if not code:
            code = next((p["code"] for p in outline if p.get("url") and p["url"].rstrip("/") == str(source.get("url", "")).rstrip("/")), None)
        if not code:
            # Older registries stored the product code in notes rather than a field.
            match = re.search(r"\(product code ([a-z0-9-]+)\)", source.get("notes") or "")
            code = match.group(1) if match else source.get("id")
        if code and source.get("title"):
            names[str(code)] = str(source["title"])
    for product in outline:
        names.setdefault(str(product["code"]), str(product.get("title") or product["code"]))
    return names


def split(text: str):
    m = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
    return (yaml.safe_load(m.group(1)) or {}, text[m.end():]) if m else ({}, text)


def one_line(body: str) -> str:
    body = re.sub(r"^# .*\n", "", body.strip(), count=1).strip()
    para = body.split("\n\n")[0]
    para = re.sub(r"^\*\*Summary\.\*\*\s*", "", para)
    para = re.sub(r"\(\[\[raw/[^)]*\)", "", para)
    para = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", para)
    para = re.sub(r"\[\[([^\]]+)\]\]", r"\1", para).replace("\n", " ")
    first = re.split(r"(?<=[.!?])\s", para, maxsplit=1)[0]
    return (first[:180] + "…") if len(first) > 180 else first


def fmt_duration(v):
    if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"\d+(\.\d+)?", v)):
        s = int(float(v))
        h, m, s = s // 3600, s % 3600 // 60, s % 60
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    return None


def rebuild(brain) -> None:
    products = product_names(brain)
    wiki = brain / "wiki"
    current = wiki_edits.snapshot(brain)
    wiki_edits.ensure_protected_unchanged(brain, current=current)
    protected = wiki_edits.protected_pages(brain, current=current)
    written = {}
    fixed = 0
    for p in (wiki / "sources").glob("*.md"):
        name = p.relative_to(wiki).as_posix()
        if name in protected:
            continue
        t = p.read_text(encoding="utf-8")
        m = re.search(r"^duration:\s*['\"]?(\d+(?:\.\d+)?)['\"]?\s*$", t, re.M)
        if m and fmt_duration(m.group(1)):
            t = t[:m.start()] + f'duration: "{fmt_duration(m.group(1))}"' + t[m.end():]
            written[name] = wiki_edits.write_page(brain, name, t, expected=initial_digest(current, name),
                                                 require_pass=False)
            fixed += 1
    by_type = collections.defaultdict(list)
    sources = collections.defaultdict(lambda: collections.defaultdict(list))
    for p in sorted(brainlib.wiki_pages(brain)):
        if p.stem in ("index", "sources-index", "hot", "log"):
            continue
        try:
            fm, body = split(p.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ValueError(f"{p.relative_to(brain).as_posix()}: bad frontmatter YAML: {exc}") from exc
        n = len(fm.get("sources") or [])
        title = (re.search(r"^# (.+)$", body, re.M) or [None, p.stem])[1]
        if fm.get("type") == "source" and fm.get("publisher"):  # topic brain: group by publisher
            sources[str(fm["publisher"])][str(fm.get("published") or "")[:4] or "undated"].append((p.stem, title))
        elif fm.get("type") == "source":
            product = fm.get("product") or ("attachments" if p.stem.startswith("att-") else "other")
            module = str(fm.get("module") or "Attachments")
            if not fm.get("product") and str(fm.get("module", "")).startswith("Community"):
                # Skool brains: community threads and Q&A digests grouped by month, lessons by course
                product, module = "community", str(fm.get("published") or "")[:7] or "undated"
            elif not fm.get("product") and not p.stem.startswith("att-"):
                product = "classroom"
            sources[product][module].append((p.stem, title))
        else:
            extra = f" `{fm.get('status')}`" if fm.get("type") == "rule" else ""
            if fm.get("type") in ("tool", "topic", "principle", "method") and fm.get("freshness") in ("platform", "tool-version"):
                extra += f" _{fm['freshness']}_"
            by_type[fm.get("type")].append(f"- [[{p.stem}]]{extra}: {one_line(body)} ({n} sources)")
    out = ["# Index", "",
           "Catalog of wiki concepts with links, one-line summaries and source counts. "
           "Rebuilt by `tools/build_wiki_index.py` after every ingest.", ""]
    for t, heading in TYPES:
        if by_type.get(t) or t in ("topic", "principle", "framework", "method", "rule", "glossary"):
            out += [f"## {heading}", ""] + sorted(by_type.get(t, []), key=str.lower) + [""]
    out += ["To find a specific source page, see [[sources-index]].", ""]
    source_out = ["# Sources index", "", "Rebuilt by `tools/build_wiki_index.py` after every ingest.", "", "## Sources", ""]
    for product in dict.fromkeys([*products, "attachments", "other", *sorted(sources)]):
        if product not in sources:
            continue
        source_out += [f"### {products.get(product, product.replace('-', ' ').title())}", ""]
        mods = sources[product].items()
        for module, items in (mods if product in products or product in ("attachments", "other") else sorted(mods, reverse=True)):
            source_out += [f"#### {module}", ""] + [f"- [[{s}|{t}]]" for s, t in sorted(items)] + [""]
    notes = [p for p in brainlib.iter_files(brain / "notes") if p.suffix == ".md"]
    if notes:
        out += ["## Your notes", ""]
        out += [f"- [[{p.relative_to(brain).with_suffix('').as_posix()}]]" for p in notes]
        out.append("")
    for name, lines in (("index.md", out), ("sources-index.md", source_out)):
        content = "\n".join(lines)
        if name in protected:
            proposal = brain / "ingest" / "proposals" / "wiki" / name
            if proposal.exists() and not proposal.read_text(encoding="utf-8").startswith(AUTO_PROPOSAL):
                # A proposal filed with `wiki_edits.py propose` is awaiting review: never overwrite it.
                print(f"{name} has human edits and an open proposal (ingest/proposals/wiki/{name}); "
                      "rebuild not written. Resolve that proposal, then rebuild.")
                continue
            brainlib.write_text(proposal, f"{AUTO_PROPOSAL}\n\nDate: {dt.date.today().isoformat()}\nPage: wiki/{name}\nWhy: index has human edits; review before replacing.\n\n---\n\n" + content)
            print(f"{name} has human edits; proposal: ingest/proposals/wiki/{name}")
        else:
            written[name] = wiki_edits.write_page(brain, name, content, expected=initial_digest(current, name),
                                                 require_pass=False)
    wiki_edits.record(brain, written=written)
    total = sum(len(v) for v in by_type.values())
    source_total = sum(len(items) for modules in sources.values() for items in modules.values())
    print(f"index.md: {total} concept pages; sources-index.md: {source_total} source pages; normalised {fixed} durations")


def initial_digest(current, name):
    return current[name].digest if name in current else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(ap)
    args = ap.parse_args()
    try:
        rebuild(brainlib.brain_dir(args.brain))
    except (ValueError, OSError) as exc:
        ap.exit(2, f"Could not complete the index rebuild. {exc}\n")


if __name__ == "__main__":
    main()

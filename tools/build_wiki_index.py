"""Rebuild a brain's wiki/index.md from the pages on disk, and normalise source-page durations.

Usage: python -I tools/build_wiki_index.py --brain <brain-folder>

index.md lists every page by type: [[link]], a one-line summary (first sentence of the page's opening paragraph
or **Summary.**), and the number of raw sources it draws on. Source pages are grouped by product and module.
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(ap)
    a = ap.parse_args()
    brain = brainlib.brain_dir(a.brain)
    products = product_names(brain)
    wiki = brain / "wiki"
    protected = wiki_edits.protected_pages(brain)
    written = {}
    fixed = 0
    for p in (wiki / "sources").glob("*.md"):
        if p.relative_to(wiki).as_posix() in protected:
            continue
        t = p.read_text(encoding="utf-8")
        m = re.search(r"^duration:\s*['\"]?(\d+(?:\.\d+)?)['\"]?\s*$", t, re.M)
        if m and fmt_duration(m.group(1)):
            t = t[:m.start()] + f'duration: "{fmt_duration(m.group(1))}"' + t[m.end():]
            p.write_text(t, encoding="utf-8", newline="\n")
            written[p.relative_to(wiki).as_posix()] = wiki_edits.hashes.digest(p)
            fixed += 1
    by_type = collections.defaultdict(list)
    sources = collections.defaultdict(lambda: collections.defaultdict(list))
    for p in sorted(brainlib.wiki_pages(brain)):
        if p.stem in ("index", "hot", "log"):
            continue
        fm, body = split(p.read_text(encoding="utf-8"))
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
           "Catalog of every wiki page: link, one-line summary, source count. Read this first on every query. "
           "Rebuilt by `tools/build_wiki_index.py` after every ingest.", ""]
    for t, heading in TYPES:
        if by_type.get(t) or t in ("topic", "principle", "framework", "method", "rule", "glossary"):
            out += [f"## {heading}", ""] + sorted(by_type.get(t, []), key=str.lower) + [""]
    out += ["## Sources", ""]
    for product in dict.fromkeys([*products, "attachments", "other", *sorted(sources)]):
        if product not in sources:
            continue
        out += [f"### {products.get(product, product.replace('-', ' ').title())}", ""]
        mods = sources[product].items()
        for module, items in (mods if product in products or product in ("attachments", "other") else sorted(mods, reverse=True)):
            out.append(f"- **{module}**: " + " · ".join(f"[[{s}|{t}]]" for s, t in sorted(items)))
        out.append("")
    notes = [p for p in brainlib.iter_files(brain / "notes") if p.suffix == ".md"]
    if notes:
        out += ["## Your notes", ""]
        out += [f"- [[{p.relative_to(brain).with_suffix('').as_posix()}]]" for p in notes]
        out.append("")
    if "index.md" in protected:
        proposal = brain / "ingest" / "proposals" / "index.md"
        if not proposal.exists():
            brainlib.write_text(proposal, f"# Proposed index rebuild\n\nDate: {dt.date.today().isoformat()}\nPage: wiki/index.md\nWhy: index has human edits; review before replacing.\n\n---\n\n" + "\n".join(out))
        print("index.md has human edits; proposal: ingest/proposals/index.md")
    else:
        (wiki / "index.md").write_text("\n".join(out), encoding="utf-8", newline="\n")
        written["index.md"] = wiki_edits.hashes.digest(wiki / "index.md")
    try:
        wiki_edits.record(brain, written=written)
    except ValueError as exc:
        ap.exit(2, f"Could not record the wiki baseline. {exc}\n")
    total = sum(len(v) for v in by_type.values())
    print(f"index.md: {total} concept pages, {sum(len(i) for m in sources.values() for i in m.values())} source pages; "
          f"normalised {fixed} durations")


if __name__ == "__main__":
    main()

"""Pool a topic brain's ingest staging by concept and write per-concept bundles for page writers.

Usage:
  python -I tools/merge_topic.py --brain <brain> survey     # concept table to stdout
  python -I tools/merge_topic.py --brain <brain> bundles    # write <brain>/ingest/bundles/*.yaml

Reads <brain>/ingest/staging/*.yaml (except examples-*.yaml) and the optional <brain>/ingest/slug-map.yaml
({old-slug: canonical-slug}). Every point and quote is tagged with its library item (from the raw file's
frontmatter) and speaker. Rule status uses the same supporting evidence and brain settings as rule_status.py.
Listed experts who oppose a rule are flagged for review. Existing locked or contested page statuses are kept.
Also writes _conflicts.yaml, _examples.yaml, _speaker_doubts.yaml, _findings.yaml, _tropes.yaml and _equipment.yaml pooled from all batches.
"""
import argparse
import collections
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib
import rule_evidence


def load(brain: pathlib.Path):
    rule_evidence.raw_item.cache_clear()
    workspace = brainlib.workspace(brain)
    slug_map = brainlib.load_yaml(brain / "ingest" / "slug-map.yaml") or {}
    concepts: dict[str, dict] = {}
    extras = {"conflicts": [], "examples": [], "speaker_doubts": [], "findings": [], "tropes": [], "equipment": []}
    for f in sorted((brain / "ingest" / "staging").glob("*.yaml")):
        if f.name.startswith("examples-"):
            continue
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        batch = data.get("batch", f.stem)
        for key in extras:
            for e in data.get(key) or []:
                extras[key].append({**(e if isinstance(e, dict) else {"text": e}), "batch": batch})
        for c in data.get("concepts") or []:
            slug = slug_map.get(c.get("slug"), c.get("slug"))
            b = concepts.setdefault(slug, {"slug": slug, "types": collections.Counter(), "names": [], "aliases": set(),
                                           "evidence": collections.Counter(), "freshness": collections.Counter(),
                                           "summaries": [], "points": [], "quotes": [], "batches": set()})
            b["types"][c.get("type")] += 1
            b["evidence"][c.get("evidence")] += 1
            b["freshness"][c.get("freshness")] += 1
            if c.get("name") and c["name"] not in b["names"]:
                b["names"].append(c["name"])
            b["aliases"].update(c.get("aliases") or [])
            if c.get("slug") != slug:
                b["aliases"].add(c.get("slug"))
            if c.get("summary"):
                b["summaries"].append({"batch": batch, "text": c["summary"]})
            b["batches"].add(batch)
            for kind in ("points", "quotes"):
                for p in c.get(kind) or []:
                    cite = p.get("cite") or {}
                    evidence = p.get("evidence") or c.get("evidence")
                    b[kind].append({"text": p.get("text"), "speaker": p.get("speaker"), "raw": cite.get("raw"),
                                    "at": str(cite.get("at")), "item": rule_evidence.raw_item(workspace, cite.get("raw", "")),
                                    "batch": batch, **{k: p[k] for k in ("variant", "kind", "stance") if p.get(k)},
                                    **({"evidence": evidence} if evidence else {})})
    return concepts, extras


def finish(b: dict, brain: pathlib.Path, settings: dict) -> dict:
    evidence = b["points"] + b["quotes"]
    items = sorted({p["item"] for p in evidence if p["item"]})
    speakers = {p["speaker"] for p in evidence if p.get("speaker")}
    aliases = settings.get("expert_aliases") or {}
    backing = {aliases.get(s, s) for s in speakers} & set(settings.get("experts") or [])
    ctype = b["types"].most_common(1)[0][0]
    out = {"slug": b["slug"], "type": ctype, "names": b["names"], "aliases": sorted(a for a in b["aliases"] if a),
           "evidence": b["evidence"].most_common(1)[0][0], "freshness": b["freshness"].most_common(1)[0][0],
           "items": items, "experts": sorted(backing), "speakers": sorted(speakers)}
    if ctype == "rule":
        page = brain / "wiki" / "rules" / f"{b['slug']}.md"
        result = rule_evidence.assess(settings, evidence, brainlib.read_frontmatter(page) if page.is_file() else {})
        out.update(status=result.status, experts=sorted(result.experts))
        rule_evidence.report_opposition(b["slug"], result.opposing)
    out.update({"summaries": b["summaries"], "points": b["points"], "quotes": b["quotes"]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(ap)
    ap.add_argument("mode", nargs="?", choices=("survey", "bundles"), default="survey")
    args = ap.parse_args()
    brain = brainlib.brain_dir(args.brain)
    mode = args.mode
    settings = brainlib.read_frontmatter(brain / "brain.md")
    concepts, extras = load(brain)
    bundles = {slug: finish(b, brain, settings) for slug, b in concepts.items() if slug}
    if mode == "survey":
        print(f"{'slug':48} {'type':10} items experts pts qts status")
        for s, b in sorted(bundles.items(), key=lambda kv: (kv[1]["type"], -len(kv[1]["items"]), kv[0])):
            print(f"{s:48} {b['type']:10} {len(b['items']):5} {len(b['experts']):7} {len(b['points']):3} "
                  f"{len(b['quotes']):3} {b.get('status', '')}")
        print(f"\n{len(bundles)} concepts; " + ", ".join(f"{k}: {len(v)}" for k, v in extras.items()))
        return
    out = brain / "ingest" / "bundles"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.yaml"):
        old.unlink()
    for slug, b in bundles.items():
        (out / f"{slug}.yaml").write_text(yaml.safe_dump(b, sort_keys=False, allow_unicode=True, width=120),
                                          encoding="utf-8", newline="\n")
    for key, rows in extras.items():
        (out / f"_{key}.yaml").write_text(yaml.safe_dump(rows, sort_keys=False, allow_unicode=True, width=120),
                                          encoding="utf-8", newline="\n")
    print(f"wrote {len(bundles)} bundles to {out.relative_to(brainlib.workspace(brain))}")


if __name__ == "__main__":
    main()

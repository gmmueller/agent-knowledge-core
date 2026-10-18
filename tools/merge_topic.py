"""Pool a topic brain's ingest staging by concept and write per-concept bundles for page writers.

Usage:
  tools/.venv/Scripts/python -I tools/merge_topic.py --brain <brain> survey     # concept table to stdout
  tools/.venv/Scripts/python -I tools/merge_topic.py --brain <brain> bundles    # write <brain>/ingest/bundles/*.yaml

Reads <brain>/ingest/staging/*.yaml (except examples-*.yaml) and the optional <brain>/ingest/slug-map.yaml
({old-slug: canonical-slug}). Every point and quote is tagged with its library item (from the raw file's
frontmatter) and speaker. Rule status, from the evidence (docs/plans/topic-brains/plan.md section 3):
  consensus  2+ experts from brain.md `experts:` back it with points or quotes (speakers mapped through
             the optional `expert_aliases:` {speaker label: expert}, e.g. co-authored papers)
  active     2+ independent sources: items from 2+ publishers, or 3+ items
  bench      otherwise
With `rule_status: voices` in brain.md, `active` instead needs 2+ independent voices: distinct speakers after
`expert_aliases:` and `voice_aliases:` ({speaker label: voice}, e.g. platform staff -> YouTube), ignoring `hosts:`.
One person repeating a rule across a book and talks stays `bench`.
`contested` is never set here: page writers set it when a debate page exists.
Also writes _conflicts.yaml, _examples.yaml, _speaker_doubts.yaml, _findings.yaml, _tropes.yaml and _equipment.yaml pooled from all batches.
"""
import argparse
import collections
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib

_front_cache: dict[str, dict] = {}
EXPERT_ALIASES: dict[str, str] = {}
VOICE_ALIASES: dict[str, str] = {}
HOSTS: set[str] = set()
BY_VOICES = False


def voices(speakers) -> set[str]:
    """Independent voices behind a set of speaker labels (rule_status: voices)."""
    out = set()
    for s in speakers:
        if not s or s in HOSTS:
            continue
        v = EXPERT_ALIASES.get(s, s)
        out.add(VOICE_ALIASES.get(v, v))
    return out


def raw_item(workspace: pathlib.Path, raw: str) -> str:
    """library/<pub>/raw/... -> '<pub>/<source_id>' (falls back to the path)."""
    rel = re.sub(r"\.md$", "", str(raw)) + ".md"
    if rel not in _front_cache:
        p = workspace / rel
        fm = {}
        if p.exists():
            m = re.match(r"^---\n(.*?)\n---\n", p.read_text(encoding="utf-8"), re.S)
            fm = (yaml.safe_load(m.group(1)) or {}) if m else {}
        _front_cache[rel] = fm
    fm = _front_cache[rel]
    return f"{fm['publisher']}/{fm['source_id']}" if fm.get("publisher") and fm.get("source_id") else rel


def load(brain: pathlib.Path):
    _front_cache.clear()
    sm = brain / "ingest" / "slug-map.yaml"
    slug_map = (yaml.safe_load(sm.read_text(encoding="utf-8")) or {}) if sm.exists() else {}
    bfm = re.match(r"^---\n(.*?)\n---\n", (brain / "brain.md").read_text(encoding="utf-8"), re.S)
    bfront = (yaml.safe_load(bfm.group(1)) or {}) if bfm else {}
    experts = set(bfront.get("experts") or [])
    # expert_aliases maps a speaker label (co-authored papers, joint authors) to the expert it counts as.
    global EXPERT_ALIASES
    EXPERT_ALIASES = bfront.get("expert_aliases") or {}
    global VOICE_ALIASES, HOSTS, BY_VOICES
    VOICE_ALIASES = bfront.get("voice_aliases") or {}
    HOSTS = set(bfront.get("hosts") or [])
    BY_VOICES = bfront.get("rule_status") == "voices"
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
                    b[kind].append({"text": p.get("text"), "speaker": p.get("speaker"), "raw": cite.get("raw"),
                                    "at": str(cite.get("at")), "item": raw_item(brainlib.workspace(brain), cite.get("raw", "")), "batch": batch,
                                    **{k: p[k] for k in ("variant", "kind") if p.get(k)}})
    return concepts, extras, experts


def finish(b: dict, experts: set) -> dict:
    items = sorted({p["item"] for p in b["points"] + b["quotes"]})
    publishers = {i.split("/", 1)[0] for i in items}
    backing = sorted({EXPERT_ALIASES.get(p.get("speaker"), p.get("speaker")) for p in b["points"] + b["quotes"]}
                     & experts)
    ctype = b["types"].most_common(1)[0][0]
    out = {"slug": b["slug"], "type": ctype, "names": b["names"], "aliases": sorted(a for a in b["aliases"] if a),
           "evidence": b["evidence"].most_common(1)[0][0], "freshness": b["freshness"].most_common(1)[0][0],
           "items": items, "experts": backing,
           "speakers": sorted({p["speaker"] for p in b["points"] + b["quotes"] if p.get("speaker")})}
    if ctype == "rule":
        independent = (len(voices(out["speakers"])) >= 2 if BY_VOICES
                       else len(publishers) >= 2 or len(items) >= 3)
        out["status"] = "consensus" if len(backing) >= 2 else "active" if independent else "bench"
    out.update({"summaries": b["summaries"], "points": b["points"], "quotes": b["quotes"]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(ap)
    ap.add_argument("mode", nargs="?", choices=("survey", "bundles"), default="survey")
    args = ap.parse_args()
    brain = brainlib.brain_dir(args.brain)
    mode = args.mode
    concepts, extras, experts = load(brain)
    bundles = {slug: finish(b, experts) for slug, b in concepts.items() if slug}
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

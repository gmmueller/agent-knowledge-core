"""Pool ingest staging files by concept, apply a slug map, and write per-concept bundles for page writers.

Usage:
  python -I tools/merge_staging.py --brain <brain-folder> survey          # concept table to stdout
  python -I tools/merge_staging.py --brain <brain-folder> bundles         # write <brain>/ingest/bundles/<slug>.yaml

Reads <brain>/ingest/staging/*.yaml and the optional <brain>/ingest/slug-map.yaml ({old-slug: canonical-slug}).
A bundle holds every point, quote and voice line about one canonical concept, each tagged with the lesson id and
presenter, plus the count of distinct lessons (rules: 1 lesson = bench, 2+ = active).
"""
import argparse
import collections
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # python -I drops the script dir
import brainlib



def lesson_of(raw: str, raw_to_lesson: dict) -> str:
    return raw_to_lesson.get(re.sub(r"\.md$", "", raw), raw)


def load(brain: pathlib.Path):
    slug_map = {}
    sm = brain / "ingest" / "slug-map.yaml"
    if sm.exists():
        slug_map = yaml.safe_load(sm.read_text(encoding="utf-8")) or {}
    batches = yaml.safe_load((brain / "ingest" / "batches.yaml").read_text(encoding="utf-8"))
    raw_to_lesson = {re.sub(r"\.md$", "", it["raw"]): it["id"] for b in batches.values() for it in b["items"]}
    presenters, concepts, voice, conflicts = {}, collections.defaultdict(lambda: {
        "types": collections.Counter(), "names": collections.Counter(), "aliases": set(), "summaries": [],
        "points": [], "quotes": [], "batches": set(), "orig_slugs": set()}), [], []
    for f in sorted((brain / "ingest" / "staging").glob("*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for l in data.get("lessons") or []:
            presenters[l["id"]] = l.get("presenter") or l.get("speakers") or "unknown"
        for c in data.get("concepts") or []:
            slug = slug_map.get(c["slug"], c["slug"])
            k = concepts[slug]
            k["types"][c.get("type")] += 1
            k["names"][c.get("name")] += 1
            k["aliases"].update(a for a in c.get("aliases") or [] if a)
            k["batches"].add(f.stem)
            k["orig_slugs"].add(c["slug"])
            if c.get("summary"):
                k["summaries"].append({"batch": f.stem, "text": c["summary"]})
            for kind in ("points", "quotes"):
                for it in c.get(kind) or []:
                    cite = it.get("cite") or {}
                    raw = re.sub(r"\.md$", "", str(cite.get("raw", "")))
                    entry = {"text": it.get("text"), "raw": raw, "at": str(cite.get("at")),
                             "lesson": lesson_of(raw, raw_to_lesson)}
                    if it.get("speaker"):
                        entry["speaker"] = it["speaker"]
                    k[kind].append(entry)
        for v in data.get("voice") or []:
            cite = v.get("cite") or {}
            raw = re.sub(r"\.md$", "", str(cite.get("raw", "")))
            voice.append({"text": v.get("text"), "raw": raw, "at": str(cite.get("at")), "note": v.get("note"),
                          "lesson": lesson_of(raw, raw_to_lesson), "batch": f.stem})
        for c in data.get("conflicts") or []:
            conflicts.append({**c, "batch": f.stem})
    return concepts, voice, conflicts, presenters


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(ap)
    ap.add_argument("mode", choices=("survey", "bundles"))
    a = ap.parse_args()
    brain = brainlib.brain_dir(a.brain)
    mode = a.mode
    concepts, voice, conflicts, presenters = load(brain)
    if mode == "survey":
        rows = []
        for slug, k in concepts.items():
            lessons = {p["lesson"] for p in k["points"] + k["quotes"]}
            rows.append((slug, k["types"].most_common(1)[0][0], len(lessons), len(k["points"]), len(k["quotes"]),
                         "".join(sorted(k["batches"])), ",".join(sorted(k["orig_slugs"] - {slug}))))
        for r in sorted(rows, key=lambda r: (r[1], -r[2])):
            print(f"{r[1]:9} {r[0]:55} lessons={r[2]:3} pts={r[3]:3} q={r[4]:3} batches={r[5]} {('merged:' + r[6]) if r[6] else ''}")
        print(f"\n{len(rows)} concepts, {len(voice)} voice lines, {len(conflicts)} conflicts")
        return
    out = brain / "ingest" / "bundles"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.yaml"):
        old.unlink()
    for slug, k in concepts.items():
        lessons = sorted({p["lesson"] for p in k["points"] + k["quotes"]})
        for it in k["points"] + k["quotes"]:
            it["presenter"] = presenters.get(it["lesson"], "unknown")
        bundle = {
            "slug": slug,
            "type": k["types"].most_common(1)[0][0],
            "names": [n for n, _ in k["names"].most_common()],
            "aliases": sorted(k["aliases"]),
            "lessons": lessons,
            "status": ("active" if len(lessons) >= 2 else "bench") if k["types"].most_common(1)[0][0] == "rule" else None,
            "summaries": k["summaries"],
            "points": k["points"],
            "quotes": k["quotes"],
        }
        (out / f"{slug}.yaml").write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True, width=200), encoding="utf-8")
    (out / "_voice.yaml").write_text(yaml.safe_dump(voice, sort_keys=False, allow_unicode=True, width=200), encoding="utf-8")
    (out / "_conflicts.yaml").write_text(yaml.safe_dump(conflicts, sort_keys=False, allow_unicode=True, width=200), encoding="utf-8")
    print(f"wrote {len(concepts)} bundles, _voice.yaml ({len(voice)}), _conflicts.yaml ({len(conflicts)})")


if __name__ == "__main__":
    main()

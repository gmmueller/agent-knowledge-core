"""Finalize a named speaker pass without overwriting raw. Usage: --workspace <workspace> PUBLISHER ITEM or --all PUBLISHER."""
import argparse
import copy
import io
import json
import math
import pathlib
import sys

import yaml
from ruamel.yaml import YAML

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib
import library_raw as lr
from diarize import caption_text, read_lines, validate

ROLES = {"host", "guest", "cohost", "other"}


def merge_people(people, publisher, item, names, roles):
    if not isinstance(people, dict):
        raise ValueError("people.yaml must be a mapping")
    people = copy.deepcopy(people)
    address = f"{publisher}/{item}"
    for name in dict.fromkeys(names):
        key = lr.slugify(name)
        # Unknown voices are item-local identities, never the same person across episodes.
        if name.startswith("Unknown Speaker "):
            key = f"{key}-{publisher}-{item}"
        person = people.setdefault(key, {"name": name, "aliases": [], "appearances": []})
        if not isinstance(person, dict) or person.get("name") != name:
            raise ValueError(f"person slug collision for {name}: {key}")
        person.setdefault("aliases", [])
        appearances = person.setdefault("appearances", [])
        if not isinstance(appearances, list) or not all(isinstance(x, dict) for x in appearances):
            raise ValueError(f"invalid appearances for {name}")
        existing = next((x for x in appearances if x.get("item") == address), None)
        if existing is None:
            appearances.append({"item": address, "role": roles[name]})
        else:
            existing["role"] = roles[name]
    return people


def named_lines(data, diar, naming):
    if diar.get("item") != data["item"] or not isinstance(naming, dict):
        raise ValueError("diar item mismatch or invalid names mapping")
    roles, confidence = naming.get("roles", {}), naming.get("confidence", {})
    labels = set(diar.get("speakers", {}))
    if not labels or not isinstance(roles, dict) or not isinstance(confidence, dict):
        raise ValueError("missing speakers, roles or confidence mapping")
    for label in labels:
        name = naming.get(label)
        if not isinstance(name, str) or not name.strip() or name != name.strip() or any(c in name for c in "\n\r"):
            raise ValueError(f"missing or invalid name for {label}")
        if roles.get(name) not in ROLES:
            raise ValueError(f"invalid or missing role for {name}")
        value = confidence.get(label)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ValueError(f"confidence for {label} must be a number 0..1")
    lines, previous = [], -1
    for line in diar["lines"]:
        if line.get("speaker") not in labels or not isinstance(line.get("text"), str):
            raise ValueError("unknown speaker or invalid diarized text")
        start, end = line["start"], line["end"]
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (start, end)) or not 0 <= start < end or start < previous:
            raise ValueError("invalid diarized timing")
        previous = start
        lines.append({**line, "speaker": naming[line["speaker"]]})
    original = caption_text(data["lines"])
    rendered = caption_text(lines)
    if "turn_timing" in diar:
        original = lr.clean_field(original.replace(">>", " "))
        if ">>" in rendered:
            raise ValueError("turn-aware diarization left speaker markers in text")
    if not lines or original != rendered:
        raise ValueError("diarization changed, lost or reordered caption text")
    return lines, roles


def finalize(publisher, item):
    # Shared across publishers; the temporary lock file disappears on normal release.
    with brainlib.file_lock(lr.LIBRARY / "people.yaml"):
        return finalize_locked(publisher, item)


def finalize_locked(publisher, item):
    data = read_lines(publisher, item)
    diar = json.loads(lr.staging_path(publisher, item, "diar.json").read_text(encoding="utf-8"))
    naming = yaml.safe_load(lr.staging_path(publisher, item, "names.yaml").read_text(encoding="utf-8"))
    lines, roles = named_lines(data, diar, naming)
    front = {**data["front"], "source_id": item, "publisher": publisher,
             "speakers": list(dict.fromkeys(x["speaker"] for x in lines)), "speaker_method": "diarized"}
    sub = item.split("-", 1)[0]
    path = lr.raw_path(publisher, sub, str(front.get("published") or ""), front["title"], item)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite raw file: {path}")
    people_path = lr.LIBRARY / "people.yaml"
    people_yaml = YAML()
    people_yaml.preserve_quotes = True
    people = people_yaml.load(people_path.read_text(encoding="utf-8")) if people_path.exists() else {}
    merged = merge_people(people or {}, publisher, item, front["speakers"], roles)
    buffer = io.StringIO()
    people_yaml.dump(merged, buffer)
    serialized = buffer.getvalue()
    # Prepare the people write before creating immutable raw; a failed merge leaves no raw behind.
    with brainlib.staged_text(people_path, serialized) as temporary:
        lr.write_raw(path, front, lr.render_transcript(lr.transcript_blocks(lines)))
        temporary.replace(people_path)
    print(path.relative_to(lr.ROOT))
    return path


def self_test():
    original = {"alice": {"name": "Alice", "aliases": ["Al"], "roles": ["expert"],
                           "appearances": [{"item": "publisher/yt-a", "role": "guest", "note": "keep"}]}}
    merged = merge_people(original, "publisher", "yt-a", ["Alice", "Alice"], {"Alice": "host"})
    assert merged["alice"]["aliases"] == ["Al"] and merged["alice"]["roles"] == ["expert"]
    assert merged["alice"]["appearances"] == [{"item": "publisher/yt-a", "role": "host", "note": "keep"}]
    assert original["alice"]["appearances"][0]["role"] == "guest"
    merged = merge_people(merged, "publisher", "pod-b", ["Alice"], {"Alice": "guest"})
    assert len(merged["alice"]["appearances"]) == 2
    data = {"item": "yt-a", "lines": [{"start": 0, "end": 2, "text": "hello there"}]}
    diar = {"item": "yt-a", "speakers": {"SPEAKER_0": {}}, "lines": [{"start": 0, "end": 2, "text": "hello there", "speaker": "SPEAKER_0"}]}
    naming = {"SPEAKER_0": "Alice", "roles": {"Alice": "host"}, "confidence": {"SPEAKER_0": .9}}
    assert named_lines(data, diar, naming)[0][0]["speaker"] == "Alice"
    data["lines"][0]["text"] = ">> hello [music] there"
    diar["lines"][0]["text"] = "hello [music] there"
    diar["turn_timing"] = {"estimated_boundaries": 0}
    naming["suspect"] = [0]
    assert named_lines(data, diar, naming)[0][0]["text"] == "hello [music] there"
    diar["lines"][0]["text"] = "hello there"
    try:
        named_lines(data, diar, naming)
    except ValueError:
        pass
    else:
        raise AssertionError("must preserve non-speaker tags")
    diar["lines"][0]["text"] = "lost words"
    try:
        named_lines(data, diar, naming)
    except ValueError:
        pass
    else:
        raise AssertionError("must reject caption loss")
    print("self-test passed")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_workspace_arg(ap)
    ap.add_argument("publisher", nargs="?")
    ap.add_argument("item", nargs="?")
    ap.add_argument("--all", dest="all_publisher", metavar="PUBLISHER")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    lr.init(args.workspace)
    if args.self_test:
        self_test()
        return
    publisher = args.all_publisher or args.publisher
    if not publisher or (args.all_publisher and (args.publisher or args.item)) or (not args.all_publisher and not args.item):
        ap.error("use PUBLISHER ITEM or --all PUBLISHER")
    validate(publisher, args.item or "yt-check")
    items = [p.name.removesuffix(".diar.json") for p in sorted((lr.pub_dir(publisher) / "staging").glob("*.diar.json"))] if args.all_publisher else [args.item]
    failures = []
    for item in items:
        try:
            if args.all_publisher:
                if not lr.staging_path(publisher, item, "names.yaml").exists():
                    print(f"SKIP {item}: needs names.yaml")
                    continue
                data = read_lines(publisher, item)
                front = data["front"]
                if lr.raw_path(publisher, item.split("-", 1)[0], str(front.get("published") or ""), front["title"], item).exists():
                    print(f"SKIP {item}: raw already exists")
                    continue
            finalize(publisher, item)
        except Exception as exc:
            print(f"FAILED {item}: {exc}", file=sys.stderr)
            failures.append(item)
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()

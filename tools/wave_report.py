"""Check a completed ingest wave with one compact report.

Usage: wave_report.py --brain FOLDER --batches ingest/batches.yaml [--wave KEY]
"""
import argparse
from functools import lru_cache
import pathlib
import re
import subprocess
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib
from library_raw import catalogue_id_for_raw, read_catalogue_file
import wiki_edits

LIBRARY = re.compile(r"^library/[^/]+/")
PAGE_DIRS = ("sources", "examples")  # topic briefs write `page: example` items to wiki/examples/
catalogue_rows = lru_cache(maxsize=None)(read_catalogue_file)


def normalized(value):
    value = str(value).replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return re.sub(r"\.md$", "", value)


def same(a, b):
    """Match two references; two publisher-qualified ones must match in full."""
    if a == b:
        return True
    if a.startswith("library/") and b.startswith("library/"):
        return False
    return LIBRARY.sub("", a) == LIBRARY.sub("", b)


def references(fm, keys):
    result = set()
    for key in keys:
        values = fm.get(key) or []
        if not isinstance(values, list):
            values = [values]
        for value in values:
            if isinstance(value, dict):
                value = value.get("raw") or value.get("item") or value.get("id", "")
            result.add(normalized(value))
    return result


@lru_cache(maxsize=None)
def raw_catalogue_reference(workspace, raw):
    parts = pathlib.PurePosixPath(raw).parts
    if len(parts) < 4 or parts[0] != "library" or parts[2] != "raw" or ".." in parts:
        return None
    publisher = parts[1]
    rows = catalogue_rows(workspace / "library" / publisher / "catalogue.tsv")
    item = catalogue_id_for_raw(workspace / (raw + ".md"), rows)
    return (publisher, item) if item else None


def stages_item(brain, item, entry):
    if item.get("raw") and entry.get("raw"):
        return normalized(item["raw"]) == normalized(entry["raw"])
    keys = ("raw", "item", "id")
    if any(same(wanted, staged) for wanted in references(item, keys)
           for staged in references(entry, keys)):
        return True
    for with_raw, with_id in ((item, entry), (entry, item)):
        if with_raw.get("raw"):
            match = raw_catalogue_reference(brainlib.workspace(brain), normalized(with_raw["raw"]))
            if match:
                publisher, catalogue_id = match
                return bool(references(with_id, ("item", "id")) & {catalogue_id, f"{publisher}/{catalogue_id}"})
    return False


def batch_report(brain, name, batch, pages):
    problems, selected = [], set()
    assigned = batch.get("items") or []
    for item in assigned:
        raw = item.get("raw")
        wanted = {normalized(item[key]) for key in ("item", "id") if item.get(key)}
        # Q&A digests share one page id and need not cite brief-reply threads; every other item
        # (including a recaptured lesson's new raw file) must be cited.
        digest = item.get("kind") == "qa" and item.get("id")
        folder = "examples" if item.get("page") == "example" else "sources"  # only the page kind the item asks for
        matches = {path for path, kind, sources, refs in pages if kind == folder and
                   ((digest and path.stem == digest) or
                    (normalized(raw) in sources if raw else any(same(w, r) for w in wanted for r in sources | refs)))}
        selected.update(matches)
        if not matches:
            problems.append(f"missing: {raw or item.get('item') or item.get('id', '')}")
    staging = brain / "ingest" / "staging" / f"{name}.yaml"
    files = [staging, *sorted(selected)]
    try:
        data = yaml.safe_load(staging.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data:
            raise ValueError("expected a nonempty YAML mapping")
        staged = []
        for key in ("lessons", "items"):
            entries = data.get(key, [])
            if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
                raise ValueError(f"'{key}' must be a list of mappings")
            staged.extend(entries)
        if not staged:
            raise ValueError("expected entries in 'lessons' or 'items'")
        if brainlib.read_frontmatter(brain / "brain.md").get("kind") == "topic":
            if not isinstance(data.get("concepts"), list):
                raise ValueError("topic staging requires a 'concepts' list (use [] if there are none)")
            staged = data.get("items", [])
            if not staged:
                raise ValueError("topic staging requires entries in 'items'")
            for entry in staged:
                if not (isinstance(entry.get("page"), str) and entry["page"].strip()
                        and isinstance(entry.get("speakers"), (dict, list))):
                    raise ValueError("each topic staging item needs 'page' and 'speakers'")
        for item in assigned:
            if not any(stages_item(brain, item, entry) for entry in staged):
                problems.append(f"staging missing: {item.get('raw') or item.get('item') or item.get('id', '')}")
    except (OSError, ValueError, yaml.YAMLError) as exc:
        problems.append(f"staging: {str(exc).splitlines()[0]}")
    if files:
        result = subprocess.run([sys.executable, "-X", "utf8", "-I", str(pathlib.Path(__file__).with_name("check_wiki.py")),
                                 "--brain", str(brain), *map(str, files)], capture_output=True)
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        if result.returncode or not re.search(r"^ok:", output, re.M):
            problems.extend(output.splitlines()[:5] or ["check_wiki: no ok: result"])
    return len(selected), problems


def main(argv=None):
    catalogue_rows.cache_clear()
    raw_catalogue_reference.cache_clear()
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(ap)
    ap.add_argument("--batches", required=True)
    ap.add_argument("--wave")
    ap.add_argument("--max-lines", type=int, default=25)
    args = ap.parse_args(argv)
    brain = brainlib.brain_dir(args.brain)
    if args.max_lines < 2:
        ap.error("--max-lines must be at least 2")
    try:
        batch_path = (brain / args.batches).resolve()
        if not batch_path.is_relative_to(brain):
            raise ValueError("--batches must be brain-relative")
        data = brainlib.load_yaml(batch_path)
        if not isinstance(data, dict) or not data:
            raise ValueError("batches must be a nonempty mapping")
        flat = all(isinstance(v, dict) and "items" in v for v in data.values())
        if flat:
            if args.wave:
                raise ValueError("--wave requires a waves file")
            batches = list(data.items())
        else:
            waves = {args.wave: data[args.wave]} if args.wave else data
            batches = [(name, batch) for wave in waves.values() for name, batch in wave.items()]
        pages = []
        for folder in PAGE_DIRS:
            for path in sorted((brain / "wiki" / folder).rglob("*.md")):
                try:
                    fm = brainlib.read_frontmatter(path)
                    pages.append((path, folder, references(fm, ("sources",)), references(fm, ("item", "items"))))
                except (ValueError, yaml.YAMLError):
                    pages.append((path, folder, set(), set()))
        lines, ok, count, problems = [], 0, 0, 0
        for name, batch in batches:
            n, errors = batch_report(brain, name, batch, pages)
            count += n
            problems += len(errors)
            ok += not errors
            lines.append(f"{name}: FAIL" if errors else f"{name}: ok ({n} pages, staging ok)")
            lines.extend("  " + e for e in errors)
        touched = wiki_edits.changed_during_pass(brain)
        problems += len(touched)
        lines.extend(f"protected page changed during the pass: wiki/{page} (move the change to a proposal)" for page in touched)
        lines.append(f"wave: {ok}/{len(batches)} batches ok, {count} pages, {problems} problems")
        if len(lines) > args.max_lines:
            omitted = len(lines) - (args.max_lines - 2)
            lines = lines[:args.max_lines - 2] + [f"... {omitted - 1} more lines", lines[-1]]
        print("\n".join(lines))
        return int(bool(problems))
    except (OSError, ValueError, KeyError, yaml.YAMLError) as exc:
        print(f"wave: FAIL: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

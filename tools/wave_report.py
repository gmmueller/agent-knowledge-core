"""Check a completed ingest wave with one compact report.

Usage: wave_report.py --brain FOLDER --batches ingest/batches.yaml [--wave KEY]
"""
import argparse
import pathlib
import re
import subprocess
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib
import wiki_edits

CORRUPTION = re.compile(r"[A-Za-z]\?s\b|\d\?\d| \? ")
LIBRARY = re.compile(r"^library/[^/]+/")
PAGE_DIRS = ("sources", "examples")  # topic briefs write `page: example` items to wiki/examples/


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


def references(fm):
    result = set()
    for key in ("sources", "item", "items"):
        values = fm.get(key) or []
        if not isinstance(values, list):
            values = [values]
        for value in values:
            if isinstance(value, dict):
                value = value.get("raw") or value.get("item") or value.get("id", "")
            result.add(normalized(value))
    return result


def batch_report(brain, name, batch, pages):
    problems, selected = [], set()
    for item in batch.get("items") or []:
        raw = item.get("raw") or item.get("item") or item.get("id", "")
        wanted = {normalized(raw)} | {normalized(item[key]) for key in ("item", "id") if item.get(key)}
        # An item's `id` is its page slug; Q&A digests share one id and need not cite every brief-reply thread.
        matches = {path for path, refs in pages
                   if path.stem == item.get("id") or any(same(w, r) for w in wanted for r in refs)}
        selected.update(matches)
        if not matches:
            problems.append(f"missing: {raw}")
    staging = brain / "ingest" / "staging" / f"{name}.yaml"
    files = [staging, *sorted(selected)]
    try:
        data = yaml.safe_load(staging.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected a YAML mapping")
    except (OSError, ValueError, yaml.YAMLError) as exc:
        problems.append(f"staging: {str(exc).splitlines()[0]}")
    if files:
        result = subprocess.run([sys.executable, "-X", "utf8", "-I", str(pathlib.Path(__file__).with_name("check_wiki.py")),
                                 "--brain", str(brain), *map(str, files)], capture_output=True)
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        if result.returncode or not re.search(r"^ok:", output, re.M):
            problems.extend(output.splitlines()[:5] or ["check_wiki: no ok: result"])
    for path in files:
        if not path.is_file():
            continue
        hits = [f"{path.relative_to(brain).as_posix()}:{i}: possible corruption"
                for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                if "http" not in line and CORRUPTION.search(line)]
        problems.extend(hits[:5])
    return len(selected), problems


def main(argv=None):
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
        for path in sorted(p for d in PAGE_DIRS for p in (brain / "wiki" / d).rglob("*.md")):
            try:
                pages.append((path, references(brainlib.read_frontmatter(path))))
            except (ValueError, yaml.YAMLError):
                pages.append((path, set()))
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

"""Detect human wiki edits: --brain <folder> status | begin | record [--init] | accept <page>... | propose <page> --from <file> | proposals.

Agent pass: `begin` before dispatching workers (it lists the human-edited pages they must not touch), then the
pass ends with `record`, which build_wiki_index.py runs at its end: agent changes join the baseline, and the pages
that were human-edited at `begin` stay protected until the user runs `accept`.
"""
import argparse
import datetime as dt
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib
import content_hashes as hashes


def manifest(brain):
    return brain / "wiki" / ".agent-baseline.json"


def snapshot(brain):
    return {p.relative_to(brain / "wiki").as_posix(): hashes.digest(p) for p in brainlib.wiki_pages(brain)}


def status(brain):
    return hashes.differences(hashes.load(manifest(brain)) or {}, snapshot(brain))


def pass_file(brain):
    return brain / "wiki" / ".agent-pass.json"


def begin(brain):
    """Start an agent pass: remember which pages are human-edited right now, so record() protects only those."""
    if hashes.load(manifest(brain)) is None:
        raise ValueError("baseline missing: use record --init first")
    protected = sorted(status(brain))
    hashes.save(pass_file(brain), {"started": dt.datetime.now().isoformat(timespec="seconds"), "protected": protected})
    return protected


def protected_pages(brain):
    """Pages agents must not write: those human-edited at the open pass's start, or every difference without a pass."""
    if hashes.load(manifest(brain)) is None:
        return set()
    open_pass = hashes.load(pass_file(brain))
    if open_pass is not None:
        return set(open_pass.get("protected") or []) & set(status(brain))
    return set(status(brain))


def record(brain, *, init=False, written=None):
    """Update the baseline after an agent pass.

    With an open pass (begin), every change is the agents' except the pages that were human-edited when the
    pass began; those stay protected and the pass is closed. Without a pass, every difference is protected
    unless the caller names the exact content it wrote (written), so a human edit is never absorbed silently.
    """
    path = manifest(brain)
    with hashes.locked(path):
        before = hashes.load(path)
        if before is None and not init:
            print("wiki baseline missing: run wiki_edits.py --brain <brain> record --init")
            return 0
        current = snapshot(brain)
        open_pass = None if init else hashes.load(pass_file(brain))
        differences = set() if init else set(hashes.differences(before, current))
        if init:
            blocked = set()
        elif open_pass is not None:
            blocked = differences & set(open_pass.get("protected") or [])
        else:
            blocked = {name for name in differences
                       if name not in (written or {}) or current.get(name) != written[name]}
        result = dict(before or {})
        for name in (result.keys() | current.keys()) - blocked:
            if name in current:
                result[name] = current[name]
            else:
                result.pop(name, None)
        hashes.save(path, result)
        if open_pass is not None:
            pass_file(brain).unlink(missing_ok=True)
    print(f"wiki baseline recorded; left {len(blocked)} human-edited pages alone")
    return len(blocked)


def page_name(brain, value):
    path = pathlib.Path(value)
    if not path.is_absolute():
        path = brain / path if path.parts and path.parts[0] == "wiki" else brain / "wiki" / path
    if not path.suffix:
        path = path.with_suffix(".md")
    root = (brain / "wiki").resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or resolved.suffix != ".md" or any(
            part.startswith(".") or part in ("notes", "library") for part in resolved.relative_to(root).parts):
        raise ValueError("page must be a Markdown file inside wiki/")
    return resolved.relative_to(root).as_posix()


def accept(brain, names=None):
    path = manifest(brain)
    with hashes.locked(path):
        before = hashes.load(path)
        if before is None:
            raise ValueError("baseline missing: use record --init first")
        current = snapshot(brain)
        selected = set(hashes.differences(before, current)) if names is None else {page_name(brain, n) for n in names}
        for name in selected:
            if name in current:
                before[name] = current[name]
            else:
                before.pop(name, None)
        hashes.save(path, before)
    return len(selected)


def proposals(brain):
    return sorted((brain / "ingest" / "proposals").glob("*.md"))


def propose(brain, page, source, why="Agent proposes an update; human review required."):
    name = page_name(brain, page)
    slug = re.sub(r"[^a-z0-9-]+", "-", pathlib.Path(name).stem.lower()).strip("-") or "page"
    out = brain / "ingest" / "proposals" / f"{slug}.md"
    if out.exists():
        raise FileExistsError(f"proposal already exists; review it first: {out}")
    brainlib.write_text(out, f"# Proposed wiki change\n\nDate: {dt.date.today().isoformat()}\nPage: wiki/{name}\nWhy: {why}\n\n---\n\n" + source.read_text(encoding="utf-8"))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(ap)
    commands = ap.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("begin", help="start an agent pass: protect the pages that are human-edited now")
    rec = commands.add_parser("record")
    rec.add_argument("--init", action="store_true")
    acc = commands.add_parser("accept")
    acc.add_argument("pages", nargs="*")
    acc.add_argument("--all", action="store_true")
    prop = commands.add_parser("propose")
    prop.add_argument("page")
    prop.add_argument("--from", dest="source", type=pathlib.Path, required=True)
    prop.add_argument("--why", default="Agent proposes an update; human review required.")
    commands.add_parser("proposals")
    a = ap.parse_args()
    brain = brainlib.brain_dir(a.brain)
    try:
        if a.command == "status":
            changes = status(brain)
            for name, kind in changes.items():
                print(f"{kind}: wiki/{name}")
            print(f"{len(changes)} human-edited pages")
            return int(bool(changes))
        if a.command == "begin":
            protected = begin(brain)
            for name in protected:
                print(f"protected: wiki/{name}")
            print(f"agent pass started; {len(protected)} human-edited pages are off limits (propose changes instead)")
        elif a.command == "record":
            record(brain, init=a.init)
        elif a.command == "accept":
            if bool(a.pages) == a.all:
                ap.error("accept requires pages or --all")
            print(f"accepted {accept(brain, None if a.all else a.pages)} pages")
        elif a.command == "propose":
            print(propose(brain, a.page, a.source, a.why))
        else:
            for path in proposals(brain):
                print(path.relative_to(brain).as_posix())
    except (ValueError, OSError) as exc:
        ap.exit(2, str(exc) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

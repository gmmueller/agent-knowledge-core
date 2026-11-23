"""Detect human wiki edits and record verified agent writes.

Use `begin` before dispatching workers and `mark-written` to register their intended output.
`record` (also called by build_wiki_index.py) closes the pass and leaves undeclared changes protected.
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
    return {p.relative_to(brain / "wiki").as_posix(): hashes.file_hashes(p) for p in brainlib.wiki_pages(brain)}


def status(brain, *, current=None):
    if current is None:
        current = snapshot(brain)
    return hashes.differences(hashes.load(manifest(brain)) or {}, current)


def pass_file(brain):
    return brain / "wiki" / ".agent-pass.json"


def begin(brain):
    """Start an agent pass and remember the current contents of already protected pages."""
    path = manifest(brain)
    with hashes.locked(path):
        baseline = hashes.load(path)
        if baseline is None:
            raise ValueError("baseline missing: use record --init first")
        if pass_file(brain).exists():
            raise ValueError("an agent pass is already open. Finish it before starting another.")
        current = snapshot(brain)
        protected = sorted(hashes.differences(baseline, current))
        hashes.save(pass_file(brain), {"started": dt.datetime.now().isoformat(timespec="seconds"), "protected": protected,
                                       "at_begin": {page: current[page].digest if page in current else None
                                                    for page in protected}})
    return protected


def changed_during_pass(brain, *, current=None):
    """Protected pages that differ from the open pass's saved hashes."""
    open_pass = hashes.load(pass_file(brain))
    if not open_pass or not open_pass.get("at_begin"):
        return []
    if current is None:
        current = snapshot(brain)
    return sorted(page for page, digest in open_pass["at_begin"].items()
                  if not hashes.matches(current.get(page), digest))


def unrecordable(before, current, open_pass, written=None):
    """Differences without matching agent output, or protected at the start of the pass."""
    protected = set(open_pass.get("protected") or [])
    expected = {**open_pass.get("written", {}), **(written or {})}
    return {name for name in hashes.differences(before, current)
            if name in protected or name not in expected or not hashes.matches(current.get(name), expected[name])}


def protected_pages(brain, *, current=None):
    """Pages agents must not write, including differences without matching agent output."""
    before = hashes.load(manifest(brain))
    if before is None:
        return set()
    if current is None:
        current = snapshot(brain)
    open_pass = hashes.load(pass_file(brain)) or {}
    return set(open_pass.get("protected") or []) | unrecordable(before, current, open_pass)


def register_writes(brain, written, *, require_pass=False):
    """Register intended content for an open pass without re-reading agent output from disk."""
    if not written:
        return
    with hashes.locked(manifest(brain)):
        path = pass_file(brain)
        open_pass = hashes.load(path)
        if open_pass is None:
            if require_pass:
                raise ValueError("no agent pass is open")
            return
        protected = sorted(written.keys() & set(open_pass.get("protected") or []))
        if protected:
            raise ValueError(f"cannot mark a page protected at the start of the pass: wiki/{protected[0]}")
        open_pass.setdefault("written", {}).update(written)
        hashes.save(path, open_pass)


def ensure_protected_unchanged(brain, *, current=None):
    touched = changed_during_pass(brain, current=current)
    if touched:
        pages = "\n".join(f"  wiki/{page}" for page in touched)
        raise ValueError(f"Agent pass remains open. Protected pages changed:\n{pages}\n"
                         "For agent changes, save the new version with `wiki_edits.py propose <page> --from <file>` "
                         "and restore the pre-pass page.\n"
                         "For owner changes, run `wiki_edits.py accept <page>` with each affected page named.\n"
                         "Then retry the index rebuild or `wiki_edits.py record`.")


def record(brain, *, init=False, written=None):
    """Close the pass and update the baseline for exact, declared agent writes."""
    path = manifest(brain)
    with hashes.locked(path):
        before = hashes.load(path)
        current = snapshot(brain)
        open_pass = hashes.load(pass_file(brain))
        if open_pass is not None:
            ensure_protected_unchanged(brain, current=current)
            if init:
                raise ValueError("finish the open agent pass before running record --init")
        if before is None and not init:
            print("wiki baseline missing: run wiki_edits.py --brain <brain> record --init")
            return 0
        blocked = set() if init else unrecordable(before, current, open_pass or {}, written)
        result = dict(before or {})
        for name in (result.keys() | current.keys()) - blocked:
            if name in current:
                result[name] = current[name].digest
            else:
                result.pop(name, None)
        hashes.save(path, result)
        if open_pass is not None:
            pass_file(brain).unlink(missing_ok=True)
    print(f"wiki baseline recorded; left {len(blocked)} human-edited pages alone")
    for name in sorted(blocked):
        print(f"left unrecorded: wiki/{name}")
    if blocked:
        print("Review unrecorded changes with `wiki_edits.py status` and use `wiki_edits.py accept <page>` to acknowledge them.")
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
        open_pass = hashes.load(pass_file(brain))
        if open_pass is not None and names is None:
            raise ValueError("name each page to accept while an agent pass is open")
        current = snapshot(brain)
        selected = set(hashes.differences(before, current)) if names is None else {page_name(brain, n) for n in names}
        for name in selected:
            if name in current:
                before[name] = current[name].digest
            else:
                before.pop(name, None)
        hashes.save(path, before)
        if open_pass is not None:
            at_begin = open_pass.get("at_begin", {})
            for name in selected & at_begin.keys():
                at_begin[name] = current[name].digest if name in current else None
            hashes.save(pass_file(brain), open_pass)
    return len(selected)


def proposals(brain):
    return sorted((brain / "ingest" / "proposals").rglob("*.md"))


def propose(brain, page, source, why="Agent proposes an update; human review required."):
    name = page_name(brain, page)
    root = brain / "ingest" / "proposals"
    out = root / "wiki" / name
    slug = re.sub(r"[^a-z0-9-]+", "-", pathlib.Path(name).stem.lower()).strip("-") or "page"
    legacy = root / f"{slug}.md"
    if legacy.is_file() and f"Page: wiki/{name}" in legacy.read_text(encoding="utf-8").splitlines()[:5]:
        raise FileExistsError(f"proposal already exists; review it first: {legacy}")
    content = source.read_text(encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as proposal:
        proposal.write(f"# Proposed wiki change\n\nDate: {dt.date.today().isoformat()}\nPage: wiki/{name}\nWhy: {why}\n\n---\n\n" + content)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(ap)
    commands = ap.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("begin", help="start an agent pass: protect the pages that are human-edited now")
    rec = commands.add_parser("record")
    rec.add_argument("--init", action="store_true")
    mark = commands.add_parser("mark-written", help="register an agent's intended output from a separate draft")
    mark.add_argument("page")
    output = mark.add_mutually_exclusive_group(required=True)
    output.add_argument("--from", dest="draft", type=pathlib.Path)
    output.add_argument("--deleted", action="store_true")
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
            current = snapshot(brain)
            changes = status(brain, current=current)
            is_open = pass_file(brain).exists()
            touched = changed_during_pass(brain, current=current)
            protected = protected_pages(brain, current=current)
            for name, kind in changes.items():
                print(f"{kind}: wiki/{name}")
            print(f"{len(changes)} pages differ from the baseline")
            print(f"agent pass: {'open' if is_open else 'closed'} ({len(protected)} protected pages)")
            if is_open:
                for name in sorted(protected):
                    print(f"protected: wiki/{name}")
            for name in touched:
                print(f"protected page changed during pass: wiki/{name}")
            return int(bool(changes or touched))
        if a.command == "begin":
            protected = begin(brain)
            for name in protected:
                print(f"protected: wiki/{name}")
            print(f"agent pass started; {len(protected)} human-edited pages are off limits (propose changes instead)")
        elif a.command == "record":
            record(brain, init=a.init)
        elif a.command == "mark-written":
            name = page_name(brain, a.page)
            path = brain / "wiki" / name
            if a.draft is not None and path.exists() and a.draft.samefile(path):
                raise ValueError("use a separate draft containing the intended output")
            expected = None if a.deleted else hashes.digest(a.draft)
            current = hashes.file_hashes(path) if path.is_file() else None
            if not hashes.matches(current, expected):
                raise ValueError(f"wiki/{name} differs from the intended output")
            register_writes(brain, {name: expected}, require_pass=True)
            print(f"marked agent output: wiki/{name}")
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

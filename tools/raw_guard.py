"""Hash captured raw text: --brain <brain> | --workspace <workspace> record [--init] | check."""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib
import content_hashes as hashes


def manifest(raw):
    return (raw if (raw.parent / "brain.md").exists() else raw.parent) / ".capture-hashes.json"


def snapshot(raw):
    return {p.relative_to(raw).as_posix(): hashes.file_hashes(p) for p in brainlib.iter_files(raw)}


def check(raw):
    """Files changed or deleted since capture. Files never recorded are not changes (see unrecorded)."""
    before = hashes.load(manifest(raw))
    if before is None:
        return {}
    return {name: kind for name, kind in hashes.differences(before, snapshot(raw)).items() if kind != "added"}


def unrecorded(raw):
    """Files with no capture hash yet (captured before the guard was adopted, or by a tool that doesn't record)."""
    before = hashes.load(manifest(raw)) or {}
    return sorted(p.relative_to(raw).as_posix() for p in brainlib.iter_files(raw)
                  if p.relative_to(raw).as_posix() not in before)


def has_manifest(raw):
    return manifest(raw).exists()


def record(raw, *, init=False):
    """Record capture hashes. Without --init: add files that have no hash yet, but refuse if a recorded file
    changed or disappeared (re-crawl instead). With --init: record everything as it is now."""
    path = manifest(raw)
    with hashes.locked(path):
        before = hashes.load(path)
        current = snapshot(raw)
        if before is None and current and not init:
            raise ValueError("existing raw data needs record --init; re-crawl changed files")
        if before is not None and not init and any(
                kind != "added" for kind in hashes.differences(before, current).values()):
            raise ValueError("raw changed after capture: re-crawl instead of editing (or explicitly record --init)")
        hashes.save(path, {name: content.digest for name, content in current.items()})


def record_capture(path):
    """Called only after a capture writes a file; update exactly that file, never its neighbours."""
    path = path.resolve()
    raw = next((p for p in path.parents if p.name == "raw"), None)
    if raw is None:
        raise ValueError(f"capture output must be inside raw/: {path}")
    target = manifest(raw)
    with hashes.locked(target):
        files = hashes.load(target) or {}
        files[path.relative_to(raw).as_posix()] = hashes.digest(path)
        hashes.save(target, files)


def cited_raw_dirs(brain):
    """Only publishers named by this brain's citations/frontmatter/selection, not every publisher."""
    import re
    publishers = set()
    paths = [brain / "brain.md", brain / "selection.yaml", *brainlib.wiki_pages(brain)]
    for path in paths:
        if path.exists():
            publishers.update(re.findall(r"library/([a-zA-Z0-9_-]+)/raw/", path.read_text(encoding="utf-8")))
    return [brainlib.library_dir(brainlib.workspace(brain)) / p / "raw" for p in sorted(publishers)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    scope = ap.add_mutually_exclusive_group(required=True)
    scope.add_argument("--brain")
    scope.add_argument("--workspace")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    rec = sub.add_parser("record")
    rec.add_argument("--init", action="store_true")
    a = ap.parse_args()
    if a.brain:
        roots = [brainlib.brain_dir(a.brain) / "raw"]
    else:
        workspace = brainlib.workspace_dir(a.workspace)
        library = brainlib.library_dir(workspace)
        roots = {p for p in library.glob("*/raw") if p.is_dir()}
        if a.command == "check":
            roots.update(p.parent / "raw" for p in library.glob("*/.capture-hashes.json"))
            roots.update(p.parent / "raw" for p in workspace.glob("*/brain.md"))
        roots = sorted(roots)
    count = missing = 0
    try:
        for raw in roots:
            if a.command == "record":
                record(raw, init=a.init)
                print(f"recorded: {raw}")
            else:
                for name, kind in check(raw).items():
                    print(f"{kind}: {raw / name}")
                    count += 1
                missing += len(unrecorded(raw))
    except (ValueError, OSError) as exc:
        ap.exit(2, str(exc) + "\n")
    if a.command == "check":
        print(f"{count} raw files changed after capture")
        if missing:
            print(f"{missing} raw files have no capture hash yet (run record, or record --init once when adopting)")
    return int(bool(count))


if __name__ == "__main__":
    sys.exit(main())

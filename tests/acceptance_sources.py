"""Offline acceptance checks against a built brain; scratch copies are always removed.

Cached map rebuilds must retain existing CRLF bytes and curated source metadata.
"""
import argparse
import ast
import difflib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brainlib
from source_helpers import brain_path, cache_key, cdp, map_cache

TOOLS = Path(__file__).resolve().parent
RUN_OFFLINE = """import runpy, sys
def deny(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen'}:
        raise RuntimeError('offline acceptance blocked: ' + event)
sys.addaudithook(deny)
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""


def run(tool, *args):
    command = [sys.executable, "-I", "-B", "-c", RUN_OFFLINE, str(TOOLS / tool), *map(str, args)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    print(f"{tool} {' '.join(map(str, args))}: exit {result.returncode}")
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def without_capture(data):
    return re.sub(rb"(?m)^captured: [^\r\n]*", b"captured: <date>", data)


def main():
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("--map-cache", required=True, help="existing offline Kajabi map cache")
    ap.add_argument("--scrub-pattern", required=True, help="private-name expression supplied by the workspace")
    args = ap.parse_args()
    brain = brainlib.brain_dir(args.brain)
    assert brain_path(brain, "raw/lesson.md") == brain / "raw" / "lesson.md"
    assert brain_path(brain, "my-course/raw/lesson.md") == brain / "raw" / "lesson.md"
    try:
        brain_path(brain, "../outside.md")
    except ValueError:
        pass
    else:
        raise AssertionError("path traversal accepted")
    assert cdp({"cdp_port": 12345}) == "http://127.0.0.1:12345"
    assert cache_key("sample-id") == "sample-id"
    for key in ("../outside", "a/b", "a\\b", ".."):
        try:
            cache_key(key)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe cache key accepted")

    scratch = brainlib.secrets_dir(brain, "scratch")
    with tempfile.TemporaryDirectory(prefix="source-adapter-check-", dir=scratch) as temporary:
        test_brain = Path(temporary) / brain.name
        test_brain.mkdir()
        for name in ("brain.md", "crawl.yaml", "outline.yaml", "sources.yaml"):
            shutil.copy2(brain / name, test_brain / name)
        shutil.copy2(args.map_cache, map_cache(test_brain))
        run("kajabi_map.py", "--brain", test_brain, "--build-only")
        built = (test_brain / "outline.yaml").read_bytes()
        expected = (brain / "outline.yaml").read_bytes()
        if built != expected:
            print("".join(difflib.unified_diff(expected.decode("utf-8").splitlines(True), built.decode("utf-8").splitlines(True)))[:3000])
        assert built == expected, "outline bytes differ"
        assert (test_brain / "sources.yaml").read_bytes() == (brain / "sources.yaml").read_bytes(), "source bytes differ"
        print("CHECK 1 PASS: outline.yaml and sources.yaml byte-identical")

        shutil.copytree(brain / "raw", test_brain / "raw")
        for kind in ("wistia", "whisper", "pages"):
            shutil.copytree(brain / "media" / kind, test_brain / "media" / kind,
                            ignore=lambda folder, names: [name for name in names if Path(name).suffix not in {".json", ".md"}])
        attachments = test_brain / "media" / "attachments"
        attachments.mkdir()
        shutil.copy2(brain / "media" / "attachments" / "manifest.json", attachments / "manifest.json")
        config = brainlib.crawl_config(brain)
        multi = config.get("multi_speaker") or {}
        selected = {}
        for path in (test_brain / "raw").rglob("*.md"):
            front = brainlib.read_frontmatter(path)
            if "product" not in front:
                continue
            is_multi = front["product"] in multi.get("products", []) or front.get("source_id") in multi.get("lessons", [])
            kind = "multi-speaker" if is_multi else front.get("method")
            if kind in {"captions", "whisper", "page-text", "multi-speaker"}:
                selected.setdefault(kind, path)
        assert len(selected) == 4, f"missing representative raw files: {selected}"
        golden = {}
        for kind, path in selected.items():
            relative = path.relative_to(test_brain)
            committed = subprocess.run(["git", "-C", str(brain.parent), "show", f"HEAD:{brain.name}/{relative.as_posix()}"], capture_output=True)
            assert committed.returncode == 0, committed.stderr.decode("utf-8", "replace")
            golden[kind] = committed.stdout
            path.unlink()
        print(run("build_raw.py", "--brain", test_brain).strip())
        for kind, path in selected.items():
            assert without_capture(path.read_bytes()) == without_capture(golden[kind]), f"{kind} differs: {path.name}"
            print(f"CHECK 2 {kind} PASS: {path.name} matches committed raw except captured")

        for name in ("wistia_to_raw.py", "whisper_transcribe.py", "kajabi_lesson_assets.py"):
            run(name, "--help")
        caption_front = brainlib.read_frontmatter(selected["captions"])
        output = run("wistia_to_raw.py", "--brain", test_brain, "--offline", "--media-id", caption_front["video"].split(":", 1)[1],
                     "--source-id", "offline-check", "--title", "Offline check", "--module", "Offline check",
                     "--url", "https://example.com/lesson", "--out", "raw/offline-check.md")
        print(output.strip())
        print(run("whisper_transcribe.py", "--brain", test_brain, "--all-uncaptioned", "--dry-run").strip())
        print(run("kajabi_lesson_assets.py", "--brain", test_brain, "--all", "--dry-run").strip())
        print("CHECK 3 PASS: help and dry paths; network and child-process audit guard active")

    pattern = re.compile(args.scrub_pattern, re.I)
    hits = []
    for path in TOOLS.parent.rglob("*"):
        if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts or path.name == "LICENSE":
            continue
        text = path.read_text(encoding="utf-8")
        if pattern.search(text):
            hits.append(str(path.relative_to(TOOLS.parent)))
    assert not hits, f"scrub matches: {hits}"
    for path in TOOLS.glob("*.py"):
        if path.name in {"brainlib.py", "test_source_adapters.py"}:
            continue
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    print("CHECK 4 PASS: framework scrub; Python parses; temporary copy removed")


if __name__ == "__main__":
    main()

"""Shared helpers for Agent Knowledge Core tools: locating a brain, reading its files and its config.

A **brain** is a folder holding `brain.md`, `sources.yaml`, `raw/`, `wiki/` and optionally `crawl.yaml`.
A **workspace** is the (private) folder that holds one or more brains; it also holds `.secrets/`
(browser profiles, caches) and is never published. Tools take `--brain <path-to-brain-folder>`.

Import from a tool with:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # python -I drops the script dir
    import brainlib
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import io
import os
import pathlib
import re
import shutil
import stat
import tempfile

import yaml

FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.S)


def brain_dir(path: str | pathlib.Path) -> pathlib.Path:
    """Resolve and validate a brain folder (must contain brain.md)."""
    p = pathlib.Path(path).expanduser().resolve()
    if not (p / "brain.md").exists():
        raise SystemExit(f"not a brain folder (no brain.md): {p}")
    return p


def add_brain_arg(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--brain", required=True, help="path to the brain folder (contains brain.md)")


def workspace(brain: pathlib.Path) -> pathlib.Path:
    """The folder that holds the brain (and .secrets/)."""
    return brain.parent


def workspace_dir(path: str | pathlib.Path) -> pathlib.Path:
    """Resolve and validate a workspace folder (holds brains and/or the shared library/)."""
    p = pathlib.Path(path).expanduser().resolve()
    if not p.is_dir() or not ((p / "library").is_dir() or any(p.glob("*/brain.md"))):
        raise SystemExit(f"not a workspace (no library/ and no brain folders): {p}")
    return p


def add_workspace_arg(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--workspace", required=True, help="path to the private workspace (holds library/ and the brains)")


def library_dir(ws: pathlib.Path) -> pathlib.Path:
    """<workspace>/library: shared expert sources for topic brains (docs/library.md)."""
    return ws / "library"


def secrets_dir(brain: pathlib.Path, *parts: str) -> pathlib.Path:
    """<workspace>/.secrets/<parts...>, created on demand. Never inside the brain, never committed."""
    return workspace_secrets(workspace(brain), *parts)


def workspace_secrets(ws: pathlib.Path, *parts: str) -> pathlib.Path:
    """<workspace>/.secrets/<parts...>, created on demand (for workspace-level tools such as the library ones)."""
    d = ws.joinpath(".secrets", *parts)
    d.mkdir(parents=True, exist_ok=True)
    return d


def split_frontmatter(text: str) -> tuple[dict, str]:
    m = FRONTMATTER.match(text)
    return ((yaml.safe_load(m.group(1)) or {}), text[m.end():]) if m else ({}, text)


def read_frontmatter(path: pathlib.Path) -> dict:
    return split_frontmatter(path.read_text(encoding="utf-8"))[0]


def load_yaml(path: pathlib.Path, default=None):
    if not path.exists():
        return default
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.stat().st_size else default


def crawl_config(brain: pathlib.Path) -> dict:
    """Optional <brain>/crawl.yaml: platform specifics (site, CDP port, products, whisper prompt, multi-speaker lists)."""
    return load_yaml(brain / "crawl.yaml", {}) or {}


def write_text(path: pathlib.Path, text: str) -> None:
    """UTF-8, LF line endings, parent folders created."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def file_lock(path: pathlib.Path):
    """Serialize read-modify-write operations on a shared file."""
    from filelock import SoftFileLock

    path.parent.mkdir(parents=True, exist_ok=True)
    return SoftFileLock(str(path) + ".lock", timeout=60)


@contextmanager
def staged_text(path: pathlib.Path, text: str):
    """Prepare a sibling file for atomic publication, then clean up on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = pathlib.Path(stream.name)
            stream.write(text)
        yield temporary
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def atomic_write(path: pathlib.Path, text: str) -> None:
    with staged_text(path, text) as temporary:
        temporary.replace(path)


def edit_yaml(path: pathlib.Path, edit) -> None:
    """Update YAML with its existing comments, ordering and quotes."""
    from ruamel.yaml import YAML

    with file_lock(path):
        parser = YAML()
        parser.preserve_quotes = True
        data = parser.load(path.read_text(encoding="utf-8")) if path.exists() else None
        data = {} if data is None else data
        if edit(data):
            buffer = io.StringIO()
            parser.dump(data, buffer)
            atomic_write(path, buffer.getvalue())


def executable(name: str) -> str:
    """Find an external program without depending on a shell or OS-specific suffix."""
    path = shutil.which(name)
    if not path:
        raise FileNotFoundError(f"{name} was not found; install it and add it to PATH")
    return path


def is_directory_link(path: pathlib.Path) -> bool:
    """Include Windows junctions on Python 3.11, where is_junction is unavailable."""
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) &
                                     getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def iter_files(root: pathlib.Path, *, exclude=()):
    """Walk real files only; never enter directory links or excluded top-level folders."""
    if not root.is_dir() or is_directory_link(root):
        return
    for directory, folders, files in os.walk(root, followlinks=False):
        base = pathlib.Path(directory)
        folders[:] = sorted(d for d in folders if not d.startswith(".")
                            and not (base == root and d in exclude)
                            and not is_directory_link(base / d))
        for name in sorted(files):
            path = base / name
            if not name.startswith(".") and not path.is_symlink():
                yield path


def wiki_pages(brain: pathlib.Path):
    return (p for p in iter_files(brain / "wiki", exclude=("notes", "library")) if p.suffix == ".md")

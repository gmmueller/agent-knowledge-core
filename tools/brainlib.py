"""Shared helpers for create-a-brain tools: locating a brain, reading its files and its config.

A **brain** is a folder holding `brain.md`, `sources.yaml`, `raw/`, `wiki/` and optionally `crawl.yaml`.
A **workspace** is the (private) folder that holds one or more brains; it also holds `.secrets/`
(browser profiles, caches) and is never published. Tools take `--brain <path-to-brain-folder>`.

Import from a tool with:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # python -I drops the script dir
    import brainlib
"""
from __future__ import annotations

import argparse
import pathlib
import re

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


def secrets_dir(brain: pathlib.Path, *parts: str) -> pathlib.Path:
    """<workspace>/.secrets/<parts...>, created on demand. Never inside the brain, never committed."""
    d = workspace(brain).joinpath(".secrets", *parts)
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

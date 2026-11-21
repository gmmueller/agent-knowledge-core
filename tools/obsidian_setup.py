"""Open each core in place as its own Obsidian vault; --brain <brain> or --workspace <ws> --all."""
import argparse
import copy
import json
import os
import pathlib
import subprocess
import sys
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib

NOTES_README = """# Your notes

This folder belongs to you. Add and edit your own notes here; they may link to wiki pages.
Agents must never create, edit or delete notes here. Wiki pages must not cite notes as sources.
The setup tool creates this starter once and never overwrites it.
"""
APP = {"userIgnoreFilters": ["ingest/", "media/", "state/", "library/"]}
GROUPS = [("sources", 0x6A9FB5), ("topics", 0x8FBCBB), ("principles", 0xA3BE8C),
          ("methods", 0xB48EAD), ("frameworks", 0xD08770), ("rules", 0xBF616A),
          ("glossary", 0xEBCB8B), ("debates", 0xAB7967), ("rubrics", 0x5E81AC),
          ("examples", 0x88C0D0), ("notes", 0xD8DEE9)]
GRAPH = {"search": '(path:"wiki/" OR path:"notes/") -path:"raw/" -path:"library/"',
         "hideUnresolved": True, "showAttachments": False,
         "colorGroups": [{"query": f'path:"{folder if folder == "notes" else "wiki/" + folder}/"',
                          "color": {"a": 1, "rgb": color}} for folder, color in GROUPS]}


def open_uri(brain):
    return "obsidian://open?path=" + urllib.parse.quote(str(brain.resolve()), safe="")


def merge_settings(current, defaults):
    result = copy.deepcopy(current)
    for key, value in defaults.items():
        if key not in result:
            result[key] = copy.deepcopy(value)
        elif key == "userIgnoreFilters" and isinstance(result[key], list):
            result[key] += [v for v in value if v not in result[key]]
        elif key == "colorGroups" and isinstance(result[key], list):
            existing = {v.get("query") for v in result[key] if isinstance(v, dict)}
            result[key] += [copy.deepcopy(v) for v in value if v["query"] not in existing]
    return result


def write_settings(path, defaults, reset=False):
    current = {} if reset or not path.exists() else json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(current, dict):
        raise ValueError(f"settings must be a JSON object: {path}")
    brainlib.write_text(path, json.dumps(merge_settings(current, defaults), indent=2, ensure_ascii=False) + "\n")
    print(f"settings: {path}")


def append_ignore(path, entries):
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    missing = [s for s in entries if s not in text.splitlines()]
    if missing:
        brainlib.write_text(path, text + ("\n" if text and not text.endswith("\n") else "") + "\n".join(missing) + "\n")
        print(f"gitignore: {path}: {', '.join(missing)}")


def link_library(brain):
    link = brain / "library"
    target = brainlib.library_dir(brainlib.workspace(brain)).resolve()
    if os.path.lexists(link):
        if not brainlib.is_directory_link(link):
            raise ValueError(f"refusing existing real library folder: {link}")
        if link.resolve() != target:
            raise ValueError(f"library link points elsewhere: {link}")
        if not target.is_dir():
            raise ValueError(f"shared library missing: {target}")
        print(f"library link already correct: {link}")
        return
    if not target.is_dir():
        raise ValueError(f"shared library missing: {target}")
    if os.name == "nt":
        try:
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        except (AttributeError, OSError):
            subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)], check=True,
                           capture_output=True, text=True)
    else:
        link.symlink_to(target, target_is_directory=True)
    print(f"library link: {link} -> {target}")


def setup(brain, *, reset=False):
    if brainlib.read_frontmatter(brain / "brain.md").get("kind") == "topic":
        link_library(brain)
    write_settings(brain / ".obsidian" / "app.json", APP, reset)
    write_settings(brain / ".obsidian" / "graph.json", GRAPH, reset)
    append_ignore(brain / ".gitignore", ["/library", "/.obsidian/workspace*.json"])
    notes = brain / "notes" / "README.md"
    if not notes.exists():
        brainlib.write_text(notes, NOTES_README)
        print(f"created notes starter: {notes}")
    print(f"open: {open_uri(brain)}")


def hub(workspace, brains, *, gitignore=False):
    folder = workspace / ".cores-hub"
    lines = ["# Knowledge cores", "", "Each core is independent. They are listed together only for convenience; their subjects and sources are not related.", ""]
    for brain in brains:
        fm = brainlib.read_frontmatter(brain / "brain.md")
        name = str(fm.get("display_name") or fm.get("name") or brain.name).replace("\n", " ")
        name = name.replace("[", "\\[").replace("]", "\\]")
        description = str((fm.get("skill") or {}).get("short_description") or "").replace("\n", " ")
        # Prevent metadata from introducing cross-vault wikilinks into the navigation vault.
        description = description.replace("[", "\\[").replace("]", "\\]")
        lines.append(f"- [{name}]({open_uri(brain)}): {description}")
    brainlib.write_text(folder / "Knowledge cores.md", "\n".join(lines) + "\n")
    write_settings(folder / ".obsidian" / "app.json", {})
    if gitignore:
        append_ignore(workspace / ".gitignore", ["/.cores-hub/"])
    else:
        print("reminder: add /.cores-hub/ to the workspace .gitignore, or pass --gitignore-hub")
    print(f"hub: {folder / 'Knowledge cores.md'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    scope = ap.add_mutually_exclusive_group(required=True)
    scope.add_argument("--brain")
    scope.add_argument("--workspace")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--gitignore-hub", action="store_true")
    a = ap.parse_args()
    if bool(a.workspace) != a.all:
        ap.error("use --brain <brain> or --workspace <workspace> --all")
    if a.gitignore_hub and not a.all:
        ap.error("--gitignore-hub requires --all")
    try:
        workspace = brainlib.workspace_dir(a.workspace) if a.all else None
        brains = [brainlib.brain_dir(p.parent) for p in sorted(workspace.glob("*/brain.md"))] if a.all else [brainlib.brain_dir(a.brain)]
        for brain in brains:
            setup(brain, reset=a.reset)
        if a.all:
            hub(workspace, brains, gitignore=a.gitignore_hub)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        ap.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    main()

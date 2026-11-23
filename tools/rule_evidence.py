"""Shared topic-rule evidence and status calculation."""
import pathlib
import sys
from functools import cache
from typing import NamedTuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib


@cache
def raw_item(workspace, raw):
    """Resolve a raw citation to its library item, including chapters of one book."""
    if not raw:
        return ""
    rel = str(raw).removesuffix(".md") + ".md"
    path = workspace / rel
    front = brainlib.read_frontmatter(path) if path.is_file() else {}
    if front.get("publisher") and front.get("source_id"):
        return f"{front['publisher']}/{front['source_id']}"
    return rel


class Assessment(NamedTuple):
    status: str | None
    experts: set[str]
    voices: set[str]
    opposing: set[str]


def assess(settings, evidence, page):
    """Count supporting voices or items and flag listed experts who oppose."""
    experts = set(settings.get("experts") or [])
    expert_aliases = settings.get("expert_aliases") or {}
    voice_aliases = settings.get("voice_aliases") or {}
    hosts = set(settings.get("hosts") or [])
    backing, voices, items, opposing = set(), set(), set(), set()
    for row in evidence:
        speaker = row.get("speaker")
        expert = expert_aliases.get(speaker, speaker)
        if speaker in hosts or expert in hosts:
            continue
        stance = row.get("stance", "supports")
        if stance == "opposes" and expert in experts:
            opposing.add(expert)
        if stance != "supports":
            continue
        if expert in experts:
            backing.add(expert)
        if expert:
            voices.add(voice_aliases.get(expert, expert))
        if row.get("item"):
            items.add(row["item"])
    publishers = {item.removeprefix("library/").split("/", 1)[0] for item in items}
    independent = (len(voices) >= 2 if settings.get("rule_status") == "voices"
                   else len(publishers) >= 2 or len(items) >= 3)
    old = page.get("status")
    if page.get("status_locked") is True or old == "contested":
        status = old
    elif len(backing) >= 2 and not opposing:
        status = "consensus"
    else:
        status = "active" if independent else "bench"
    return Assessment(status, backing, voices, opposing)


def report_opposition(slug, opposing):
    if opposing:
        print(f"{slug}: contested candidate (opposition from {', '.join(sorted(opposing))})")

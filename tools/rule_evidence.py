"""Shared topic-rule evidence and status calculation."""
import pathlib
import sys
from functools import cache
from typing import NamedTuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib
from reference_sources import enabled as reference_mode


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
    superseded_only: bool = False


def assess(settings, evidence, page, references=None):
    """Count evidence using the brain's expert or reference model."""
    reference = reference_mode(settings)
    experts = set(settings.get("experts") or [])
    expert_aliases = settings.get("expert_aliases") or {}
    voice_aliases = settings.get("voice_aliases") or {}
    hosts = set(settings.get("hosts") or [])
    backing, voices, items, opposing = set(), set(), set(), set()
    authoritative, contradictions = set(), set()
    superseded, current = False, False
    for row in evidence:
        speaker = row.get("speaker")
        expert = expert_aliases.get(speaker, speaker)
        stance = row.get("stance", "supports")
        if reference:
            source = references.evidence(row) if references is not None else row
            if source.get("superseded"):
                superseded |= stance == "supports"
                continue
            current |= stance == "supports"
            identity = source.get("identity") or row.get("item")
            if identity and source.get("authority") in {"official", "primary"}:
                if stance == "supports":
                    authoritative.add(identity)
                elif stance == "opposes":
                    contradictions.add(identity)
        if speaker in hosts or expert in hosts:
            continue
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
    if page.get("status_locked") is True or (not reference and old == "contested"):
        status = old
    elif reference and authoritative and contradictions and len(authoritative | contradictions) >= 2:
        status = "contested"
    elif len(backing) >= 2 and not opposing and not contradictions:
        status = "consensus"
    elif reference:
        status = "active" if authoritative else "bench"
    else:
        status = "active" if independent else "bench"
    return Assessment(status, backing, voices, opposing | contradictions, superseded and not current)


def report_opposition(slug, opposing):
    if opposing:
        print(f"{slug}: contested candidate (opposition from {', '.join(sorted(opposing))})")

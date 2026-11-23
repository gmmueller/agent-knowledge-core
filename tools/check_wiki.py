"""Check brain cards, wiki pages and ingest staging against captured sources.

Usage: python -I tools/check_wiki.py --brain <brain-folder> [files ...]
  With no files: brain.md, every wiki content page and ingest/staging/*.yaml.

Citation forms (paths relative to the brain folder, `.md` optional):
  ([[raw/main/m02-x/l01-y]] @ 1:07)       transcript block timestamp
  ([[raw/_attachments/z]] @ p. 3)         PDF page
  ([[raw/main/m01-x/l04-y]] @ page text)   lesson page text (or a text-only lesson)
  ([[raw/community/2026-10/x]] @ post)   a Skool thread's opening post
  ([[raw/community/2026-10/x]] @ c:9d9bf4b9)  one comment in a Skool thread (its `c:<id8>` anchor)
Library paths resolve from the workspace root; @ ¶N addresses web blocks.
For `post` / `c:` cites the quote's speaker (or the persona's default_speaker when unnamed) must be the
author of that post or comment, so a member's words can't pass as the expert's.
Persona quotes may omit the brain's default_speaker; topic quotes always name a speaker.
A quote must appear verbatim (whitespace and curly quotes normalised, case-sensitive) in the cited block.
Timestamp and PDF citations can include the previous and next blocks. Exit code 1 if anything fails.
"""
import pathlib
import datetime as dt
import argparse
import functools
import itertools
import re
import sys
from urllib.parse import unquote

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # python -I drops the script dir
import brainlib

TIMESTAMP = re.compile(r"\d+:(?:[0-5]\d:)?[0-5]\d")
CITE = re.compile(r"\[\[((?:raw/|library/)[^\[\]|#]+?)(?:\|[^\]]*)?\]\]\s*@\s*"
                  rf"({TIMESTAMP.pattern}|p\.\s*\d+|¶\d+|page text|post|c:[0-9a-f]{{8}}|\d+(?:\.\d+)?s)"
                  r"(?![\w:]|\.\d)")
RAW_LINK = re.compile(r"\[\[(?:raw/|library/)")
WIKI_LINK = re.compile(r"\[\[([^\[\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
MARKDOWN_LINK = re.compile(
    r"""\[[^\[\]\n]+\]\(\s*(?:<([^>\n]*)>|((?:\\[()]|\([^()\n]*\)|[^\s()])+))"""
    r"""\s*(?:(?:"[^"\n]*"|'[^'\n]*')\s*)?\)"""
)
INLINE_CODE = re.compile(r"`[^`\n]+`")
URL = re.compile(r"https?://\S+")
CORRUPTION = re.compile(r"[A-Za-z]\?(?:s|t|re|ve|ll|m|d)\b|\d\?\d|\w \? \w|[\"”\]] \? [\(\[\w]")
EXAMPLE = re.compile(r"^library/[^/]+/examples/[^/]+$")  # measured example facts (docs/library.md); cited @ <seconds>s
QUOTE_MARKER = re.compile(r'^\s*(?:>\s*|[-*+]\s+)["“]')
DASH = r"(?:[—–]|-{1,2})"
# Requiring the dash lets the quote contain inner quotation marks.
QUOTE_LINE = re.compile(rf'''^\s*(?:>\s*|[-*+]\s+)["“](.+?)["”]\s*{DASH}\s*([^"“”\[]*)$''')
QUOTE_BULLET = re.compile(r'''^\s*[-*+]\s+["“].+?["”]\s*$''')
INLINE_QUOTE = re.compile(rf'''["“](.+?)["”](?:\s*{DASH}\s*([^"“”\[]*))?\s*$''')
TS_BLOCK = re.compile(rf"^\*\*\[({TIMESTAMP.pattern}|¶\d+)\]\*\*\s?(.*)$")
PAGE_BLOCK = re.compile(r"^\*\*\[p\. (\d+)\]\*\*\s*$")
THREAD_HEAD = re.compile(r"^((?:> )*)\*\*(.+?)\*\* \(@[^)]*\)(?: · \*\*\w+\*\*)? · [\d-]+ [\d:]+ · c:([0-9a-f]{8})\s*$")
POST_HEAD = re.compile(r"^\*\*(.+?)\*\* \(@[^)]*\) · [\d-]+ [\d:]+\s*$")
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
TYPES = {"source", "topic", "principle", "method", "framework", "rule", "glossary", "example", "rubric", "tool", "debate"}
STANCES = {"supports", "nuances", "opposes"}
CLAIM_SECTIONS = {"key claims", "key points", "why", "when it applies"}
RULE_TABLE_HEADER = re.compile(r"^\|\s*(?:#\s*\|\s*)?Rule\s*\|", re.I)
TABLE_DIVIDER = re.compile(r"\|(?:\s*:?-+:?\s*\|)+")
WARNING = "warning: "  # prefix for findings that print but don't fail the check


@functools.lru_cache(maxsize=None)
def frontmatter(path):
    m = re.match(r"^---\n(.*?)\n---(?:\n|$)", path.read_text(encoding="utf-8"), re.S)
    return yaml.safe_load(m.group(1)) or {} if m else {}


def topic(brain):
    return frontmatter(brain / "brain.md").get("kind") == "topic"


def display_path(brain, path):
    root = brainlib.workspace(brain)
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)


def check_schema(brain, fm, body, where, errors):
    # brain.md may set its own `evidence_types:` (e.g. rulebook, expert, vendor); "inference" is always allowed
    evidence = set(frontmatter(brain / "brain.md").get("evidence_types") or
                   {"research", "synthesis", "official", "practitioner", "example"}) | {"inference"}
    for key, values in (("evidence", evidence),
                        ("freshness", {"evergreen", "platform", "tool-version", "dated"})):
        if key in fm and fm[key] not in values:
            errors.append(f"{where}: {key} must be one of {sorted(values)}")
    if fm.get("type") == "tool":
        for key in ("reviewed", "recheck_by"):
            value = fm.get(key)
            try:
                if isinstance(value, dt.datetime):
                    raise ValueError
                dt.date.fromisoformat(str(value))
            except ValueError:
                errors.append(f"{where}: tool requires '{key}' date (YYYY-MM-DD)")
    if fm.get("type") == "rule":
        statuses = {"active", "bench", "consensus", "contested"} if topic(brain) else {"active", "bench"}
        if fm.get("status") not in statuses:
            errors.append(f"{where}: rule needs status {'|'.join(sorted(statuses))}")
        if fm.get("status") == "contested":
            targets = re.findall(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]", body)
            debates = [p for p in brainlib.wiki_pages(brain) if frontmatter(p).get("type") == "debate"]
            if not any(t.removesuffix('.md') in (p.stem, p.relative_to(brain).with_suffix('').as_posix(), p.relative_to(brain / 'wiki').with_suffix('').as_posix()) for t in targets for p in debates):
                errors.append(f"{where}: contested rule requires a link to a debate page")


def norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("…", "...")
    s = re.sub(r"\*\*|__", "", s)
    s = re.sub(r"\\([()\[\]*_#.!+-])", r"\1", s)  # markdown escapes (Skool exports write \( \) \*)
    return re.sub(r"\s+", " ", s).strip()


_raw_cache: dict[str, dict | None] = {}


def raw_index(brain: pathlib.Path, rel: str) -> dict | None:
    """Index raw text; block_speakers parallels blocks, keeping requote's pair format."""
    key = f"{brain}/{rel}" if rel.endswith(".md") else f"{brain}/{rel}.md"
    if key in _raw_cache:
        return _raw_cache[key]
    parts = pathlib.PurePosixPath(rel).parts
    if parts[:1] == ("raw",):
        root, relative = brain / "raw", parts[1:]
    elif len(parts) >= 4 and parts[0] == "library" and parts[2] == "raw":
        root, relative = brainlib.workspace(brain).joinpath(*parts[:3]), parts[3:]
    else:
        return None
    if not relative or ".." in parts or "\\" in rel or ":" in rel:
        return None
    path = root.joinpath(*relative)
    path = path if path.suffix == ".md" else path.with_name(path.name + ".md")
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        _raw_cache[key] = None
        return None
    text = path.read_text(encoding="utf-8")
    fm = frontmatter(path)
    speakers = fm.get("speakers") or []
    if isinstance(speakers, str):
        speakers = [speakers]
    body = re.sub(r"^---.*?\n---\n", "", text, count=1, flags=re.S)
    blocks, page_text, cur = [], [], None
    in_page_text = False
    for line in body.splitlines():
        if line.startswith("## Lesson page text"):
            in_page_text, cur = True, None
            continue
        m = TS_BLOCK.match(line)
        p = PAGE_BLOCK.match(line)
        if not in_page_text and m:
            content, speaker = m.group(2), None
            for name in speakers:
                if content.startswith(name + ":"):
                    speaker, content = name, content[len(name) + 1:].lstrip()
                    break
            cur = [m.group(1), content, speaker]
            blocks.append(cur)
        elif not in_page_text and p:
            cur = [f"p. {p.group(1)}", "", None]
            blocks.append(cur)
        elif in_page_text or not blocks:
            page_text.append(line)
        elif cur is not None:
            cur[1] += " " + line
    duration = fm.get("duration")
    if duration is None or duration == "":
        duration = fm.get("duration_s")
    duration = str(duration)
    if TIMESTAMP.fullmatch(duration):
        end = ts_seconds(duration)
    else:
        end = float(duration) if re.fullmatch(r"\d+(?:\.\d+)?", duration) else None
    idx = {"blocks": [(b[0], norm(b[1])) for b in blocks], "block_speakers": [b[2] for b in blocks],
           "speakers": speakers, "page_text": norm(" ".join(page_text)), "all": norm(body),
           "end": end,
           "anchors": thread_anchors(body) if fm.get("method") == "skool-api" else {}}
    _raw_cache[key] = idx
    return idx


def thread_anchors(body: str) -> dict:
    """Skool thread (tools/skool_thread.py format): {'post' | 'c:<id8>': (author, normalised text)}."""
    anchors, key, author, buf, prefix = {}, None, None, [], ""
    def close():
        if key:
            anchors[key] = (author, norm(" ".join(buf)))
    for line in body.splitlines():
        h, ph = THREAD_HEAD.match(line), POST_HEAD.match(line)
        if key is None and ph:
            key, author, buf, prefix = "post", ph.group(1), [], ""
        elif h:
            close()
            prefix, author, key, buf = h.group(1), h.group(2), "c:" + h.group(3), []
        elif line.startswith("## Comments"):
            close()
            key = "comments"
        elif key and key != "comments":
            buf.append(line[len(prefix):] if line.startswith(prefix) else line.lstrip("> "))
    close()
    anchors.pop("comments", None)
    return anchors


def ts_seconds(label: str) -> int:
    parts = [int(x) for x in label.split(":")]
    return sum(v * 60 ** i for i, v in enumerate(reversed(parts)))


def check_cite(brain, rel, at, quote, where, errors, speaker=None) -> None:
    if quote and speaker and not any(ch.isalpha() for ch in speaker):
        errors.append(f"{where}: invalid quote speaker '{speaker}'")
    if quote and not speaker and topic(brain):
        errors.append(f"{where}: topic quote missing speaker")
    example = rel.removesuffix(".yaml").removesuffix(".md")
    if EXAMPLE.match(example):
        # examples/<id>.yaml holds measurements and frames, not text: the time must lie inside the video, no quotes
        path = brainlib.workspace(brain) / (example + ".yaml")
        library = brainlib.library_dir(brainlib.workspace(brain))
        if not path.is_file() or not path.resolve().is_relative_to(library.resolve()):
            errors.append(f"{where}: example file not found: {example}.yaml")
            return
        if not at.endswith("s") or ":" in at:
            errors.append(f"{where}: cite an example as '@ <seconds>s', got '{at}'")
            return
        duration = float((yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("duration_s") or 0)
        if float(at[:-1]) > duration + 0.5:
            errors.append(f"{where}: {at} is past the end of {rel} ({duration:.1f}s)")
        if quote:
            errors.append(f"{where}: quotes must cite a raw transcript, not {rel}")
        return
    if re.fullmatch(r"\d+(?:\.\d+)?s", at):
        errors.append(f"{where}: '@ {at}' (seconds) is only for examples/ files")
        return
    idx = raw_index(brain, rel)
    if idx is None:
        errors.append(f"{where}: raw file not found: {rel}")
        return
    at = re.sub(r"p\.\s*", "p. ", at)
    if at == "post" or at.startswith("c:"):
        anchor = idx["anchors"].get(at)
        if anchor is None:
            errors.append(f"{where}: no '{at}' in {rel}" + ("" if idx["anchors"] else " (not a Skool thread file)"))
            return
        author, text = anchor
        if quote:
            if norm(quote) not in text:
                other = [k for k, (_, t) in idx["anchors"].items() if norm(quote) in t]
                errors.append(f"{where}: quote not in {at} of {rel}{f' (found at {other[0]}: fix the anchor)' if other else ''}: \"{quote[:70]}\"")
            who = speaker or frontmatter(brain / "brain.md").get("default_speaker")
            if who and not (author.startswith(who) or who.startswith(author)):
                errors.append(f"{where}: quote attributed to '{who}' but {at} was written by '{author}': name the speaker")
        return
    if at == "page text":
        if quote and idx["page_text"] and norm(quote) in idx["page_text"]:
            # Written page text (a mixed capture's "## Lesson page text" section) is checked as written text.
            if topic(brain) and speaker:
                check_speaker(brain, idx, None, speaker, where, errors)
        elif quote and (any(idx["block_speakers"]) or idx["anchors"]):
            turns = [(name, " ".join(block[1] for _, block in turn))
                     for name, turn in itertools.groupby(zip(idx["block_speakers"], idx["blocks"]), key=lambda pair: pair[0])
                     if name]
            turns.extend(idx["anchors"].values())
            who = speaker or frontmatter(brain / "brain.md").get("default_speaker")
            if not any(who in speaker_names(brain, [name]) and norm(quote) in text for name, text in turns):
                errors.append(f"{where}: quote not spoken by '{who or '(unnamed)'}' in {rel}: cite its speaker turn")
        elif quote:
            if topic(brain) and speaker:
                check_speaker(brain, idx, None, speaker, where, errors)
            if norm(quote) not in (idx["page_text"] or idx["all"]):
                errors.append(f"{where}: quote not in page text of {rel}: \"{quote[:70]}\"")
        return
    secs = ts_seconds(at) if TIMESTAMP.fullmatch(at) else None
    if secs is not None and idx["end"] is not None and secs > idx["end"]:
        errors.append(f"{where}: timestamp {at} is past the end of {rel} ({idx['end']:g}s)")
        return
    labels = [b[0] for b in idx["blocks"]]
    if at not in labels:
        # Tolerate a timestamp inside a block, up to the known end.
        if secs is not None and any(TIMESTAMP.fullmatch(lab) for lab in labels):
            i = max((k for k, lab in enumerate(labels) if TIMESTAMP.fullmatch(lab) and ts_seconds(lab) <= secs),
                    default=None)
            if i is None:
                errors.append(f"{where}: timestamp {at} before first block in {rel}")
                return
        else:
            errors.append(f"{where}: no block '{at}' in {rel}")
            return
    else:
        i = labels.index(at)
    if quote:
        if topic(brain) and speaker:
            check_speaker(brain, idx, idx["block_speakers"][i], speaker, where, errors)
        q = norm(quote)
        blocks = idx["blocks"]
        radius = 0 if at.startswith("¶") else 1
        start, stop = max(0, i - radius), min(len(blocks), i + radius + 1)
        neighbors = blocks[start:stop]
        if topic(brain) and idx["block_speakers"][i]:
            neighbors = [blocks[k] for k in range(start, stop)
                         if idx["block_speakers"][k] == idx["block_speakers"][i]]
        window = " ".join(b[1] for b in neighbors)
        if q not in window:
            locator = "paragraph" if at.startswith("¶") else "timestamp"
            hint = f" (found elsewhere: fix the {locator})" if q in idx["all"] else ""
            errors.append(f"{where}: quote not at {at} in {rel}{hint}: \"{quote[:70]}\"")


@functools.lru_cache(maxsize=None)
def people(workspace):
    return brainlib.load_yaml(brainlib.library_dir(workspace) / "people.yaml", {}) or {}


def speaker_names(brain, names):
    allowed = list(names)
    if len(names) > 1:
        allowed.append(" and ".join(names))
    for person in people(brainlib.workspace(brain)).values():
        if person.get("name") in names:
            allowed.extend(person.get("aliases") or [])
    return allowed


def check_speaker(brain, idx, block_speaker, speaker, where, errors):
    allowed = speaker_names(brain, [block_speaker] if block_speaker else idx["speakers"])
    if allowed and speaker not in allowed:
        errors.append(f"{where}: quote speaker '{speaker}' does not match block speaker '{block_speaker or ', '.join(idx['speakers'])}'")


def scan_corruption(text, where, errors):
    for ln, line in enumerate(text.splitlines(), 1):
        if CORRUPTION.search(URL.sub("", line)):
            errors.append(f"{where}:{ln}: possible corruption")


@functools.lru_cache(maxsize=None)
def sibling_brains(brain):
    return {p.parent.name for p in brainlib.workspace(brain).glob("*/brain.md") if p.parent != brain}


def link_targets(brain):
    targets = {"brain"}
    for path in brainlib.wiki_pages(brain):
        targets.update((path.stem, path.relative_to(brain).with_suffix("").as_posix(),
                        path.relative_to(brain / "wiki").with_suffix("").as_posix()))
    return targets


def check_links(brain, page, line, where, errors, targets):
    for target in WIKI_LINK.findall(line):
        if target.startswith(("raw/", "library/", "notes/")):
            continue
        target = target.strip().replace("\\", "/").removesuffix(".md")
        parts = pathlib.PurePosixPath(target).parts
        if not parts:
            continue
        relative = (page.parent / target).resolve() if ".." in parts else None
        if ((len(parts) > 1 and parts[0] in sibling_brains(brain)) or ":" in parts[0] or parts[0] == "/"
                or (relative and not relative.is_relative_to(brain))):
            errors.append(f"{where}: cross-brain wikilink: [[{target}]]")
        elif targets is not None:
            local = relative.relative_to(brain).as_posix() if relative else target.removeprefix(brain.name + "/")
            if local not in targets:
                errors.append(f"{where}: unresolved wikilink: [[{target}]]")
    for link in MARKDOWN_LINK.finditer(line):
        destination = link.group(1) if link.group(1) is not None else link.group(2)
        if destination.startswith("//") or re.match(r"[a-zA-Z][a-zA-Z0-9+.-]+:", destination):
            continue
        target = unquote(re.split(r"[#?]", destination, maxsplit=1)[0])
        target = re.sub(r"\\([()])", r"\1", target).replace("\\", "/")
        if not target:
            continue
        try:
            resolved = (page.parent / target).resolve()
        except (OSError, RuntimeError, ValueError):
            errors.append(f"{where}: invalid Markdown link path: {destination}")
            continue
        if not resolved.is_relative_to(brain):
            if resolved.exists():
                errors.append(f"{WARNING}{where}: Markdown link leaves the brain folder: {destination}")
            else:
                errors.append(f"{where}: unresolved Markdown link outside the brain folder: {destination}")


def check_claims(body, page_type, where, errors):
    sections = {}
    for m in re.finditer(r"^## ([^\n]+)\n?(.*?)(?=^#{1,2} |\Z)", body, re.S | re.M):
        section = m.group(1).strip().lower()
        sections.setdefault(section, []).append(m.group(2))
    if page_type == "source" and not sections.keys() & {"key claims", "key points"}:
        errors.append(f"{where}: no '## Key claims' or '## Key points' section")
    elif page_type not in ("source", "rule") and "key points" not in sections:
        errors.append(f"{where}: no '## Key points' section")
    for section, blocks in sections.items():
        if section not in CLAIM_SECTIONS and not (page_type == "source" and section == "evidence"):
            continue
        for block in blocks:
            # One citation can support a wrapped bullet or paragraph.
            block = re.sub(r"^[ \t]*(?:#|>).*", "\n", INLINE_CODE.sub("", block), flags=re.M)
            claims = [claim.strip() for claim in re.split(r"\n\s*\n|\n(?=[ \t]*(?:[-*+] |\d+[.)] ))", block)
                      if claim.strip()]
            if not claims and page_type == "source" and section in {"key claims", "key points"}:
                errors.append(f"{where}: empty '{section.title()}' section")
            for i, claim in enumerate(claims):
                if CITE.search(claim) or "**Inference:**" in claim:
                    continue
                prose = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", claim)
                label = re.match(r"\*\*([^*\n]+)\*\*:?", prose)
                if label and re.search(r"\bInference\b", label[1]):
                    continue
                if navigation_only(prose) or re.fullmatch(r"\*\*[^*\n]+\*\*:?", claim) or claim.startswith("|"):
                    continue
                next_claim = claims[i + 1] if i + 1 < len(claims) else ""
                if not ((claim.endswith(":") or (label and label[0] == prose)) and CITE.search(next_claim)):
                    # Bullets in the core claim sections must cite; prose and Evidence notes often state an
                    # absence or give context, so they only warn.
                    bullet = section in CLAIM_SECTIONS and re.match(r"(?:[-*+]|\d+[.)])\s", claim)
                    errors.append(f"{'' if bullet else WARNING}{where}: {section} claim without citation: "
                                  f"{claim[:70].splitlines()[0]}")


def navigation_only(prose):
    without_links = MARKDOWN_LINK.sub("", WIKI_LINK.sub("", prose))
    return without_links != prose and re.fullmatch(
        r"(?:(?:for [\w -]+ )?see )?(?:[\s,.;]|\band\b|\bor\b)*", without_links, re.I)


def check_page(brain: pathlib.Path, path: pathlib.Path, errors: list) -> None:
    if path.resolve().is_relative_to((brain / "notes").resolve()):
        return
    text = path.read_text(encoding="utf-8")
    where = display_path(brain, path)
    scan_corruption(text, where, errors)
    card = path == brain / "brain.md"
    m = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
    if not m and not card:
        errors.append(f"{where}: missing frontmatter")
        return
    try:
        fm = (yaml.safe_load(m.group(1)) or {}) if m else {}
    except yaml.YAMLError as e:
        errors.append(f"{where}: bad frontmatter YAML: {e}")
        return
    offset = m.end() if m else 0
    body = text[offset:]
    if not card:
        if fm.get("type") not in TYPES:
            errors.append(f"{where}: type must be one of {sorted(TYPES)}")
        if not SLUG.match(path.stem):
            errors.append(f"{where}: filename not kebab-case")
        for k in ("sources", "updated"):
            if k not in fm:
                errors.append(f"{where}: frontmatter missing '{k}'")
        if fm.get("type") == "source":
            for k in (("publisher", "item", "url") if topic(brain) else ("module", "lesson", "url")):
                if k not in fm and (topic(brain) or "_attachments" not in str(fm.get("sources"))):
                    errors.append(f"{where}: source page missing '{k}'")
        check_schema(brain, fm, body, where, errors)
    for s in fm.get("sources") or []:
        if EXAMPLE.match(re.sub(r"\.yaml$", "", str(s))):
            if not (brainlib.workspace(brain) / str(s)).with_suffix(".yaml").exists():
                errors.append(f"{where}: frontmatter source not found: {s}")
        elif raw_index(brain, str(s)) is None:
            errors.append(f"{where}: frontmatter source not found: {s}")
    if re.search(r"\[\[notes/[^\]]+\]\]\s*@", body) or any(
            str(s).replace("\\", "/").lstrip("./").startswith("notes/") for s in fm.get("sources") or []):
        errors.append(f"{where}: wiki pages must not cite human-owned notes as sources")
    n_quotes = 0
    in_rules = in_rule_table = False
    targets = link_targets(brain) if card else None
    for ln, line in enumerate(body.splitlines(), text.count("\n", 0, offset) + 1):
        rule_row = False
        if card:
            stripped = line.strip()
            if stripped.startswith(("# ", "## ")):
                in_rules = stripped.lower() == "## rules"
            if not in_rules or not stripped.startswith("|"):
                in_rule_table = False
            elif not in_rule_table:
                in_rule_table = bool(RULE_TABLE_HEADER.match(stripped))
            elif not TABLE_DIVIDER.fullmatch(stripped):
                rule_row = True
        quotes_before_line = n_quotes
        # Blank out code spans (citation examples) for link scanning but keep positions, so quotes stay verbatim.
        scan = INLINE_CODE.sub(lambda m: " " * len(m[0]), line)
        location = f"{where}:{ln}"
        check_links(brain, path, scan, location, errors, targets)
        links = list(RAW_LINK.finditer(scan))
        prefix = line[:links[0].start()].rstrip().removesuffix("(").rstrip() if links else line
        q = QUOTE_LINE.fullmatch(prefix) if links else None
        if not q and ((line.lstrip().startswith(">") and QUOTE_MARKER.match(line))
                      or (links and QUOTE_BULLET.fullmatch(prefix))):
            errors.append(f"{location}: quote line needs a separator dash and a parsable citation")
        end = 0
        for i, link in enumerate(links):
            cite = CITE.match(scan, link.start())
            if not cite:
                errors.append(f"{location}: raw link without a valid '@ <locator>': {scan[link.start():link.start() + 70]}")
                continue
            quote = q if i == 0 else None
            if not quote and card and not QUOTE_MARKER.match(line):
                inline = line[end:link.start()].rsplit("|", 1)[-1].rstrip().removesuffix("(").rstrip()
                quote = INLINE_QUOTE.search(inline)
            speaker = (quote.group(2) or "").strip() if quote else None
            if quote:
                n_quotes += 1
            check_cite(brain, *cite.groups(), quote.group(1) if quote else None, location, errors, speaker)
            end = cite.end()
        if rule_row and n_quotes == quotes_before_line:
            errors.append(f"{location}: rule without an exact quote")
    if card or fm.get("type") in TYPES:
        check_claims(body, "rule" if card else fm["type"], where, errors)
    if fm.get("type") == "rule" and n_quotes == 0:
        errors.append(f"{where}: rule without an exact quote")


def check_staging(brain: pathlib.Path, path: pathlib.Path, errors: list) -> None:
    where = display_path(brain, path)
    text = path.read_text(encoding="utf-8")
    scan_corruption(text, where, errors)
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        errors.append(f"{where}: bad YAML: {e}")
        return
    for i, c in enumerate(data.get("concepts") or []):
        cw = f"{where}: concepts[{i}] {c.get('slug')}"
        if not SLUG.match(str(c.get("slug", ""))):
            errors.append(f"{cw}: slug not kebab-case")
        if c.get("type") not in TYPES - {"source"}:
            errors.append(f"{cw}: bad type {c.get('type')}")
        # Legacy persona staging infers rule status during ingest.
        schema = dict(c)
        if not topic(brain) and c.get("type") == "rule":
            schema.setdefault("status", "bench")
        check_schema(brain, schema, yaml.safe_dump(c, allow_unicode=True), cw, errors)
        if c.get("type") == "rule" and not c.get("quotes"):
            errors.append(f"{cw}: rule without a quote")
        for kind in ("points", "quotes"):
            for j, item in enumerate(c.get(kind) or []):
                stance = item.get("stance")
                if stance is not None and stance not in STANCES:
                    errors.append(f"{cw}: {kind}[{j}] stance must be one of {sorted(STANCES)}")
                cite = item.get("cite") or {}
                if not cite.get("raw") or not cite.get("at"):
                    errors.append(f"{cw}: {kind}[{j}] missing cite.raw/cite.at")
                    continue
                check_cite(brain, re.sub(r"\.md$", "", cite["raw"]), str(cite["at"]),
                           item.get("text") if kind == "quotes" else None, f"{cw} {kind}[{j}]", errors, item.get("speaker"))
    for key in ("findings", "tropes", "equipment", "examples"):  # cites must resolve to a real block
        for j, e in enumerate(data.get(key) or []):
            cite = e.get("cite") if isinstance(e, dict) else None
            if cite and cite.get("raw") and cite.get("at"):
                check_cite(brain, re.sub(r"\.md$", "", cite["raw"]), str(cite["at"]), None, f"{where}: {key}[{j}]", errors, None)
    for j, v in enumerate(data.get("voice") or []):
        cite = v.get("cite") or {}
        if cite.get("raw") and cite.get("at"):
            check_cite(brain, re.sub(r"\.md$", "", cite["raw"]), str(cite["at"]), v.get("text"), f"{where}: voice[{j}]", errors, v.get("speaker"))
        else:
            errors.append(f"{where}: voice[{j}] missing cite")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(parser)
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()
    brain = brainlib.brain_dir(args.brain)
    files = [pathlib.Path(f).resolve() for f in args.files]
    if not files:
        files = [brain / "brain.md", *sorted(brainlib.wiki_pages(brain)),
                 *sorted((brain / "ingest" / "staging").glob("*.yaml"))]
        files = [f for f in files if f.name not in ("index.md", "sources-index.md", "hot.md", "log.md")]
    errors: list[str] = []
    for f in files:
        if f.is_relative_to(brain / "notes") or f.is_relative_to(brain / "wiki" / "notes"):
            continue
        if not f.is_file():
            errors.append(f"{display_path(brain, f)}: file not found")
            continue
        (check_staging if f.suffix == ".yaml" else check_page)(brain, f, errors)
    hard = [e for e in errors if not e.startswith(WARNING)]
    if errors:
        print("\n".join(hard + [e for e in errors if e.startswith(WARNING)]))
    if not hard:
        print(f"ok: {len(files)} files" + (f" ({len(errors)} warnings)" if errors else ""))
    sys.exit(1 if hard else 0)


if __name__ == "__main__":
    main()

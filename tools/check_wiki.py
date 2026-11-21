"""Check wiki source pages and ingest staging files against raw/: citations resolve, quotes are verbatim.

Usage: python -I tools/check_wiki.py --brain <brain-folder> [files ...]
  With no files: every wiki page and ingest/staging/*.yaml in the brain.

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
A quote must appear verbatim (whitespace and curly quotes normalised, case-sensitive) in the cited block,
allowing it to run into the next block or start in the previous one. Exit code 1 if anything fails.
"""
import pathlib
import datetime as dt
import argparse
import functools
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # python -I drops the script dir
import brainlib

CITE = re.compile(r"\[\[((?:raw/|library/)[^\]|#]+?)(?:\.md|\.yaml)?(?:\|[^\]]*)?\]\]\s*@\s*(\d+:\d{2}(?::\d{2})?|p\.\s*\d+|¶\d+|page text|post|c:[0-9a-f]{8}|\d+(?:\.\d+)?s)")
EXAMPLE = re.compile(r"^library/[^/]+/examples/[^/]+$")  # measured example facts (docs/library.md); cited @ <seconds>s
QUOTE_LINE = re.compile(r'''^>\s*["“](.+?)["”]\s*[—–-]*\s*(.*?)\s*\(?\s*(\[\[(?:raw/|library/).*)$''')
# quotes that contain inner quote marks: the closing mark is the one followed by "— Speaker"; tried first
QUOTE_LINE_DASHED = re.compile(r'''^>\s*["“](.+?)["”]\s*[—–]\s*(.*?)\s*\(?\s*(\[\[(?:raw/|library/).*)$''')
TS_BLOCK = re.compile(r"^\*\*\[(\d+:\d{2}(?::\d{2})?|¶\d+)\]\*\*\s?(.*)$")
PAGE_BLOCK = re.compile(r"^\*\*\[p\. (\d+)\]\*\*\s*$")
THREAD_HEAD = re.compile(r"^((?:> )*)\*\*(.+?)\*\* \(@[^)]*\)(?: · \*\*\w+\*\*)? · [\d-]+ [\d:]+ · c:([0-9a-f]{8})\s*$")
POST_HEAD = re.compile(r"^\*\*(.+?)\*\* \(@[^)]*\) · [\d-]+ [\d:]+\s*$")
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
TYPES = {"source", "topic", "principle", "method", "framework", "rule", "glossary", "example", "rubric", "tool", "debate"}


@functools.lru_cache(maxsize=None)
def frontmatter(path):
    m = re.match(r"^---\n(.*?)\n---(?:\n|$)", path.read_text(encoding="utf-8"), re.S)
    return yaml.safe_load(m.group(1)) or {} if m else {}


def topic(brain):
    return frontmatter(brain / "brain.md").get("kind") == "topic"


def display_path(brain, path):
    root = brainlib.workspace(brain)
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


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


_raw_cache: dict[str, dict] = {}


def raw_index(brain: pathlib.Path, rel: str) -> dict | None:
    """Index raw text; block_speakers parallels blocks, keeping requote's pair format."""
    key = f"{brain}/{rel}"
    if key in _raw_cache:
        return _raw_cache[key]
    path = (brainlib.workspace(brain) if rel.startswith("library/") else brain) / (rel if rel.endswith(".md") else rel + ".md")
    if not path.exists():
        _raw_cache[key] = None
        return None
    text = path.read_text(encoding="utf-8")
    speakers = frontmatter(path).get("speakers") or []
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
    idx = {"blocks": [(b[0], norm(b[1])) for b in blocks], "block_speakers": [b[2] for b in blocks],
           "speakers": speakers, "page_text": norm(" ".join(page_text)), "all": norm(body),
           "anchors": thread_anchors(body) if frontmatter(path).get("method") == "skool-api" else {}}
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
    rel = re.sub(r"\.yaml$", "", rel)
    if EXAMPLE.match(rel):
        # examples/<id>.yaml holds measurements and frames, not text: the time must lie inside the video, no quotes
        path = brainlib.workspace(brain) / (rel + ".yaml")
        if not path.exists():
            errors.append(f"{where}: example file not found: {rel}.yaml")
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
        if quote and topic(brain):
            check_speaker(brain, idx, None, speaker, where, errors)
        hay = idx["page_text"] or idx["all"]
        if quote and norm(quote) not in hay:
            errors.append(f"{where}: quote not in page text of {rel}: \"{quote[:70]}\"")
        return
    labels = [b[0] for b in idx["blocks"]]
    if at not in labels:
        # tolerate a timestamp inside a block: map to the block that contains it
        if re.match(r"\d+:\d{2}", at) and labels and re.match(r"\d+:\d{2}", labels[0]):
            secs = ts_seconds(at)
            i = max((k for k, lab in enumerate(labels) if ts_seconds(lab) <= secs), default=None)
            if i is None:
                errors.append(f"{where}: timestamp {at} before first block in {rel}")
                return
        else:
            errors.append(f"{where}: no block '{at}' in {rel}")
            return
    else:
        i = labels.index(at)
    if quote:
        if topic(brain):
            check_speaker(brain, idx, idx["block_speakers"][i], speaker, where, errors)
        q = norm(quote)
        blocks = idx["blocks"]
        neighbors = blocks[max(0, i - 1): i + 2]
        if topic(brain) and idx["block_speakers"][i]:
            neighbors = [blocks[k] for k in range(max(0, i - 1), min(len(blocks), i + 2))
                         if idx["block_speakers"][k] == idx["block_speakers"][i]]
        window = " ".join(b[1] for b in neighbors)
        if q not in window:
            elsewhere = q in idx["all"]
            errors.append(f"{where}: quote not at {at} in {rel}{' (found elsewhere: fix the timestamp)' if elsewhere else ''}: \"{quote[:70]}\"")


def check_speaker(brain, idx, block_speaker, speaker, where, errors):
    if not speaker:
        errors.append(f"{where}: topic quote missing speaker")
        return
    people_file = brainlib.library_dir(brainlib.workspace(brain)) / "people.yaml"
    people = yaml.safe_load(people_file.read_text(encoding="utf-8")) or {} if people_file.exists() else {}
    allowed = [block_speaker] if block_speaker else list(idx["speakers"])
    if not block_speaker and len(allowed) > 1:
        allowed.append(" and ".join(idx["speakers"]))
    for person in people.values():
        if person.get("name") in allowed:
            allowed.extend(person.get("aliases") or [])
    if allowed and speaker not in allowed:
        errors.append(f"{where}: quote speaker '{speaker}' does not match block speaker '{block_speaker or ', '.join(idx['speakers'])}'")


def check_page(brain: pathlib.Path, path: pathlib.Path, errors: list) -> None:
    if path.resolve().is_relative_to((brain / "notes").resolve()):
        return
    text = path.read_text(encoding="utf-8")
    where = display_path(brain, path)
    m = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
    if not m:
        errors.append(f"{where}: missing frontmatter")
        return
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        errors.append(f"{where}: bad frontmatter YAML: {e}")
        return
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
    check_schema(brain, fm, text[m.end():], where, errors)
    for s in fm.get("sources") or []:
        if EXAMPLE.match(re.sub(r"\.yaml$", "", str(s))):
            if not (brainlib.workspace(brain) / str(s)).with_suffix(".yaml").exists():
                errors.append(f"{where}: frontmatter source not found: {s}")
        elif raw_index(brain, re.sub(r"\.md$", "", str(s))) is None:
            errors.append(f"{where}: frontmatter source not found: {s}")
    body = text[m.end():]
    if re.search(r"\[\[notes/[^\]]+\]\]\s*@", body) or any(
            str(s).replace("\\", "/").lstrip("./").startswith("notes/") for s in fm.get("sources") or []):
        errors.append(f"{where}: wiki pages must not cite human-owned notes as sources")
    n_quotes = 0
    for ln, line in enumerate(body.splitlines(), 1):
        q = QUOTE_LINE_DASHED.match(line) or QUOTE_LINE.match(line)
        cites = CITE.findall(line)
        if line.lstrip().startswith(">") and any(ch in line for ch in ('"', '“')) and not q:
            errors.append(f"{where}:{ln}: quote line without a parsable citation")
        for rel, at in cites:
            speaker = q.group(2).strip().rstrip("(").strip() if q else None
            if q and not speaker and not topic(brain):
                speaker = frontmatter(brain / "brain.md").get("default_speaker")
            check_cite(brain, rel, at, q.group(1) if q else None, f"{where}:{ln}", errors, speaker)
        if q:
            n_quotes += 1
        if ("[[raw/" in line or "[[library/" in line) and not cites:
            errors.append(f"{where}:{ln}: raw link without '@ <timestamp|p. N|¶N|page text>'")
    if fm.get("type") == "source":
        claims = re.search(r"^## Key claims\n(.*?)(?=^## |\Z)", body, flags=re.S | re.M)
        if not claims:
            errors.append(f"{where}: no '## Key claims' section")
        else:
            for line in claims.group(1).splitlines():
                if line.startswith("- ") and not CITE.search(line) and not line.startswith("- **Inference:**"):
                    errors.append(f"{where}: claim without citation: {line[:70]}")
    if fm.get("type") not in ("source", None):
        for sec in ("Key points", "Why", "When it applies"):
            block = re.search(rf"^## {sec}\n(.*?)(?=^## |\Z)", body, flags=re.S | re.M)
            for line in (block.group(1).splitlines() if block else []):
                if line.lstrip().startswith("- ") and not CITE.search(line) and "**Inference:**" not in line:
                    errors.append(f"{where}: {sec.lower()} bullet without citation: {line.strip()[:70]}")
        if not re.search(r"^## Key points", body, flags=re.M) and fm.get("type") != "rule":
            errors.append(f"{where}: no '## Key points' section")
    if fm.get("type") == "rule" and n_quotes == 0:
        errors.append(f"{where}: rule without an exact quote")


def check_staging(brain: pathlib.Path, path: pathlib.Path, errors: list) -> None:
    where = display_path(brain, path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
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
        files = sorted(brainlib.wiki_pages(brain)) + sorted((brain / "ingest" / "staging").glob("*.yaml"))
        files = [f for f in files if f.name not in ("index.md", "hot.md", "log.md")]
    errors: list[str] = []
    for f in files:
        if f.is_relative_to(brain / "notes"):
            continue
        (check_staging if f.suffix == ".yaml" else check_page)(brain, f, errors)
    print("\n".join(errors) if errors else f"ok: {len(files)} files")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

"""Check wiki source pages and ingest staging files against raw/: citations resolve, quotes are verbatim.

Usage: python -I tools/check_wiki.py --brain <brain-folder> [files ...]
  With no files: every wiki page and ingest/staging/*.yaml in the brain.

Citation forms (paths relative to the brain folder, `.md` optional):
  ([[raw/main/m02-x/l01-y]] @ 1:07)       transcript block timestamp
  ([[raw/_attachments/z]] @ p. 3)         PDF page
  ([[raw/main/m01-x/l04-y]] @ page text)   lesson page text (or a text-only lesson)
Library paths resolve from the workspace root; @ ¶N addresses web blocks.
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

CITE = re.compile(r"\[\[((?:raw/|library/)[^\]|#]+?)(?:\.md)?(?:\|[^\]]*)?\]\]\s*@\s*(\d+:\d{2}(?::\d{2})?|p\.\s*\d+|¶\d+|page text)")
QUOTE_LINE = re.compile(r'''^>\s*["“](.+?)["”]\s*[—–-]*\s*(.*?)\s*\(?\s*(\[\[(?:raw/|library/).*)$''')
TS_BLOCK = re.compile(r"^\*\*\[(\d+:\d{2}(?::\d{2})?|¶\d+)\]\*\*\s?(.*)$")
PAGE_BLOCK = re.compile(r"^\*\*\[p\. (\d+)\]\*\*\s*$")
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
    for key, values in (("evidence", {"research", "official", "practitioner", "example", "inference"}),
                        ("freshness", {"evergreen", "platform", "tool-version"})):
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
            debates = [p for p in (brain / "wiki").rglob("*.md") if frontmatter(p).get("type") == "debate"]
            if not any(t.removesuffix('.md') in (p.stem, p.relative_to(brain).with_suffix('').as_posix(), p.relative_to(brain / 'wiki').with_suffix('').as_posix()) for t in targets for p in debates):
                errors.append(f"{where}: contested rule requires a link to a debate page")


def norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("…", "...")
    s = re.sub(r"\*\*|__", "", s)
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
           "speakers": speakers, "page_text": norm(" ".join(page_text)), "all": norm(body)}
    _raw_cache[key] = idx
    return idx


def ts_seconds(label: str) -> int:
    parts = [int(x) for x in label.split(":")]
    return sum(v * 60 ** i for i, v in enumerate(reversed(parts)))


def check_cite(brain, rel, at, quote, where, errors, speaker=None) -> None:
    idx = raw_index(brain, rel)
    if idx is None:
        errors.append(f"{where}: raw file not found: {rel}")
        return
    at = re.sub(r"p\.\s*", "p. ", at)
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
    people_file = brainlib.workspace(brain) / "library" / "people.yaml"
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
        if raw_index(brain, re.sub(r"\.md$", "", str(s))) is None:
            errors.append(f"{where}: frontmatter source not found: {s}")
    body = text[m.end():]
    n_quotes = 0
    for ln, line in enumerate(body.splitlines(), 1):
        q = QUOTE_LINE.match(line)
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
        files = sorted((brain / "wiki").rglob("*.md")) + sorted((brain / "ingest" / "staging").glob("*.yaml"))
        files = [f for f in files if f.name not in ("index.md", "hot.md", "log.md")]
    errors: list[str] = []
    for f in files:
        (check_staging if f.suffix == ".yaml" else check_page)(brain, f, errors)
    print("\n".join(errors) if errors else f"ok: {len(files)} files")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

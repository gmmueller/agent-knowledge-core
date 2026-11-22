"""Repair quotes after a raw file was re-crawled: re-find each failing quote in the new transcript.

Usage: python -I tools/requote.py --brain <brain-folder> <raw-rel-path> <file> [<file> ...] [--apply] [--min 0.85]

Only quotes citing <raw-rel-path> that check_wiki.py would reject are touched. For each, the closest window of the
new transcript (same word count ±30%) is found with difflib; with --apply, quotes at or above --min similarity are
replaced by the new verbatim text and block label. Lower matches are listed for a manual decision.
The --apply mode skips protected wiki pages.
"""
import argparse
import difflib
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # -I drops the script dir; tools/ is ours
import brainlib
import wiki_edits
from check_wiki import norm, raw_index

LOCATOR = r"(?:\d+:\d{2}(?::\d{2})?|¶\d+|p\.\s*\d+)"


def _key(w: str) -> str:
    return re.sub(r"[^\w']", "", w.lower())


def best_match(idx: dict, quote: str) -> tuple[float, str, str]:
    """Closest transcript window to the quote. Candidates are anchored on shared word pairs, so it stays fast."""
    words = []  # (word, label)
    for label, text, *_ in idx["blocks"]:
        words += [(w, label) for w in text.split()]
    keys = [_key(w) for w, _ in words]
    qw = [_key(w) for w in norm(quote).split()]
    q = " ".join(qw)
    pairs = {(qw[i], qw[i + 1]): i for i in range(len(qw) - 1)}
    starts = set()
    for j in range(len(keys) - 1):
        i = pairs.get((keys[j], keys[j + 1]))
        if i is not None:
            starts.update(range(max(0, j - i - 3), j - i + 4))
    best = (0.0, "", "")
    for s in starts:
        for size in {max(3, int(len(qw) * f)) for f in (0.8, 0.9, 1.0, 1.1, 1.2)}:
            chunk = words[s:s + size]
            if not chunk:
                continue
            r = difflib.SequenceMatcher(None, q, " ".join(keys[s:s + size]), autojunk=False).ratio()
            if r > best[0]:
                best = (r, chunk[0][1], " ".join(w for w, _ in chunk))
    return best


def quote_ok(idx: dict, quote: str, at: str) -> bool:
    labels = [b[0] for b in idx["blocks"]]
    if at not in labels:
        return False
    i = labels.index(at)
    window = " ".join(b[1] for b in idx["blocks"][max(0, i - 1): i + 2])
    return norm(quote) in window


def main() -> None:
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("raw")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--min", type=float, default=0.85)
    a = ap.parse_args()
    brain = brainlib.brain_dir(a.brain)
    raw = re.sub(r"\.md$", "", a.raw)
    idx = raw_index(brain, raw)
    if idx is None:
        sys.exit(f"raw file not found: {raw}")
    esc = re.escape(raw)
    page_q = re.compile(r'^(>\s*")(.+?)("\s*[—–-]*\s*[^\n(]*\(\[\[' + esc + r'(?:\.md)?\]\]\s*@\s*)(' + LOCATOR + r')(\))', re.M)
    wiki = (brain / "wiki").resolve()
    protected = wiki_edits.protected_pages(brain) if a.apply else set()
    for f in a.files:
        path = pathlib.Path(f)
        resolved = path.resolve()
        if resolved.is_relative_to(wiki):
            name = resolved.relative_to(wiki).as_posix()
            if name in protected:
                print(f"skipped protected page: wiki/{name}")
                continue
        original = text = path.read_text(encoding="utf-8")
        changes = []
        if path.suffix == ".md":
            def fix(m):
                quote, at = m.group(2), m.group(4)
                if quote_ok(idx, quote, at):
                    return m.group(0)
                r, label, new = best_match(idx, quote)
                changes.append((r, at, label, quote, new))
                if a.apply and r >= a.min:
                    return f"{m.group(1)}{new}{m.group(3)}{label}{m.group(5)}"
                return m.group(0)
            text = page_q.sub(fix, text)
        else:
            # staging YAML: only items under concepts[].quotes and voice are quotes (points are paraphrases)
            import yaml

            data = yaml.safe_load(text) or {}
            quote_texts = {str(q.get("text")) for c in data.get("concepts") or [] for q in c.get("quotes") or []}
            quote_texts |= {str(v.get("text")) for v in data.get("voice") or []}
            # edit textually ("- text: <quote>" followed by cite raw/at lines) to keep the file's formatting
            pat = re.compile(r'(text:\s*)(["\']?)(.+?)\2(\n\s+cite:\s*\n\s+raw:\s*' + esc + r'(?:\.md)?\s*\n\s+at:\s*[\'"]?)(' + LOCATOR + r')([\'"]?)')
            def fix(m):
                quote, at = m.group(3), m.group(5)
                if quote.replace('\\"', '"') not in quote_texts or quote_ok(idx, quote, at):
                    return m.group(0)
                r, label, new = best_match(idx, quote)
                changes.append((r, at, label, quote, new))
                if a.apply and r >= a.min:
                    q = '"' + new.replace("\\", "\\\\").replace('"', '\\"') + '"'
                    return f"{m.group(1)}{q}{m.group(4)}{label}{m.group(6)}"
                return m.group(0)
            text = pat.sub(fix, text)
        for r, at, label, old, new in changes:
            flag = "FIXED" if a.apply and r >= a.min else ("would fix" if r >= a.min else "MANUAL")
            print(f"{flag} {r:.2f} {f} @ {at} -> {label}\n    old: {old[:100]}\n    new: {new[:100]}")
        if a.apply and text != original:
            path.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

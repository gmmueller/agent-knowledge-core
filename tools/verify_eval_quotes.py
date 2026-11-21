"""Verify quotes in an eval answers file with check_wiki's citation checker (speaker and verbatim).

Usage: python -I tools/verify_eval_quotes.py --brain <brain-folder> <answers.md>
"""
import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib
import check_wiki as cw  # noqa: E402

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(parser)
    parser.add_argument("answers", type=pathlib.Path)
    args = parser.parse_args()
    brain = brainlib.brain_dir(args.brain)
    text = args.answers.read_text(encoding="utf-8")
    # "quote" — Speaker ([[library/...]] @ t), or "quote" ([[raw/...]] @ t | page text | post | c:<id8>) for a persona's
    # unnamed quotes (inline, possibly several per line). The dash is optional for raw/ cites only: in topic brains an
    # undashed library quote usually names its speaker in the prose before it, which the second pass covers.
    pat = re.compile(r'["“]([^"”]{8,400})["”](\s*[—–-]\s*([A-Z][\w.\' -]{1,40}?)?)?\s*\(\s*\[\[((?:library|raw)/[^\]|#]+?)(?:\.md)?\]\]\s*@\s*([\d:]+|¶\d+|p\.\s*\d+|page text|post|c:[0-9a-f]{8})')
    total, errors = 0, []
    for ln, line in enumerate(text.splitlines(), 1):
        for quote, dash, speaker, rel, at in pat.findall(line):
            if not dash and not rel.startswith("raw/"):
                continue
            total += 1
            before = len(errors)
            cw.check_cite(brain, rel, at, quote, f"line {ln}", errors, speaker.strip() or None)
            if len(errors) > before:
                errors[-1] += f"  [speaker: {speaker.strip() or '(default)'}]"
    print(f"{total} attributed quotes checked, {len(errors)} problems")
    print("\n".join(errors))

    # Second pass: answers often quote a speaker but cite a wiki page instead of a raw block, which the check above
    # skips. Every quoted phrase of 5+ words must still appear verbatim (case-insensitive) in some raw file.
    corpus = "\n".join(cw.norm(p.read_text(encoding="utf-8")).lower()
                       for root in (brainlib.library_dir(brainlib.workspace(brain)), brain / "raw") if root.exists()
                       for p in root.glob("*/raw/**/*.md" if root.name == "library" else "**/*.md"))
    loose = [(ln, q) for ln, line in enumerate(text.splitlines(), 1)
             for q in re.findall(r'["“]([^"”]{12,400})["”]', line) if len(q.split()) >= 5]
    missing = [(ln, q) for ln, q in loose if cw.norm(q).lower().rstrip(".,;:!?") not in corpus]
    print(f"{len(loose)} quoted phrases checked against all raw text, {len(missing)} not found verbatim "
          "(review each: a misquote, or a label, example line or user's own words in quote marks)")
    print("\n".join(f"line {ln}: \"{q[:90]}\"" for ln, q in missing))


if __name__ == "__main__":
    main()

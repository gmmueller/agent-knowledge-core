"""Verify quotes in an eval answers file with check_wiki's citation checker (speaker and verbatim).

Usage: python -I tools/verify_eval_quotes.py --brain <brain-folder> <answers.md>
Exit code 1 if either pass finds a problem.
"""
import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib
import check_wiki as cw  # noqa: E402
from reference_sources import enabled as reference_mode

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(parser)
    parser.add_argument("answers", type=pathlib.Path)
    args = parser.parse_args()
    brain = brainlib.brain_dir(args.brain)
    reference = reference_mode(cw.frontmatter(brain / "brain.md"))
    text = args.answers.read_text(encoding="utf-8")
    # "quote" — Speaker ([[library/...]] @ t), or "quote" ([[raw/...]] @ t | page text | post | c:<id8>) for a persona's
    # unnamed quotes (inline, possibly several per line). In expert topic brains an undashed library quote usually
    # names its speaker in the preceding prose, which the second pass covers.
    # \w without digits or underscore allows a Unicode initial letter.
    pat = re.compile(
        r"""["“]([^"”]{8,400})["”](\s*[—–-]\s*([^\W\d_][\w.'’ -]*?(?:\([^()\n]+\))?)?)?"""
        r"\s*\(\s*\[\[((?:library|raw)/[^\]|#]+?)(?:\.md)?\]\]\s*@\s*"
        rf"({cw.QUOTE_LOCATOR}|[\d:]+)(?![\w:]|\.\d)"
    )
    total, errors, masked_lines = 0, [], []
    for ln, line in enumerate(text.splitlines(), 1):
        spans = []
        for match in pat.finditer(line):
            quote, dash, speaker, rel, at = (g or "" for g in match.groups())
            if not dash and not rel.startswith("raw/") and not reference:
                continue
            total += 1
            before = len(errors)
            cw.check_cite(brain, rel, at, quote, f"line {ln}", errors, speaker.strip() or None)
            if len(errors) > before:
                errors[-1] += f"  [speaker: {speaker.strip() or '(default)'}]"
            spans.append(match.span(0))
        if spans:
            chars = list(line)
            for start, end in spans:
                chars[start:end] = [" "] * (end - start)
            line = "".join(chars)
        masked_lines.append((ln, line))
    print(f"{total} attributed quotes checked, {len(errors)} problems")
    print("\n".join(errors))

    # Second pass: answers often quote a speaker but cite a wiki page instead of a raw block, which the check above
    # skips. Every quoted phrase of 5+ words must still appear verbatim (case-insensitive) in some raw file.
    corpus = "\n".join(cw.norm(p.read_text(encoding="utf-8")).lower()
                       for root in (brainlib.library_dir(brainlib.workspace(brain)), brain / "raw") if root.exists()
                       for p in root.glob("*/raw/**/*.md" if root.name == "library" else "**/*.md"))
    loose = [(ln, match[1]) for ln, line in masked_lines
             for match in re.finditer(r'["“]([^"”]{1,400})["”]', line)
             if len(match[1]) >= 12 and len(match[1].split()) >= 5]
    missing = [(ln, q) for ln, q in loose if cw.norm(q).lower().rstrip(".,;:!?") not in corpus]
    print(f"{len(loose)} quoted phrases checked against all raw text, {len(missing)} not found verbatim "
          "(review each: a misquote, or a label, example line or user's own words in quote marks)")
    print("\n".join(f"line {ln}: \"{q[:90]}\"" for ln, q in missing))
    return int(bool(errors or missing))


if __name__ == "__main__":
    sys.exit(main())

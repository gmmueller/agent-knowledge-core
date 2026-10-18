"""Convert Skool rich text to Markdown.

Classroom lesson bodies (`metadata.desc`) are stored as "[v2]" + ProseMirror-style JSON.
Post and comment bodies (`metadata.content`) are already Markdown and are returned unchanged.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib

import hashlib
import json


def lesson_hash(meta: dict) -> str:
    """Change key for a classroom lesson: body + video + resources. Needs a full module fetch
    (course-tree nodes carry no `desc`, so a hash from them is not comparable)."""
    return hashlib.sha1(((meta.get("desc") or "") + (meta.get("videoLink") or "") + (meta.get("resources") or "")).encode("utf-8")).hexdigest()


def _marks(text: str, marks: list) -> str:
    for m in marks or []:
        t = m.get("type")
        if t == "bold":
            text = f"**{text}**"
        elif t == "italic":
            text = f"*{text}*"
        elif t == "code":
            text = f"`{text}`"
        elif t == "link":
            text = f"[{text}]({(m.get('attrs') or {}).get('href', '')})"
    return text


def _inline(nodes: list) -> str:
    out = []
    for n in nodes or []:
        t = n.get("type")
        if t == "text":
            out.append(_marks(n.get("text", ""), n.get("marks")))
        elif t == "hardBreak":
            out.append("\n")
        elif t == "image":
            a = n.get("attrs") or {}
            out.append(f"![{a.get('alt', '')}]({a.get('originalSrc') or a.get('src', '')})")
        elif t == "mention":
            out.append("@" + str((n.get("attrs") or {}).get("label", "")))
        else:
            out.append(_inline(n.get("content")))
    return "".join(out)


def _block(n: dict, indent: str = "") -> list[str]:
    t, content = n.get("type"), n.get("content")
    if t == "paragraph":
        return [indent + _inline(content).strip()]
    if t == "heading":
        return ["#" * int((n.get("attrs") or {}).get("level", 2)) + " " + _inline(content).strip()]
    if t in ("bulletList", "orderedList"):
        lines = []
        for i, item in enumerate(content or [], 1):
            bullet = f"{i}. " if t == "orderedList" else "- "
            sub = [ln for c in item.get("content") or [] for ln in _block(c, indent + "  ")]
            sub = [ln for ln in sub if ln.strip()]
            if sub:
                lines.append(indent + bullet + sub[0].strip())
                lines += sub[1:]
        return lines
    if t == "codeBlock":
        return ["```", _inline(content), "```"]
    if t == "blockquote":
        return ["> " + ln for c in content or [] for ln in _block(c)]
    if t == "horizontalRule":
        return ["---"]
    if t == "image":
        return [_inline([n])]
    return [ln for c in content or [] for ln in _block(c, indent)] if content else []


def desc_to_markdown(desc: str | None) -> str:
    """Skool lesson `desc` -> Markdown. Plain strings pass through."""
    if not desc:
        return ""
    if not desc.startswith("[v2]"):
        return desc.strip()
    doc = json.loads(desc[4:])
    blocks = []
    for n in doc if isinstance(doc, list) else doc.get("content", []):
        text = "\n".join(_block(n)).rstrip()
        if text.strip():
            blocks.append(text)
    return "\n\n".join(blocks)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(ap)
    ap.add_argument("input", help="UTF-8 file containing a lesson desc (offline)")
    args = ap.parse_args()
    brainlib.brain_dir(args.brain)
    print(desc_to_markdown(Path(args.input).read_text(encoding="utf-8")))

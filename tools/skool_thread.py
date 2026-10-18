"""Render a Skool post plus its comment tree into a raw thread file (Markdown with frontmatter).

Used by the community crawler; usable for any Skool group.
Each comment gets a stable anchor `c:<first 8 chars of comment id>` so wiki pages can cite
`(raw/community/... @ c:aa70c354)`. Mentions like `[@Name](obj://user/<id>)` become `@Name`.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from skool_session import configure

import datetime as dt
import json
import re

MENTION = re.compile(r"\[(@[^\]]+)\]\(obj://[^)]*\)")


def clean(text: str) -> str:
    return MENTION.sub(r"\1", text or "").strip()


def person(user: dict) -> tuple[str, str]:
    name = " ".join(x for x in (user.get("firstName") or user.get("first_name"), user.get("lastName") or user.get("last_name")) if x)
    return name or user.get("name", "?"), user.get("name", "?")


def role_of(user: dict, roles: dict) -> str:
    """Role from the explicit staff map (user id -> 'owner'|'admin'|'moderator'), else 'member'.

    Don't infer staff from spData.role: gamification roles are not staff roles.
    """
    return roles.get(user.get("id") or user.get("user_id"), "member")


def _created(post: dict) -> str:
    return (post.get("createdAt") or post.get("created_at") or "")[:16].replace("T", " ")


def comment_items(tree: dict, depth: int = 0):
    """Yield (depth, post) for every comment in a comments-API tree, in display order."""
    for ch in (tree or {}).get("children") or []:
        yield depth, ch["post"]
        yield from comment_items(ch, depth + 1)


def thread_markdown(post: dict, comment_trees: list[dict], roles: dict, labels: dict,
                    group: str, source_id: str, voice: str, captured: str | None = None) -> str:
    """post: a post object (feed or post page). comment_trees: post_tree / pinned_post_tree dicts.
    roles: user id -> 'owner'|'admin'|'moderator'. labels: label id -> category name."""
    md = post["metadata"]
    name, handle = person(post.get("user") or {})
    seen, comments = set(), []
    for tree in comment_trees:
        for depth, c in comment_items(tree):
            if c["id"] not in seen:
                seen.add(c["id"])
                comments.append((depth, c))
    role = role_of(post.get("user") or {"id": post.get("userId")}, roles)
    front = {
        "source_id": source_id,
        "title": md.get("title", ""),
        "url": f"https://www.skool.com/{group}/{post['name']}",
        "post_id": post["id"],
        "author": f"{name} (@{handle})",
        "author_role": role,
        "category": labels.get(post.get("labelId") or md.get("labels", ""), post.get("labelId")),
        "created": post.get("createdAt"),
        "updated": post.get("updatedAt"),
        "comments": md.get("comments", len(comments)),
        "comments_captured": len(comments),
        "upvotes": md.get("upvotes"),
        "voice": voice,
        "captured": captured or dt.date.today().isoformat(),
        "method": "skool-api",
    }
    lines = ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in front.items()] + ["---", ""]
    lines += [f"# {md.get('title', '')}", "", f"**{name}** (@{handle}, {role}) · {_created(post)}", "", clean(md.get("content")), ""]
    if md.get("attachments") or md.get("videoIds"):
        lines += [f"_Attachments: {md.get('attachments') or '-'}; videos: {md.get('videoIds') or '-'}_", ""]
    if comments:
        lines += ["## Comments", ""]
    for depth, c in comments:
        cname, chandle = person(c.get("user") or {})
        crole = role_of(c.get("user") or {"id": c.get("user_id")}, roles)
        tag = f" · **{crole}**" if crole != "member" else ""
        indent = "> " * depth
        head = f"{indent}**{cname}** (@{chandle}){tag} · {_created(c)} · c:{c['id'][:8]}"
        body = "\n".join(f"{indent}{ln}" if ln else indent.rstrip() for ln in clean((c.get("metadata") or {}).get("content")).split("\n"))
        lines += [head, body, ""]
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(ap)
    ap.add_argument("input", help="offline JSON with post, comment_trees, roles, labels, source_id and voice")
    args = ap.parse_args()
    brain, config = configure(args)
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    print(thread_markdown(data["post"], data.get("comment_trees", []), data.get("roles", {}),
                          data.get("labels", {}), config["group"], data["source_id"], data["voice"],
                          data.get("captured")), end="")

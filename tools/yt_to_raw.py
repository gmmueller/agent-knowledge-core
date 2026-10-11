"""Convert English YouTube captions into immutable raw transcripts.

Requires yt-dlp for uncached captions; no-English-caption exit code is 3."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from source_helpers import configure, brain_path, cache_key

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess

from wistia_to_raw import paragraphs, ts, yaml_str  # noqa: E402  shared paragraphing (~30 s blocks)



def fetch_captions(video_id: str, cache: pathlib.Path) -> tuple[pathlib.Path | None, str]:
    cache_key(video_id)
    cache.mkdir(parents=True, exist_ok=True)
    for kind, flag in (("manual", "--write-subs"), ("auto", "--write-auto-subs")):
        found = sorted(cache.glob(f"{video_id}.{kind}.*.json3"))
        if not found:
            subprocess.run(
                ["yt-dlp", "--skip-download", flag, "--sub-langs", "en-orig,en,en-US,en-GB", "--sub-format", "json3",
                 "-o", str(cache / f"{video_id}.{kind}.%(ext)s"), f"https://www.youtube.com/watch?v={video_id}"],
                check=False, capture_output=True,
            )
            found = sorted(cache.glob(f"{video_id}.{kind}.*.json3"))
        if found:
            # prefer the original-language auto track over YouTube's machine "translation" to en
            orig = [f for f in found if ".en-orig." in f.name]
            return (orig or found)[0], kind
    return None, ""


def upload_date(video_id: str, cache: pathlib.Path) -> str:
    """YouTube upload date as YYYY-MM-DD ('' if unknown); cached in <cache>/<id>.upload_date."""
    cache_key(video_id)
    f = cache / f"{video_id}.upload_date"
    if not f.exists():
        r = subprocess.run(["yt-dlp", "--skip-download", "--print", "%(upload_date)s",
                            f"https://www.youtube.com/watch?v={video_id}"], check=False, capture_output=True, text=True)
        d = (r.stdout or "").strip()
        if r.returncode != 0 or not re.fullmatch(r"\d{8}", d):
            return ""
        cache.mkdir(parents=True, exist_ok=True)
        f.write_text(d, encoding="utf-8")
    d = f.read_text(encoding="utf-8").strip()
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def json3_lines(path: pathlib.Path) -> list[dict]:
    """json3 events -> the {start, end, text: [str]} shape wistia_to_raw.paragraphs expects."""
    events = json.loads(path.read_text(encoding="utf-8")).get("events", [])
    lines = []
    for e in events:
        text = "".join(s.get("utf8", "") for s in e.get("segs") or []).replace("\n", " ").strip()
        if not text:
            continue
        start = e.get("tStartMs", 0) / 1000
        lines.append({"start": start, "end": start + e.get("dDurationMs", 0) / 1000, "text": [text]})
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    for a in ("video-id", "source-id", "title", "module", "url", "out"):
        ap.add_argument(f"--{a}", required=True)
    ap.add_argument("--cache", default="media/youtube")
    ap.add_argument("--notes")
    ap.add_argument("--duration-s", type=float)
    ap.add_argument("--extra-front", nargs="*", default=[], help="extra frontmatter lines as key=value")
    args = ap.parse_args()

    brain, _ = configure(args)
    resolve = lambda p: brain_path(brain, p)  # noqa: E731
    out = resolve(args.out)
    if out.exists():
        sys.exit(f"refusing to overwrite existing raw file: {out}")

    path, kind = fetch_captions(args.video_id, resolve(args.cache))
    if not path:
        print(f"no English captions for {args.video_id}; use the whisper path", file=sys.stderr)
        sys.exit(3)
    lines = json3_lines(path)
    paras = paragraphs(lines)
    duration = args.duration_s or (lines[-1]["end"] if lines else 0)

    front = [
        "---",
        f"source_id: {args.source_id}",
        f"title: {yaml_str(args.title)}",
        f"module: {yaml_str(args.module)}",
        f"url: {args.url}",
        f"video: youtube:{args.video_id}",
        f"duration: {ts(duration)}",
        f"captured: {dt.date.today().isoformat()}",
        "method: captions",
        f"captions: {'youtube-manual' if kind == 'manual' else 'youtube-auto'}",
        *[f"{k}: {v}" for k, v in (kv.split('=', 1) for kv in args.extra_front)],
        "---",
        "",
    ]
    body = ["## Transcript\n"] + [f"**[{ts(t)}]** {text}\n" for t, text in paras]
    if args.notes:
        body.append(resolve(args.notes).read_text(encoding="utf-8").strip() + "\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(front) + "\n".join(body), encoding="utf-8", newline="\n")
    words = sum(len(t.split()) for _, t in paras)
    print(f"wrote {out.relative_to(brain)}  ({kind} captions, {len(lines)} lines, {len(paras)} blocks, {words} words)")


if __name__ == "__main__":
    main()

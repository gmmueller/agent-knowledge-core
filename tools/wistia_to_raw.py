"""Convert English Wistia captions into immutable raw transcripts.

JSON is cached in media/wistia/. --offline requires cached inputs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
import raw_guard
from source_helpers import configure, brain_path, cache_key

import argparse
import datetime as dt
import json
import pathlib
import re
import time
import urllib.request

PARA_MIN_S = 30  # start a new paragraph after ~30s, at a sentence end
PARA_MAX_S = 45  # ...or force one at 45s


def fetch_json(kind: str, media_id: str, brain: pathlib.Path, *, offline=False) -> dict:
    cache_key(media_id)
    if kind not in {"medias", "captions"}:
        raise ValueError("Wistia input must be medias or captions")
    CACHE = brain / "media" / "wistia"
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{media_id}.{kind}.json"
    if not path.exists():
        if offline:
            raise FileNotFoundError(f"missing cached Wistia input: {path}")
        url = f"https://fast.wistia.com/embed/{kind}/{media_id}.json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            path.write_bytes(r.read())
        time.sleep(0.3)
    return json.loads(path.read_text(encoding="utf-8"))


def ts(seconds: float) -> str:
    s = int(seconds)
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def english_lines(captions: dict) -> list[dict]:
    for cap in captions.get("captions", []):
        if cap.get("language") == "eng" or cap.get("bcp47LanguageTag", "").startswith("en"):
            return cap["hash"]["lines"]
    return []


def paragraphs(lines: list[dict]) -> list[tuple[float, str]]:
    paras, start, buf = [], None, []
    for ln in lines:
        text = " ".join(ln["text"]).strip()
        text = re.sub(r"^-\s+", "", text)  # Wistia marks speaker turns with a leading dash
        if not text:
            continue
        if start is None:
            start = ln["start"]
        buf.append(text)
        age = ln["end"] - start
        if (age >= PARA_MIN_S and re.search(r"[.!?][\"')\]]*$", text)) or age >= PARA_MAX_S:
            paras.append((start, " ".join(buf)))
            start, buf = None, []
    if buf:
        paras.append((start, " ".join(buf)))
    return paras


def yaml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)  # JSON strings are valid YAML scalars


def main() -> None:
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("--offline", action="store_true")
    for a in ("media-id", "source-id", "title", "module", "url", "out"):
        ap.add_argument(f"--{a}", required=True)
    ap.add_argument("--notes")
    args = ap.parse_args()

    brain, _ = configure(args)
    out = brain_path(brain, args.out)
    if out.exists():
        sys.exit(f"refusing to overwrite existing raw file: {out}")

    media = fetch_json("medias", args.media_id, brain, offline=args.offline)["media"]
    lines = english_lines(fetch_json("captions", args.media_id, brain, offline=args.offline))
    if not lines:
        sys.exit(f"no English captions for {args.media_id}; use the whisper path")

    front = [
        "---",
        f"source_id: {args.source_id}",
        f"title: {yaml_str(args.title)}",
        f"module: {yaml_str(args.module)}",
        f"url: {args.url}",
        f"video: wistia:{args.media_id}",
        f"duration: {ts(media['duration'])}",
        f"captured: {dt.date.today().isoformat()}",
        "method: captions",
        "---",
        "",
    ]
    body = [f"**[{ts(t)}]** {text}\n" for t, text in paragraphs(lines)]
    if args.notes:
        notes = pathlib.Path(args.notes).read_text(encoding="utf-8").strip()
        body += ["## Lesson page text\n", notes + "\n"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(front) + "\n".join(body), encoding="utf-8", newline="\n")
    raw_guard.record_capture(out)
    words = sum(len(t.split()) for _, t in paragraphs(lines))
    print(f"wrote {out.relative_to(brain)}  ({len(lines)} caption lines, {len(body)} blocks, {words} words)")


if __name__ == "__main__":
    main()

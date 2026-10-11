"""Build immutable raw lesson and PDF files from media/ caches and outline.yaml.

Missing inputs are reported as pending. --verify checks existing transcripts."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from source_helpers import configure, brain_path

import argparse
import datetime as dt
import json
import pathlib
import re

import yaml

from attachment_to_raw import write_pdf_raw
from wistia_to_raw import english_lines, fetch_json, paragraphs, ts, yaml_str



def outline_lessons():
    o = yaml.safe_load((BRAIN / "outline.yaml").read_text(encoding="utf-8"))

    def walk(cats, path):
        for c in cats or []:
            for l in c.get("lessons") or []:
                yield path + [c["title"]], l
            yield from walk(c.get("categories"), path + [c["title"]])

    for p in o["products"]:
        for path, l in walk(p["categories"], []):
            yield p, path, l


def att_id(filename: str) -> str:
    return "att-" + pathlib.Path(filename).stem.replace("_", "-")


def load_manifest() -> list[dict] | None:
    path = MEDIA / "attachments" / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def build_attachments(manifest: list[dict]) -> dict[str, list[str]]:
    """Write raw files for PDFs; return lesson id -> attachment source ids that have a raw file."""
    by_lesson: dict[str, list[str]] = {}
    for entry in manifest:
        canonical = brain_path(BRAIN, entry["canonical"])
        ids = list(dict.fromkeys(link["lesson_id"] for link in entry["links"]))
        raw = BRAIN / "raw" / "_attachments" / f"{canonical.stem}.md"
        if canonical.suffix.lower() == ".pdf" and not raw.exists():
            write_pdf_raw(canonical, ids, entry["links"][0]["url"], entry["links"][0]["title"], brain=BRAIN)
        elif not raw.exists():
            # png: transcribed by the orchestrator; mp3: audio copies of captioned lessons, no raw file
            print(f"  no raw file for {canonical.name} ({canonical.suffix}); handle manually if needed")
        if raw.exists():
            for lid in ids:
                by_lesson.setdefault(lid, []).append(att_id(canonical.name))
    return by_lesson


def transcript_lines(lesson: dict) -> tuple[str, list[dict], dict] | None:
    """(method, lines, extra frontmatter) for a lesson's video, or None if not ready."""
    mid = lesson["video"].split(":", 1)[1]
    if lesson.get("captions"):
        if not (MEDIA / "wistia" / f"{mid}.captions.json").exists():
            return None
        return "captions", english_lines(fetch_json("captions", mid, BRAIN, offline=True)), {}
    cache = MEDIA / "whisper" / f"{mid}.json"
    if not cache.exists():
        return None
    w = json.loads(cache.read_text(encoding="utf-8"))
    lines = [{"start": s["start"], "end": s["end"], "text": [s["text"]]} for s in w["segments"]]
    return "whisper", lines, {"whisper_model": w["model"]}


def build_lesson(product: dict, path: list[str], lesson: dict, atts: list[str]) -> str:
    out = brain_path(BRAIN, lesson["raw_path"])
    if out.exists():
        return "exists"
    page = MEDIA / "pages" / f"{lesson['id']}.md"
    if not page.exists():
        return "pending-page"
    notes = page.read_text(encoding="utf-8").strip()
    video = str(lesson.get("video") or "none")
    extra: dict = {}
    if video.startswith("wistia:"):
        media_id = video.split(":", 1)[1]
        if not (MEDIA / "wistia" / f"{media_id}.medias.json").exists():
            return "pending-media"
        got = transcript_lines(lesson)
        if got is None:
            return "pending-captions" if lesson.get("captions") else "pending-whisper"
        method, lines, extra = got
        paras = paragraphs(lines)
        duration = ts(fetch_json("medias", video.split(":", 1)[1], BRAIN, offline=True)["media"]["duration"])
    else:
        if not notes:
            return "empty-text-only"
        method, paras, duration = "page-text", [], None

    front = ["---", f"source_id: {lesson['id']}", f"title: {yaml_str(lesson['title'])}",
             f"product: {product['code']}", f"module: {yaml_str(' > '.join(path))}", f"url: {lesson['url']}",
             f"video: {video}"]
    if duration:
        front.append(f"duration: {duration}")
    front += [f"captured: {dt.date.today().isoformat()}", f"method: {method}"]
    front += [f"{k}: {v}" for k, v in extra.items()]
    if product["code"] in LIVE_PRODUCTS or lesson["id"] in LIVE_LESSONS:
        front.append(f"speakers: {yaml_str(SPEAKERS)}")
    if atts:
        front.append(f"attachments: [{', '.join(dict.fromkeys(atts))}]")
    front += ["---", ""]

    body = [f"**[{ts(t)}]** {text}\n" for t, text in paras]
    if notes:
        body += (["## Lesson page text\n"] if paras else []) + [notes + "\n"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(front) + "\n".join(body), encoding="utf-8", newline="\n")
    return method


def verify() -> None:
    problems, n, words_total = [], 0, 0
    for product, path, lesson in outline_lessons():
        out = brain_path(BRAIN, lesson["raw_path"])
        if not out.exists():
            problems.append(f"missing  {lesson['id']}")
            continue
        n += 1
        text = out.read_text(encoding="utf-8")
        blocks = re.findall(r"^\*\*\[[\d:]+\]\*\* (.*)$", text, re.M)
        words = sum(len(b.split()) for b in blocks)
        words_total += words
        dur = lesson.get("duration_s") or 0
        if str(lesson.get("video", "")).startswith("wistia:"):
            wpm = words / (dur / 60) if dur else 0
            if not blocks or wpm < 80 or wpm > 260:
                problems.append(f"wpm {wpm:5.0f}  {lesson['id']}  ({words} words / {dur / 60:.1f} min)")
            last = re.findall(r"^\*\*\[([\d:]+)\]\*\*", text, re.M)
            if last:
                parts = [int(x) for x in last[-1].split(":")]
                last_s = sum(v * 60 ** i for i, v in enumerate(reversed(parts)))
                if dur and last_s < dur - 120:
                    problems.append(f"ends early {last[-1]} of {dur / 60:.1f} min  {lesson['id']}")
        elif len(text.split("---", 2)[-1].strip()) < 200:
            problems.append(f"short text-only  {lesson['id']}")
    print(f"{n} lesson raw files, {words_total:,} transcript words")
    print("\n".join(problems) if problems else "no problems")


def main() -> None:
    global BRAIN, MEDIA, LIVE_PRODUCTS, LIVE_LESSONS, SPEAKERS
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    BRAIN, config = configure(args)
    MEDIA = BRAIN / "media"
    multi = config.get("multi_speaker") or {}
    LIVE_PRODUCTS, LIVE_LESSONS = set(multi.get("products", [])), set(multi.get("lessons", []))
    SPEAKERS = multi.get("label", "multi: co-hosts and attendees; not diarized")
    if args.verify:
        return verify()
    manifest = load_manifest()
    atts = build_attachments(manifest) if manifest else {}
    if manifest is None:
        print("no attachments manifest yet: lesson files would lack attachment links; stopping")
        return
    counts: dict[str, list[str]] = {}
    for product, path, lesson in outline_lessons():
        status = build_lesson(product, path, lesson, atts.get(lesson["id"], []))
        counts.setdefault(status, []).append(lesson["id"])
    for status, ids in sorted(counts.items()):
        tail = "" if status in ("exists", "captions", "whisper", "page-text") else ": " + ", ".join(ids)
        print(f"{status}: {len(ids)}{tail}")


if __name__ == "__main__":
    main()

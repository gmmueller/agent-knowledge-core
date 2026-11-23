"""Crawl Skool classroom lessons from outline.yaml into raw/ files (incremental, read-only).

Usage: python -I tools/skool_classroom_crawl.py \
         --brain <brain> [--port <port>] [--only <source_id> ...] [--limit N] [--dry-run]

Per lesson (skipping locked lessons and `duplicate_of` copies):
  1. lesson body: from the module cache (.secrets/scratch/<short>/modules) or one throttled
     `_next/data` fetch (?md=<module id>) when the cache lacks it or is stale;
  2. transcript: YouTube captions via yt-dlp (tools/yt_to_raw.py); Skool-native (Mux) videos via the
     HLS "English CC" track (tools/mux_captions.py); Loom via faster-whisper with --whisper
     (tools/whisper_lines.py); lessons with no video become `method: page-text`; anything else is
     recorded as `needs_whisper` in the state file and skipped for now;
  3. dates: `published` = YouTube upload date when known, else the module's Skool createdAt
     (`skool_created`); `lesson_updated` moves on any edit, so it is not an age signal;
  4. writes raw/classroom/<course code>-<course slug>/<NNN>-<lesson slug>.md.
State: <brain>/state/classroom_crawled.json maps source_id -> {content_hash, raw_path, method, captured}.
A lesson whose content_hash changed since capture gets a NEW file `<NNN>-<slug>.<YYYY-MM-DD>.md` with
`supersedes:` pointing at the old one (raw/ is immutable). Stops cleanly on RateLimited.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
import raw_guard
from source_helpers import stamp_skool
from skool_session import configure, scratch_dir

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import time
import unicodedata

import yaml
from playwright.sync_api import sync_playwright

import mux_captions
import whisper_lines
from skool_session import BudgetExhausted, NotLoggedIn, RateLimited, next_data
from skool_text import desc_to_markdown, lesson_hash
from wistia_to_raw import paragraphs, ts, yaml_str
from yt_to_raw import fetch_captions, json3_lines, upload_date

sys.stdout.reconfigure(encoding="utf-8")


def slug(text: str, maxlen: int = 60) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return (t[:maxlen].rstrip("-")) or "untitled"


def find_node(tree, mid):
    if tree["course"]["id"] == mid:
        return tree
    for ch in tree.get("children") or []:
        r = find_node(ch, mid)
        if r:
            return r
    return None


def module_meta(browser, group, course_code, lesson, cache_dir: pathlib.Path, *, brain: pathlib.Path, need_video=False):
    """(module incl. createdAt and metadata.desc, pageProps.video) from cache if fresh, else one fetch.

    need_video: a Skool/Mux lesson needs an unexpired playback token, so refetch when it's stale.
    """
    p = cache_dir / f"{lesson['id']}.json"
    if p.exists():
        rec = json.loads(p.read_text(encoding="utf-8"))  # cache files are always full module fetches
        video = rec.get("video") or {}
        fresh_token = not need_video or float(video.get("expire") or 0) > time.time() + 1800
        if rec.get("updatedAt") == lesson.get("updated") and fresh_token:
            return rec["module"], rec.get("video")
    d = next_data(browser, f"{group}/classroom/{course_code}", {"md": lesson["id"]}, brain=brain)
    node = find_node(d["pageProps"]["course"], lesson["id"])
    if not node:
        raise RuntimeError(f"module {lesson['id']} not in response")
    m = node["course"]
    cache_dir.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"updatedAt": m["updatedAt"], "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
                             "course_code": course_code, "module": m, "video": d["pageProps"].get("video")},
                            ensure_ascii=False), encoding="utf-8")
    return m, d["pageProps"].get("video")


def resources_md(lesson) -> str:
    items = []
    for r in lesson.get("resources") or []:
        if r.get("url"):
            items.append(f"- [{r.get('title') or r['url']}]({r['url']})")
        else:
            items.append(f"- {r.get('title') or r.get('file_name')} (file: {r.get('file_name')}; not downloaded)")
    return "\n".join(items)


def main():
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("--group", default=None, help="Skool group slug (default: crawl.yaml site)")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--whisper", action="store_true", help="transcribe Loom videos on the GPU (check it's idle first)")
    args = ap.parse_args()
    brain, config = configure(args)
    ROOT = brainlib.workspace(brain)
    group = args.group
    outline = yaml.safe_load((brain / "outline.yaml").read_text(encoding="utf-8"))
    cache_dir = scratch_dir(brain, "modules")
    media = brain / "media" / "youtube"
    state_p = brain / "state" / "classroom_crawled.json"
    state = json.loads(state_p.read_text(encoding="utf-8")) if state_p.exists() else {}
    today = dt.date.today().isoformat()

    todo = []
    for c in outline["courses"]:
        if not c.get("access"):
            continue
        for sec in c.get("sections") or []:
            for les in sec.get("lessons") or []:
                if les.get("duplicate_of") or les.get("module_access") is False:
                    continue
                if args.only and les["source_id"] not in args.only:
                    continue
                prev = state.get(les["source_id"])
                if prev and prev.get("content_hash") == les.get("content_hash") and prev.get("method") != "needs_whisper":
                    continue
                todo.append((c, sec, les))
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} lessons to crawl", flush=True)
    if args.dry_run:
        for c, sec, les in todo:
            print(les["source_id"], les.get("video"), les["title"])
        return

    def save_state():
        brainlib.atomic_write(state_p, json.dumps(state, indent=1, ensure_ascii=False))

    done = errors = 0
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{args.port}")
        try:
            for c, sec, les in todo:
                try:
                    sid = les["source_id"]
                    video = les.get("video") or ""
                    module, vinfo = module_meta(browser, group, c["code"], les, cache_dir, brain=brain, need_video=video.startswith("skool:"))
                    meta = module["metadata"]
                    chash = lesson_hash(meta)  # outline hashes can be null (--tree-only); this one is from the full module
                    prev = state.get(sid, {})
                    if prev.get("raw_path") and prev.get("content_hash") == chash and prev.get("method") != "needs_whisper":
                        print(f"{sid}: unchanged (lesson touched, content same)", flush=True)
                        continue
                    skool_created = (module.get("createdAt") or "")[:10]
                    published = skool_created  # best guess at when the content was made; YouTube upload date wins
                    paras, method, caption_kind, duration = [], "page-text", None, les.get("duration_s") or 0
                    if video.startswith("youtube:"):
                        cap, caption_kind = fetch_captions(video.split(":", 1)[1], media)
                        published = upload_date(video.split(":", 1)[1], media) or published
                        if cap:
                            paras, method, caption_kind = paragraphs(json3_lines(cap)), "captions", f"youtube-{caption_kind}"
                        else:
                            method = "needs_whisper"
                    elif video.startswith("skool:") and vinfo:
                        cues = mux_captions.lines(vinfo, brain / "media" / "mux")
                        duration = float(vinfo.get("duration") or 0) / 1000 or duration
                        if cues:
                            paras, method, caption_kind = paragraphs(cues), "captions", "mux-auto"
                        else:
                            method = "needs_whisper"
                    elif video.startswith("loom:"):
                        method = "needs_whisper"
                    elif video:
                        method = "needs_whisper"
                    if method == "needs_whisper" and args.whisper and video.startswith("loom:"):
                        loom_id = video.split(":", 1)[1]
                        segs = whisper_lines.lines(loom_id, f"https://www.loom.com/share/{loom_id}", brain / "media" / "loom", (config.get("whisper") or {}).get("prompt", ""),
                                                           (config.get("whisper") or {}).get("model", "large-v3-turbo"))
                        if segs:
                            paras, method = paragraphs(segs), "whisper"
                            duration = duration or segs[-1]["end"]
                        else:  # transcribed, but no speech (short silent clips): keep the page text
                            method, caption_kind = "page-text", "whisper-no-speech"
                    if method == "needs_whisper":
                        state[sid] = {**prev, "content_hash": chash, "method": method, "video": video, "checked": today}
                        print(f"{sid}: needs whisper ({video})", flush=True)
                        continue

                    course_dir = brain / "raw" / "classroom" / f"{c['code']}-{slug(c['title'], 40)}"
                    n = sid.rsplit("-", 1)[1]
                    out = course_dir / f"{n}-{slug(les['title'])}.md"
                    supersedes = prev.get("raw_path")
                    module_title = c["title"] + (f" / {sec['title']}" if sec.get("title") else "")
                    front = [
                        "---",
                        f"source_id: {sid}",
                        f"title: {yaml_str(les['title'])}",
                        f"module: {yaml_str(module_title)}",
                        f"url: {les['url']}",
                        f"video: {video or 'none'}",
                        f"duration: {ts(duration) if video else '0:00'}",
                        f"published: {published or 'unknown'}",
                        f"skool_created: {skool_created or 'unknown'}",
                        f"captured: {today}",
                        f"method: {method}",
                    ]
                    if caption_kind:
                        front.append(f"captions: {caption_kind}")
                    front += [f"lesson_updated: {les.get('updated')}", f"content_hash: {chash}"]
                    body = []
                    if paras:
                        body += ["## Transcript", ""] + [f"**[{ts(t)}]** {text}\n" for t, text in paras]
                    text = desc_to_markdown(meta.get("desc"))
                    text = re.sub(r"^(#{1,5}) ", r"#\1 ", text, flags=re.M)  # nest lesson headings under ours
                    if text:
                        body += ["## Lesson page text", "", text, ""]
                    res = resources_md(les)
                    if res:
                        body += ["## Attached files", "", res, ""]
                    text_body = "\n".join(body).rstrip() + "\n"
                    raw = "\n".join([*front, "---", ""]) + text_body
                    if not supersedes and out.exists() and out.read_text(encoding="utf-8") != raw:
                        supersedes = out.relative_to(ROOT).as_posix()
                    if supersedes:
                        raw = "\n".join([*front, f"supersedes: {supersedes}", "---", ""]) + text_body
                        base = out.with_stem(f"{out.stem}.{today}")
                        out, revision = base, 2
                        while out.exists() and out.read_text(encoding="utf-8") != raw:
                            out = base.with_stem(f"{base.stem}-{revision}")
                            revision += 1
                    if not out.exists():
                        brainlib.atomic_write(out, raw)
                    raw_guard.record_capture(out)
                    rel = str(out.relative_to(ROOT)).replace("\\", "/")
                    state[sid] = {"content_hash": chash, "raw_path": rel, "method": method, "captured": today}
                    done += 1
                    words = sum(len(t.split()) for _, t in paras)
                    print(f"{sid}: wrote {rel} ({method}, {words} transcript words, {len(text)} text chars)", flush=True)
                    if done % 10 == 0:
                        save_state()
                except (RateLimited, BudgetExhausted, NotLoggedIn):
                    raise
                except Exception as e:
                    errors += 1
                    print(f"{les.get('source_id')}: ERROR {type(e).__name__}: {str(e)[:300]}", flush=True)
        except (RateLimited, BudgetExhausted) as e:
            errors += 1
            print(f"stopped: {type(e).__name__}: {e}", flush=True)
        finally:
            save_state()
    if not errors and not (args.only or args.limit) and not any(
            state.get(les["source_id"], {}).get("method") == "needs_whisper" for _, _, les in todo):
        stamp_skool(brain, config["site"] + "/classroom")
    print(f"done: {done} written, {errors} errors", flush=True)
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())

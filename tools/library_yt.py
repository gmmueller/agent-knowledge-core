"""Catalogue YouTube channels/RSS feeds and fetch resumable library transcripts.

Run with tools/.venv/Scripts/python -I tools/library_yt.py --help.
"""
import argparse
import datetime as dt
import email.utils
import json
import io
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.request
import wave
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import patch

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib
import library_raw as lr
from yt_to_raw import fetch_captions, json3_lines, upload_date

TABS = {"videos": "video", "shorts": "short", "streams": "stream"}
# Fields kept in media/meta/<id>.json; the full yt-dlp dump is ~1 MB of format lists.
META_KEYS = ("id", "title", "upload_date", "release_date", "duration", "view_count",
             "description", "width", "height", "channel", "channel_id", "uploader")


def ytdlp(*args):
    result = subprocess.run(["yt-dlp", *map(str, args)], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=300)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "yt-dlp failed")
    return result.stdout


def log(publisher, operation, messages):
    path = lr.pub_dir(publisher) / "crawl-log.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n## [{dt.date.today().isoformat()}] {operation}\n\n")
        f.write("\n".join(f"- {lr.clean_field(m)}" for m in messages) + "\n")


def failure(messages, label, error):
    message = f"FAILED {label}: {error}"
    messages.append(message)
    print(message, flush=True)
    if re.search(r"429|sign.?in|bot|too many requests", str(error), re.I):
        time.sleep(30)


def metadata(publisher, video_id):
    path = lr.pub_dir(publisher) / "media" / "meta" / f"{video_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    data = json.loads(ytdlp("-J", "--skip-download", f"https://www.youtube.com/watch?v={video_id}"))
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {k: data[k] for k in META_KEYS if k in data}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    time.sleep(1)
    return data


def youtube_row(data, source, kind):
    date = data.get("upload_date") or data.get("release_date") or ""
    return {"id": f"yt-{data['id']}", "kind": kind, "title": data.get("title", ""),
            "published": f"{date[:4]}-{date[4:6]}-{date[6:]}" if re.fullmatch(r"\d{8}", date) else "",
            "duration_s": int(data["duration"]) if data.get("duration") is not None else "",
            "views": data.get("view_count"), "url": f"https://www.youtube.com/watch?v={data['id']}",
            "source": source, "description": data.get("description", "")}


def duration_seconds(value):
    parts = value.strip().split(":")
    if not all(p.isdigit() for p in parts) or len(parts) > 3:
        return ""
    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return total


def podcast_rows(source):
    request = urllib.request.Request(source["rss"], headers={"User-Agent": "brains-library/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        root = ET.fromstring(response.read())
    rows = []
    for item in root.findall("./channel/item"):
        title = item.findtext("title") or "Untitled"
        date = item.findtext("pubDate") or ""
        if date:
            date = email.utils.parsedate_to_datetime(date).date().isoformat()
        rows.append({"id": f"pod-{lr.slugify(title)}", "kind": "podcast", "title": title,
                     "published": date, "duration_s": duration_seconds(item.findtext(
                         "{http://www.itunes.com/dtds/podcast-1.0.dtd}duration") or ""),
                     "url": item.findtext("link") or "", "source": source["id"],
                     "description": item.findtext("description") or ""})
    return rows


def catalogue(publisher, config, details):
    messages, candidates = [], []
    for source in config["sources"]:
        counts = dict(source.get("counts") or {})
        succeeded = False
        if source["type"] == "youtube-channel":
            for tab in source.get("tabs", ["videos"]):
                try:
                    data = json.loads(ytdlp("--flat-playlist", "-J", source["url"].rstrip("/") + "/" + tab))
                    rows = []
                    for entry in data.get("entries", []):
                        if not entry.get("id"):
                            continue
                        cached = lr.pub_dir(publisher) / "media" / "meta" / f"{entry['id']}.json"
                        if cached.exists():
                            entry = json.loads(cached.read_text(encoding="utf-8"))
                        rows.append(youtube_row(entry, source["id"], TABS[tab]))
                    added, updated = lr.merge_catalogue(publisher, rows)
                    counts[tab] = len(rows)
                    candidates.extend((i, row) for i, row in enumerate(rows))
                    messages.append(f"{source['id']} {tab}: {len(rows)} items, {added} added, {updated} updated")
                    print(messages[-1], flush=True)
                    succeeded = True
                except Exception as error:
                    failure(messages, f"{source['id']} {tab}", error)
        elif source["type"] == "podcast" and source.get("rss"):
            try:
                rows = podcast_rows(source)
                added, updated = lr.merge_catalogue(publisher, rows)
                counts["podcast"] = len(rows)
                messages.append(f"{source['id']}: {len(rows)} episodes, {added} added, {updated} updated")
                succeeded = True
            except Exception as error:
                failure(messages, source["id"], error)
        if succeeded:
            source.update(last_crawled=dt.date.today().isoformat(), counts=counts)
    known = lr.read_catalogue(publisher)
    seen, attempted, enriched = set(), 0, []
    # Flat playlists are newest first within each tab; interleave tabs by rank.
    for _, row in sorted(candidates, key=lambda pair: pair[0]):
        if row["id"] in seen or known[row["id"]].get("published"):
            continue
        seen.add(row["id"])
        if attempted >= details:
            break
        attempted += 1
        try:
            data = metadata(publisher, row["id"][3:])
            enriched.append(youtube_row(data, row["source"], row["kind"]))
        except Exception as error:
            failure(messages, row["id"], error)
    if enriched:
        lr.merge_catalogue(publisher, enriched)
    (lr.pub_dir(publisher) / "sources.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    messages.append(f"Metadata: {attempted} lookups requested; catalogue total: {len(known)}")
    log(publisher, "catalogue", messages)
    print("\n".join(messages), flush=True)
    return any(m.startswith("FAILED") for m in messages)


class Transcriber:
    def __init__(self):
        self.model = None

    def lines(self, publisher, video_id):
        audio = lr.audio_path(publisher, video_id)
        audio.parent.mkdir(parents=True, exist_ok=True)
        if not audio.exists():
            ytdlp("--no-playlist", "-f", "bestaudio[ext=m4a]", "-o", audio,
                   f"https://www.youtube.com/watch?v={video_id}")
        wav = audio.with_suffix(".16k.wav")
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(audio),
                        "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", str(wav)], check=True)
        import numpy as np
        if self.model is None:
            import nvidia
            self.dlls = []
            for base in nvidia.__path__:
                for folder in pathlib.Path(base).glob("*/bin"):
                    self.dlls.append(os.add_dll_directory(str(folder)))
                    os.environ["PATH"] = str(folder) + os.pathsep + os.environ["PATH"]
            from faster_whisper import WhisperModel
            self.model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16", local_files_only=True)
        try:
            with wave.open(str(wav)) as f:
                samples = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
            segments, _ = self.model.transcribe(samples, language="en", vad_filter=True, beam_size=5,
                                               repetition_penalty=1.05, compression_ratio_threshold=2.0)
            return [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]
        finally:
            wav.unlink(missing_ok=True)


def captions(video_id, cache, messages):
    # The shared fetcher suppresses stderr; retain it so rate limits reach the run log.
    blocked = []
    def run(*args, **kwargs):
        result = subprocess.run(*args, **kwargs, timeout=300)
        if result.returncode:
            error = result.stderr.decode("utf-8", errors="replace")
            messages.append(f"Caption warning {video_id}: {error}")
            if re.search(r"429|sign.?in|bot|too many requests", error, re.I):
                blocked.append(error.strip())
                time.sleep(30)
        return result
    with patch("yt_to_raw.subprocess", SimpleNamespace(run=run)):
        result = fetch_captions(video_id, cache)
    if not result[0] and blocked:
        raise RuntimeError("; ".join(blocked))
    return result


def fetch(publisher, config, ids):
    rows = lr.read_catalogue(publisher)
    sources = {s["id"]: s for s in config["sources"]}
    messages, transcriber = [], Transcriber()
    for index, item_id in enumerate(dict.fromkeys(ids)):
        if index:
            time.sleep(1.5)
        try:
            if not re.fullmatch(r"yt-[A-Za-z0-9_-]{11}", item_id):
                raise ValueError(f"not a YouTube item: {item_id}")
            row = rows[item_id]
            stage = lr.staging_path(publisher, item_id, "lines.json")
            raw_dir = lr.pub_dir(publisher) / "raw" / "yt"
            if stage.exists() or any(raw_dir.glob(f"*-{item_id[3:]}-*.md")):
                messages.append(f"SKIP {item_id}: output exists")
                continue
            source = sources[row["source"]]
            data = metadata(publisher, item_id[3:])
            enriched = youtube_row(data, row["source"], row["kind"])
            lr.merge_catalogue(publisher, [enriched])
            row = {k: enriched.get(k) or v for k, v in row.items()}
            cache = lr.pub_dir(publisher) / "media" / "captions"
            row["published"] = row["published"] or upload_date(item_id[3:], cache)
            path, caption_kind = captions(item_id[3:], cache, messages)
            lines = [{**line, "text": " ".join(line["text"])} for line in json3_lines(path)] if path else []
            method = "captions" if lines else "whisper"
            if not lines:
                lines = transcriber.lines(publisher, item_id[3:])
            if not lines:
                raise ValueError("empty transcript")
            front = {"source_id": item_id, "publisher": publisher, "title": row["title"],
                     "url": row["url"], "kind": row["kind"], "published": row["published"],
                     "duration": lr.ts(float(row["duration_s"] or lines[-1]["end"])),
                     "captured": dt.date.today().isoformat(), "method": method}
            if method == "captions":
                front["captions"] = "youtube-" + caption_kind
            tab = next(t for t, kind in TABS.items() if kind == row["kind"])
            mode = (source.get("tab_format") or {}).get(tab, source.get("format"))
            if mode == "solo":
                speaker = config.get("default_speaker")
                if not speaker:
                    raise ValueError("solo source requires default_speaker")
                front.update(speakers=[speaker], speaker_method="single")
                for line in lines:
                    line["speaker"] = speaker
                output = lr.raw_path(publisher, "yt", row["published"], row["title"], item_id)
                lr.write_raw(output, front, lr.render_transcript(lr.transcript_blocks(lines)))
            else:
                front["speaker_method"] = "none"
                output = stage
                stage.parent.mkdir(parents=True, exist_ok=True)
                with stage.open("x", encoding="utf-8") as f:
                    json.dump({"item": item_id, "front": front, "lines": lines}, f, ensure_ascii=False, indent=2)
            message = f"OK {item_id}: {method}, {len(lines)} lines -> {output.relative_to(lr.ROOT)}"
            messages.append(message)
            print(message, flush=True)
        except Exception as error:
            failure(messages, item_id, error)
    log(publisher, "fetch", messages)
    print("\n".join(messages), flush=True)
    return any(m.startswith("FAILED") for m in messages)


def self_check():
    assert duration_seconds("1:02:03") == 3723
    assert duration_seconds("90") == 90
    assert duration_seconds("") == ""
    row = youtube_row({"id": "abcdefghijk", "upload_date": "20260512", "duration": 12.5}, "channel", "short")
    assert row["published"] == "2026-05-12" and row["id"] == "yt-abcdefghijk"
    assert TABS["shorts"] == "short"
    feed = b'<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel><item><title>Test Episode</title><link>https://example.com/episode</link><pubDate>Tue, 12 May 2026 12:00:00 GMT</pubDate><itunes:duration>1:02:03</itunes:duration><description>Teaching</description></item></channel></rss>'
    with patch("urllib.request.urlopen", return_value=io.BytesIO(feed)):
        rows = podcast_rows({"rss": "https://example.com/rss", "id": "test"})
    assert len(rows) == 1 and rows[0]["id"] == "pod-test-episode"
    assert rows[0]["duration_s"] == 3723 and rows[0]["published"] == "2026-05-12"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    brainlib.add_workspace_arg(parser)
    subs = parser.add_subparsers(dest="command", required=True)
    cat = subs.add_parser("catalogue")
    cat.add_argument("publisher")
    cat.add_argument("--details", type=int, default=0)
    get = subs.add_parser("fetch")
    get.add_argument("publisher")
    choice = get.add_mutually_exclusive_group(required=True)
    choice.add_argument("--items", nargs="+")
    choice.add_argument("--selection", type=pathlib.Path)
    get.add_argument("--tiers", default="A,B,X")
    add = subs.add_parser("add", help="catalogue single videos (guest appearances on channels we don't list in full)")
    add.add_argument("publisher")
    add.add_argument("--source", required=True, help="a sources.yaml source id (type youtube-selected)")
    add.add_argument("videos", nargs="+", help="video ids or URLs")
    subs.add_parser("self-check")
    args = parser.parse_args()
    lr.init(args.workspace)
    if args.command == "self-check":
        self_check()
        print("self-check passed")
        return
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.publisher):
        parser.error("publisher must be kebab-case ASCII")
    config = yaml.safe_load((lr.pub_dir(args.publisher) / "sources.yaml").read_text(encoding="utf-8"))
    if args.command == "catalogue":
        if args.details < 0:
            parser.error("--details must be non-negative")
        failed = catalogue(args.publisher, config, args.details)
    elif args.command == "add":
        if args.source not in {s["id"] for s in config["sources"]}:
            parser.error(f"unknown source {args.source}")
        rows, messages = [], []
        for v in args.videos:
            m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", v)
            vid = m.group(1) if m else v
            try:
                data = metadata(args.publisher, vid)
                kind = "short" if "/shorts/" in v or (data.get("duration") or 999) <= 180 and (data.get("height") or 0) > (data.get("width") or 1) else "video"
                rows.append(youtube_row(data, args.source, kind))
                print(f"{vid}: {data.get('title')}", flush=True)
            except Exception as error:
                failure(messages, vid, error)
        added, updated = lr.merge_catalogue(args.publisher, rows)
        messages.insert(0, f"add {args.source}: {added} added, {updated} updated")
        log(args.publisher, "add", messages)
        failed = len(rows) < len(args.videos)
    else:
        ids = args.items
        if args.selection:
            selection = yaml.safe_load(args.selection.read_text(encoding="utf-8"))
            tiers = set(args.tiers.split(","))
            ids = [item["item"].split("/", 1)[1] for item in selection["items"]
                   if item["item"].startswith(args.publisher + "/") and item.get("override", item.get("tier")) in tiers]
        failed = fetch(args.publisher, config, ids)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

"""Fetch auto captions ("English CC") for a Skool-native (Mux) video from its HLS manifest.

Skool lesson fetches return pageProps.video = {id, playbackId, playbackToken, expire, duration, ...}.
The master playlist https://stream.video.skool.com/<playbackId>.m3u8?token=<playbackToken> lists a
SUBTITLES group whose subtitles.m3u8 points at WebVTT segments. Plain HTTPS with the signed token;
no cookies, and not Skool's own API. Tokens expire after ~1 day, so fetch the lesson right before.

lines(video, cache_dir) -> [{start, end, text: [str]}] (the shape wistia_to_raw.paragraphs expects),
or [] if the video has no English captions track.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib

import json
import pathlib
import re
import time
import urllib.parse
import urllib.request

# The token carries a Mux playback restriction (referrer domain), so send what the in-page player sends.
UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.skool.com/", "Origin": "https://www.skool.com"}


def _get(url: str) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def _ts(s: str) -> float:
    parts = s.replace(",", ".").split(":")
    return sum(float(p) * 60 ** i for i, p in enumerate(reversed(parts)))


def parse_vtt(text: str) -> list[dict]:
    cues, out = re.split(r"\r?\n\r?\n", text), []
    for cue in cues:
        m = re.search(r"([\d:.]+)\s+-->\s+([\d:.]+)", cue)
        if not m:
            continue
        body = cue[m.end():].split("\n", 1)[1] if "\n" in cue[m.end():] else ""
        body = re.sub(r"<[^>]+>", "", body).replace("\n", " ").strip()
        if body:
            out.append({"start": _ts(m.group(1)), "end": _ts(m.group(2)), "text": [body]})
    return out


def lines(video: dict, cache_dir: pathlib.Path) -> list[dict]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"{video['id']}.captions.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    if float(video.get("expire") or 0) < time.time() + 300:
        raise RuntimeError("Mux playback token expired: re-fetch the lesson first")
    master_url = f"https://stream.video.skool.com/{video['playbackId']}.m3u8?token={video['playbackToken']}"
    master = _get(master_url)
    subs = [ln for ln in master.splitlines() if ln.startswith("#EXT-X-MEDIA") and "TYPE=SUBTITLES" in ln]
    subs.sort(key=lambda ln: 'LANGUAGE="en' not in ln)
    if not subs or 'LANGUAGE="en' not in subs[0]:
        cache.write_text("[]", encoding="utf-8")
        return []
    sub_url = urllib.parse.urljoin(master_url, re.search(r'URI="([^"]+)"', subs[0]).group(1))
    playlist = _get(sub_url)
    seg_urls = [urllib.parse.urljoin(sub_url, ln) for ln in playlist.splitlines() if ln and not ln.startswith("#")]
    cues, seen = [], set()
    for u in seg_urls:
        for c in parse_vtt(_get(u)):
            key = (round(c["start"], 2), c["text"][0])
            if key not in seen:  # segments can repeat a cue at their boundaries
                seen.add(key)
                cues.append(c)
        time.sleep(0.2)
    cues.sort(key=lambda c: c["start"])
    cache.write_text(json.dumps(cues, ensure_ascii=False), encoding="utf-8")
    return cues


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(ap)
    ap.add_argument("vtt", help="parse a saved UTF-8 WebVTT file (offline)")
    args = ap.parse_args()
    brainlib.brain_dir(args.brain)
    print(json.dumps(parse_vtt(Path(args.vtt).read_text(encoding="utf-8")), ensure_ascii=False, indent=2))

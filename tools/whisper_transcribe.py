"""Transcribe uncaptioned Wistia media into media/whisper/ using CUDA when available, otherwise CPU.

Model and spelling prompt come from crawl.yaml. --dry-run reports uncached media."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from source_helpers import configure, cache_key

import argparse
import json
import pathlib
import subprocess
import time
import urllib.request
import wave

import yaml

from wistia_to_raw import fetch_json
from whisper_runtime import load_cuda_dlls, model_options


def uncaptioned_media() -> list[str]:
    o = yaml.safe_load((BRAIN / "outline.yaml").read_text(encoding="utf-8"))
    ids = []

    def walk(cats):
        for c in cats or []:
            for l in c.get("lessons") or []:
                v = str(l.get("video") or "")
                if v.startswith("wistia:") and not l.get("captions"):
                    ids.append(v.split(":", 1)[1])
            walk(c.get("categories"))

    for p in o["products"]:
        walk(p["categories"])
    return ids


def audio_for(media_id: str, media: dict):
    import numpy as np

    mp4 = CACHE / f"{media_id}.mp4"
    wav = CACHE / f"{media_id}.16k.wav"
    if not wav.exists():
        if not mp4.exists():
            mp4s = [a for a in media["assets"] if a.get("ext") == "mp4" and a.get("type", "").endswith("video") and a.get("size")]
            asset = min(mp4s, key=lambda a: a["size"])
            req = urllib.request.Request(asset["url"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r, open(mp4, "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
        subprocess.run([brainlib.executable("ffmpeg"), "-nostdin", "-loglevel", "error", "-y", "-i", str(mp4), "-vn", "-ac", "1", "-ar", "16000", str(wav)], check=True)
        mp4.unlink()
    # Load the PCM ourselves; faster-whisper's PyAV decoder breaks on newer av releases.
    with wave.open(str(wav)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def main() -> None:
    global BRAIN, CACHE, OUT, PROMPT
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--all-uncaptioned", action="store_true")
    ap.add_argument("--model")
    ap.add_argument("--anti-loop", action="store_true",
                    help="keep previous-text conditioning (punctuation) but add a repetition penalty and a stricter "
                         "compression-ratio fallback; preferred fix for repetition loops")
    ap.add_argument("--no-prev-text", action="store_true",
                    help="don't condition on previous text (fixes repetition loops; re-run a media after deleting its cache)")
    args = ap.parse_args()
    BRAIN, config = configure(args)
    whisper = config.get("whisper") or {}
    args.model = args.model or whisper.get("model", "large-v3-turbo")
    PROMPT = whisper.get("prompt") or None
    CACHE, OUT = BRAIN / "media" / "wistia", BRAIN / "media" / "whisper"
    ids = args.ids or (uncaptioned_media() if args.all_uncaptioned else [])
    for media_id in ids:
        cache_key(media_id)
    todo = [m for m in ids if not (OUT / f"{m}.json").exists()]
    print(f"{len(ids)} media, {len(todo)} to transcribe", flush=True)
    if args.dry_run or not todo:
        return
    OUT.mkdir(parents=True, exist_ok=True)

    load_cuda_dlls()
    from faster_whisper import WhisperModel

    model = WhisperModel(args.model, **model_options())
    total_audio = total_wall = 0.0
    for i, mid in enumerate(todo, 1):
        media = fetch_json("medias", mid, BRAIN)["media"]
        t0 = time.time()
        audio = audio_for(mid, media)
        t1 = time.time()
        segments, info = model.transcribe(audio, language="en", vad_filter=True, beam_size=5, initial_prompt=PROMPT,
                                          condition_on_previous_text=not args.no_prev_text,
                                          **({"repetition_penalty": 1.05, "compression_ratio_threshold": 2.0} if args.anti_loop else {}))
        segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments]
        t2 = time.time()
        (OUT / f"{mid}.json").write_text(json.dumps({
            "media_id": mid, "name": media.get("name"), "duration": media["duration"],
            "model": args.model, "condition_on_previous_text": not args.no_prev_text, "anti_loop": args.anti_loop, "language": info.language, "segments": segs,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        (CACHE / f"{mid}.16k.wav").unlink()
        total_audio += media["duration"]
        total_wall += t2 - t0
        words = sum(len(s["text"].split()) for s in segs)
        print(f"[{i}/{len(todo)}] {mid} {media['duration'] / 60:.1f} min: fetch {t1 - t0:.0f}s, "
              f"asr {t2 - t1:.0f}s, {len(segs)} segs, {words} words", flush=True)
    print(f"done: {total_audio / 3600:.2f} h audio in {total_wall / 60:.1f} min "
          f"({total_audio / max(total_wall, 1):.0f}x realtime)")


if __name__ == "__main__":
    main()

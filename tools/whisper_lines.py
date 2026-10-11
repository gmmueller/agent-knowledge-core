"""Transcribe a media URL with faster-whisper and cache timestamped lines.

Downloads via yt-dlp and decodes with ffmpeg. Run only one GPU job at a time."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from source_helpers import configure, brain_path, cache_key

import json
import os
import pathlib
import subprocess

_model = None


def _load_cuda_dlls() -> None:
    # The nvidia-cublas/cudnn wheels ship their DLLs outside the Windows search path.
    import nvidia

    for base in nvidia.__path__:
        for bin_dir in pathlib.Path(base).glob("*/bin"):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ["PATH"]


def _get_model(model):
    global _model
    if _model is None or _model[0] != model:
        _load_cuda_dlls()
        from faster_whisper import WhisperModel

        _model = (model, WhisperModel(model, device="cuda", compute_type="float16"))
    return _model[1]


def lines(key: str, url: str, media_dir: pathlib.Path, prompt: str = "", model: str = "large-v3-turbo") -> list[dict]:
    import numpy as np

    cache_key(key)
    media_dir.mkdir(parents=True, exist_ok=True)
    cache = media_dir / f"{key}.whisper.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    audio = media_dir / f"{key}.m4a"
    if not audio.exists():
        subprocess.run(["yt-dlp", "-f", "bestaudio/best", "-x", "--audio-format", "m4a", "-o", str(media_dir / f"{key}.%(ext)s"), url],
                       check=True, capture_output=True)
    pcm = subprocess.run(["ffmpeg", "-nostdin", "-i", str(audio), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         check=True, capture_output=True).stdout
    samples = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
    segs, _ = _get_model(model).transcribe(samples, language="en", vad_filter=True, initial_prompt=prompt or None)
    out = [{"start": s.start, "end": s.end, "text": [s.text.strip()]} for s in segs if s.text.strip()]
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    audio.unlink(missing_ok=True)
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("--key", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--media-dir", default="media/whisper-lines")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    brain, config = configure(args)
    media_dir = brain_path(brain, args.media_dir)
    cache_key(args.key)
    if args.dry_run:
        print("cached" if (media_dir / f"{args.key}.whisper.json").exists() else "pending transcription")
        return
    whisper = config.get("whisper") or {}
    result = lines(args.key, args.url, media_dir, whisper.get("prompt", ""), whisper.get("model", "large-v3-turbo"))
    print(f"{len(result)} transcript lines")


if __name__ == "__main__":
    main()

"""Gather measured video facts and frames, without annotation or judgments.

Usage: python -I tools/example_frames.py --workspace <workspace> <publisher> <yt-id ...>
Opening lines retain JSON3 segment timing; manual caption phrases without word
offsets remain phrases (word times cannot be recovered from that track).
"""
import argparse
import datetime as dt
import importlib.metadata
import json
import math
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib
import library_raw as lr
from yt_to_raw import fetch_captions, json3_lines

import cv2
import yaml
from PIL import Image, ImageDraw
from scenedetect import detect
from scenedetect.detectors import AdaptiveDetector


def frame_numbers(cuts, fps, count):
    opening = sorted({round(t * fps) for t in (0, .5, 1, 2, 3) if round(t * fps) < count})
    extra = sorted(set(cuts) - set(opening))
    budget = 40 - len(opening)
    if len(extra) > budget:
        extra = [extra[round(i * (len(extra) - 1) / (budget - 1))] for i in range(budget)]
    return sorted(opening + extra)


def contact_sheets(frames, folder):
    sheets = []
    for offset in range(0, len(frames), 20):
        batch = frames[offset:offset + 20]
        sheet = Image.new('RGB', (5 * 240, math.ceil(len(batch) / 5) * 344), '#181818')
        draw = ImageDraw.Draw(sheet)
        for i, frame in enumerate(batch):
            with Image.open(lr.ROOT / frame['path']) as image:
                image.thumbnail((232, 312))
                x, y = (i % 5) * 240, (i // 5) * 344
                sheet.paste(image, (x + (240 - image.width) // 2, y))
                draw.text((x + 8, y + 320), f"{frame['t']:.3f} s", fill='white')
        path = folder / ('sheet.jpg' if offset == 0 else 'sheet-2.jpg')
        sheet.save(path, quality=90)
        sheets.append(path.relative_to(lr.ROOT).as_posix())
    return sheets


def prepare(publisher, item):
    video_id = item[3:]
    url = f'https://www.youtube.com/watch?v={video_id}'
    video = lr.video_path(publisher, video_id)
    video.parent.mkdir(parents=True, exist_ok=True)
    info_path = video.with_suffix('.info.json')
    if not video.exists():
        subprocess.run(['yt-dlp', '--no-playlist', '-f',
                        'bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/b[height<=1080]',
                        '--merge-output-format', 'mp4', '--recode-video', 'mp4',
                        '--write-info-json', '-o', str(video), url], check=True)
    if not info_path.exists():
        result = subprocess.run(['yt-dlp', '--no-playlist', '--skip-download', '--dump-single-json', url],
                                check=True, capture_output=True, text=True, encoding='utf-8')
        info_path.write_text(result.stdout, encoding='utf-8')
    info = json.loads(info_path.read_text(encoding='utf-8'))
    cap = cv2.VideoCapture(str(video))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width, height = (int(cap.get(p)) for p in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT))
        if not cap.isOpened() or fps <= 0 or count <= 0 or min(width, height) <= 0:
            raise ValueError(f'cannot decode video: {video}')
        duration = count / fps
        # shortcut: small picture-in-picture cuts can be missed; use region detection if those matter.
        scenes = detect(str(video), AdaptiveDetector(adaptive_threshold=3.0,
                        min_content_val=15.0, min_scene_len=max(1, round(fps * .1))))
        cut_frames = [start.frame_num for start, _ in scenes if start.frame_num > 0]
        cuts = [round(n / fps, 6) for n in cut_frames]
        folder = lr.pub_dir(publisher) / 'media' / 'frames' / video_id
        folder.mkdir(parents=True, exist_ok=True)
        frames = []
        for n in frame_numbers(cut_frames, fps, count):
            cap.set(cv2.CAP_PROP_POS_FRAMES, n)
            ok, pixels = cap.read()
            if not ok:
                raise ValueError(f'cannot read frame {n}: {video}')
            image = Image.fromarray(cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB))
            if image.height > 720:
                image = image.resize((round(image.width * 720 / image.height), 720), Image.Resampling.LANCZOS)
            t = round(n / fps, 6)
            path = folder / f'{t:.6f}.jpg'
            image.save(path, quality=90)
            frames.append({'t': t, 'path': path.relative_to(lr.ROOT).as_posix()})
    finally:
        cap.release()
    sheets = contact_sheets(frames, folder)
    captions, kind = fetch_captions(video_id, video.parent)
    opening, transcript = [], ''
    if captions:
        lines = json3_lines(captions)
        transcript = ' '.join(' '.join(line['text']) for line in lines)
        for event in json.loads(captions.read_text(encoding='utf-8')).get('events', []):
            for segment in event.get('segs') or []:
                start = (event.get('tStartMs', 0) + segment.get('tOffsetMs', 0)) / 1000
                text = lr.clean_field(segment.get('utf8', ''))
                if start < 10 and text:
                    opening.append({'start': start, 'text': text})
        opening.sort(key=lambda line: line['start'])
    try:
        importlib.metadata.version('opencv-python-headless')
        opencv_package = 'opencv-python-headless'
    except importlib.metadata.PackageNotFoundError:
        opencv_package = 'opencv-python'
    versions = {name: importlib.metadata.version(name) for name in ('scenedetect', opencv_package, 'pillow')}
    versions['yt-dlp'] = subprocess.run(['yt-dlp', '--version'], check=True, capture_output=True,
                                      text=True).stdout.strip()
    data = dict(item=f'{publisher}/{item}', url=url, title=info['title'], duration_s=duration,
                fps=fps, resolution={'width': width, 'height': height},
                aspect='vertical' if height > width else 'horizontal', cuts=cuts,
                shot_count=len(cuts) + 1, avg_shot_s=duration / (len(cuts) + 1),
                cuts_per_min=len(cuts) * 60 / duration, first_cut_s=cuts[0] if cuts else None,
                frames=frames, sheets=sheets, opening_lines=opening, transcript=transcript,
                captions=kind or 'none', measured=dt.date.today().isoformat(), tool_versions=versions,
                detector={'name': 'AdaptiveDetector', 'adaptive_threshold': 3.0,
                          'min_content_val': 15.0, 'min_scene_len_frames': max(1, round(fps * .1))})
    out = lr.pub_dir(publisher) / 'examples' / f'{item}.yaml'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')
    with (lr.pub_dir(publisher) / 'crawl-log.md').open('a', encoding='utf-8') as log:
        log.write(f'\n## [{dt.date.today().isoformat()}] example-frames | {item}\n\n'
                  f'{len(cuts)} detected cuts; {len(frames)} frames; captions: {kind or "none"}. '
                  f'Facts: examples/{item}.yaml. AdaptiveDetector ratio 3, content floor 15, minimum shot 0.1 s.\n')
    print(f'{publisher}/{item}: {len(cuts)} cuts, {len(frames)} frames, captions={kind or "none"}', flush=True)


def self_check():
    assert frame_numbers([], 30, 10) == [0]
    assert frame_numbers([15, 16, 31], 30, 120) == [0, 15, 16, 30, 31, 60, 90]
    selected = frame_numbers(list(range(1, 1000)), 30, 1000)
    assert len(selected) == 40 and selected[-1] == 999
    assert {0, 15, 30, 60, 90}.issubset(selected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    brainlib.add_workspace_arg(parser)
    parser.add_argument('publisher')
    parser.add_argument('items', nargs='+')
    args = parser.parse_args()
    lr.init(args.workspace)
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', args.publisher):
        parser.error('publisher must be kebab-case ASCII')
    if any(not re.fullmatch(r'yt-[A-Za-z0-9_-]{11}', item) for item in args.items):
        parser.error('items must be yt-<11-character YouTube video ID>')
    self_check()
    failures = 0
    for item in args.items:
        try:
            prepare(args.publisher, item)
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            print(f'{item}: {error}', file=sys.stderr)
            failures += 1
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()

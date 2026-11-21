"""Ungated ECAPA speaker pass. Run with python -I tools/diarize.py --workspace <workspace>.

Requires torch/torchaudio 2.8 (CUDA wheels), speechbrain and scikit-learn.
--all PUBLISHER skips existing diar.json; --speakers 1..6 overrides estimation.
--whisper-words opts into cached GPU word alignment; it did not improve this acceptance sample enough to become default.
"""
import argparse
import copy
import difflib
import json
import math
import os
import pathlib
import re
import subprocess
import sys
import time
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import brainlib
import library_raw as lr


def validate(publisher, item):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", publisher):
        raise ValueError("publisher must be a kebab-case slug")
    if not re.fullmatch(r"(?:yt|pod)-[A-Za-z0-9_-]+", item):
        raise ValueError("item must be a yt- or pod- id without path separators")


def read_lines(publisher, item):
    validate(publisher, item)
    data = json.loads(lr.staging_path(publisher, item, "lines.json").read_text(encoding="utf-8"))
    if data["item"] != item or not isinstance(data["front"], dict) or not data["lines"]:
        raise ValueError("invalid or empty staging item")
    previous = -1
    for line in data["lines"]:
        start, end = line["start"], line["end"]
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (start, end)):
            raise ValueError("caption times must be finite numbers")
        if start < previous or start < 0 or end <= start:
            raise ValueError("caption times must be ordered and end after start")
        text = line["text"]
        if not isinstance(text, str) and not (isinstance(text, list) and all(isinstance(x, str) for x in text)):
            raise ValueError("caption text must be a string or list of strings")
        previous = start
    return data


def audio_for(publisher, item, url):
    path = lr.audio_path(publisher, item.removeprefix("yt-"))
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([brainlib.executable("yt-dlp"), "--no-playlist", "-f", "bestaudio", "-x", "--audio-format", "m4a",
                        "-o", str(path.with_suffix(".%(ext)s")), url], check=True)
    if not path.exists() or not path.stat().st_size:
        raise ValueError(f"missing or empty audio: {path}")
    import numpy as np
    result = subprocess.run([brainlib.executable("ffmpeg"), "-nostdin", "-loglevel", "error", "-i", str(path),
                             "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"],
                            check=True, stdout=subprocess.PIPE)
    return np.frombuffer(result.stdout, dtype="<f4").copy()


def cluster(embeddings, count=None):
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import silhouette_score

    n = len(embeddings)
    sample = embeddings[np.linspace(0, n - 1, min(n, 2000), dtype=int)]
    if count and count > len(sample):
        raise ValueError("not enough speech windows for requested speaker count")
    candidates = [count] if count else range(2, min(6, len(sample) - 1) + 1)
    best_score, best_labels = 0.10, np.zeros(len(sample), dtype=int)
    scores = {}
    for k in candidates:
        if k == 1:
            labels = np.zeros(len(sample), dtype=int)
        else:
            # Ward on unit embeddings avoids isolating noisy singletons before splitting real voices.
            labels = AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(sample)
        score = silhouette_score(sample, labels, metric="cosine") if 1 < k < len(sample) else 0
        scores[k] = round(float(score), 4)
        adjusted = score - 0.015 * (k - 2)
        substantial = min(np.bincount(labels)) >= max(3, len(sample) * 0.025)
        if count or (substantial and adjusted > best_score):
            best_score, best_labels = adjusted, labels
    centers = np.stack([sample[best_labels == k].mean(axis=0) for k in sorted(set(best_labels))])
    centers /= np.maximum(np.linalg.norm(centers, axis=1, keepdims=True), 1e-8)
    if not count and len(centers) > 1 and np.max(1 - centers @ centers.T) < 0.12:
        centers = sample.mean(axis=0, keepdims=True)
        centers /= np.maximum(np.linalg.norm(centers, axis=1, keepdims=True), 1e-8)
    return centers, scores


def smooth(costs, times):
    """Viterbi smoothing: changing voice costs 0.12 cosine distance, except across gaps."""
    import numpy as np
    n, k = costs.shape
    back = np.zeros((n, k), dtype=int)
    previous = costs[0].copy()
    for i in range(1, n):
        penalty = 0.12 if times[i] - times[i - 1] < 2 else 0
        transitions = previous[:, None] + penalty * (1 - np.eye(k))
        back[i] = transitions.argmin(axis=0)
        previous = costs[i] + transitions[back[i], np.arange(k)]
    labels = np.zeros(n, dtype=int)
    labels[-1] = previous.argmin()
    for i in range(n - 1, 0, -1):
        labels[i - 1] = back[i, labels[i]]
    return labels


def assign_lines(lines, turns):
    out = []
    cursor = 0
    for index, line in enumerate(lines):
        start, end = line["start"], line["end"]
        text = lr.clean_field(line["text"] if isinstance(line["text"], str) else " ".join(line["text"]))
        if not text:
            continue
        while cursor + 1 < len(turns) and turns[cursor][1] <= start:
            cursor += 1
        overlaps, pieces = {}, []
        for a, b, speaker in turns[cursor:]:
            if a >= end:
                break
            a, b = max(a, start), min(b, end)
            if b > a:
                overlaps[speaker] = overlaps.get(speaker, 0) + b - a
                pieces.append((a, b, speaker))
        speaker = max(overlaps, key=overlaps.get) if overlaps else turns[cursor][2]
        words = text.split()
        # shortcut: untimed words are split proportionally; use word alignment for precise turn boundaries.
        cuts = [round((b - start) / (end - start) * len(words)) for _, b, _ in pieces[:-1]]
        bounds = [0, *cuts, len(words)]
        can_split = index + 1 == len(lines) or end <= lines[index + 1]["start"]
        if can_split and len(pieces) > 1 and all(b - a >= 0.8 for a, b, _ in pieces) and all(
                bounds[i + 1] > bounds[i] for i in range(len(pieces))):
            for i, (a, b, spk) in enumerate(pieces):
                out.append({"start": round(a, 3), "end": round(b, 3),
                            "text": " ".join(words[bounds[i]:bounds[i + 1]]), "speaker": spk})
        else:
            out.append({"start": start, "end": end, "text": text, "speaker": speaker})
    return out


def caption_text(lines):
    return lr.clean_field(" ".join(lr.clean_field(line["text"] if isinstance(line["text"], str)
                                              else " ".join(line["text"])) for line in lines))


def json3_turns(document):
    """Keep text order; segment offsets anchor words and >> turn boundaries."""
    events = [e for e in document.get("events", []) if e.get("segs") and e.get("dDurationMs", 0) > 0]
    tokens, estimated, offsets = [], 0, 0
    for index, event in enumerate(events):
        start = event["tStartMs"] / 1000
        end = start + event["dDurationMs"] / 1000
        if index + 1 < len(events):
            end = min(end, events[index + 1]["tStartMs"] / 1000)
        if end <= start:
            end = start + 0.01  # overlapping events still carry words; keep them (raw must match the captions)
        # Concatenate segments before tokenizing: segment boundaries can fall inside a word.
        text = "".join(s.get("utf8", "") for s in event["segs"])
        matches = list(re.finditer(r">>|(?:(?!>>)\S)+", text))
        if not matches:
            continue
        anchors = {0: start, len(matches): end}
        position = 0
        for segment in event["segs"]:
            if "tOffsetMs" in segment:
                offsets += 1
                token_index = next((i for i, m in enumerate(matches) if m.start() >= position), len(matches))
                if token_index < len(matches):
                    anchors[token_index] = min(end, max(start, start + segment["tOffsetMs"] / 1000))
            position += len(segment.get("utf8", ""))
        ordered = sorted(anchors)
        if any(anchors[a] > anchors[b] for a, b in zip(ordered, ordered[1:])):
            raise ValueError("non-monotonic json3 word offsets")
        for left, right in zip(ordered, ordered[1:]):
            words = sum(m.group() != ">>" for m in matches[left:right])
            # shortcut: multiword segments without offsets use proportional timing; prefer word-timed captions.
            step = (anchors[right] - anchors[left]) / max(words, 1)
            spoken = 0
            for i in range(left, right):
                value = matches[i].group()
                timestamp = anchors[left] + spoken * step
                if value == ">>":
                    estimated += int(i not in anchors and spoken > 0)
                    tokens.append({"text": value, "start": timestamp, "end": timestamp})
                else:
                    tokens.append({"text": value, "start": timestamp, "end": timestamp + step})
                    spoken += 1
    if not any(token["text"] == ">>" for token in tokens):
        return [], {"offset_segments": offsets, "estimated_boundaries": 0}
    lines, current, pending_start = [], [], None
    for token in tokens:
        if token["text"] == ">>":
            if current:
                lines.append({"start": pending_start, "end": token["start"],
                              "text": " ".join(w["text"] for w in current), "words": current})
                current = []
            pending_start = token["start"]
        else:
            if pending_start is None:
                pending_start = token["start"]
            current.append(token)
    if current:
        lines.append({"start": pending_start, "end": current[-1]["end"],
                      "text": " ".join(w["text"] for w in current), "words": current})
    # A turn whose words share one timestamp (two '>>' at the same offset) has no span:
    # fold it into the previous turn (or the next one) rather than fail the item.
    merged = []
    for line in lines:
        if line["end"] <= line["start"] and merged:
            merged[-1]["text"] += " " + line["text"]
            merged[-1]["words"] += line["words"]
            merged[-1]["end"] = max(merged[-1]["end"], line["end"])
        else:
            merged.append(line)
    if len(merged) > 1 and merged[0]["end"] <= merged[0]["start"]:
        first = merged.pop(0)
        merged[0] = {**merged[0], "start": first["start"], "text": first["text"] + " " + merged[0]["text"],
                     "words": first["words"] + merged[0]["words"]}
    lines = merged
    if any(line["end"] <= line["start"] for line in lines):
        raise ValueError("json3 turn has no positive timed span")
    return lines, {"offset_segments": offsets, "estimated_boundaries": estimated}


def caption_turns(publisher, item, data):
    if not item.startswith("yt-") or data["front"].get("method") != "captions":
        return [], None
    cache = lr.pub_dir(publisher) / "media" / "captions"
    video_id = item[3:]
    paths = sorted(cache.glob(f"{video_id}.*.json3"))
    if not paths:
        from yt_to_raw import fetch_captions
        path, _ = fetch_captions(video_id, cache)
        paths = [path] if path else []
    expected = caption_text(data["lines"])
    matching = []
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        source_lines = [{"text": "".join(s.get("utf8", "") for s in e.get("segs", []))}
                        for e in document.get("events", []) if e.get("segs") and e.get("dDurationMs", 0) > 0]
        if caption_text(source_lines) != expected:
            continue
        matching.append((path, document))
    matching.sort(key=lambda pair: sum("tOffsetMs" in s for e in pair[1].get("events", [])
                                      for s in e.get("segs", [])), reverse=True)
    for path, document in matching:
        lines, timing = json3_turns(document)
        if lines:
            timing["json3"] = path.relative_to(lr.ROOT).as_posix()
            if caption_text(lines) != lr.clean_field(expected.replace(">>", " ")):
                raise ValueError("json3 turn splitting changed caption text")
            if timing["estimated_boundaries"]:
                print(f"{item}: WARNING {timing['estimated_boundaries']} inline boundaries lack word offsets; "
                      "using proportional timing", flush=True)
            return lines, timing
        return [], None
    if ">>" in expected:
        raise ValueError("need matching cached json3 to time speaker markers")
    return [], None


def whisper_words(publisher, item, audio):
    """Cache local GPU ASR words for timing only; captions remain the transcript."""
    path = lr.staging_path(publisher, item, "words.json")
    media = lr.audio_path(publisher, item.removeprefix("yt-"))
    stat = media.stat()
    fingerprint = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("item") != item or cached.get("audio") != fingerprint or cached.get("model") != "large-v3-turbo":
            raise ValueError(f"stale Whisper word cache: {path}; move it aside before retrying")
        print(f"{item}: using cached Whisper words", flush=True)
        return cached
    from whisper_runtime import model_options
    options = model_options()
    from faster_whisper import WhisperModel

    begun = time.perf_counter()
    model = WhisperModel("large-v3-turbo", **options)
    loaded = time.perf_counter()
    segments, _ = model.transcribe(audio, language="en", word_timestamps=True, vad_filter=True,
                                   beam_size=5, condition_on_previous_text=False, repetition_penalty=1.05)
    words, progress = [], 0
    for segment in segments:
        words.extend({"word": w.word, "start": w.start, "end": w.end} for w in segment.words or [])
        if segment.end >= progress:
            print(f"{item}: Whisper words through {lr.ts(segment.end)}", flush=True)
            progress = segment.end + 180
    if not words:
        raise ValueError("Whisper produced no words")
    elapsed = time.perf_counter() - begun
    cached = {"item": item, "model": "large-v3-turbo", "audio": fingerprint,
              "audio_s": len(audio) / 16000, "runtime_s": round(elapsed, 2),
              "transcribe_s": round(time.perf_counter() - loaded, 2), "words": words}
    temporary = path.with_suffix(".json.tmp")
    try:
        temporary.write_text(json.dumps(cached, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"{item}: {len(words)} Whisper words, {elapsed:.1f}s", flush=True)
    return cached


def align_caption_words(lines, asr_words):
    """Monotonic normalized/fuzzy matching; only timing changes, never caption tokens."""
    result = copy.deepcopy(lines)
    tokens = [word for line in result for word in line["words"]]
    def normalize(text):
        text = unicodedata.normalize("NFKD", text.casefold())
        return re.sub(r"[^a-z0-9]", "", text)

    speech, in_tag = [], False
    for i, word in enumerate(tokens):
        if "[" in word["text"]:
            in_tag = True
        value = "" if in_tag else normalize(word["text"])
        if "]" in word["text"]:
            in_tag = False
        if value:
            speech.append((i, value))
    previous = -1
    asr = []
    for word in asr_words:
        a, b = word["start"], word["end"]
        if not all(isinstance(t, (int, float)) and math.isfinite(t) for t in (a, b)) or not 0 <= a <= b or a < previous:
            raise ValueError("invalid or non-monotonic Whisper word timing")
        previous = a
        value = normalize(word["word"])
        if value and b > a:
            asr.append((word, value))
    matched = set()
    matcher = difflib.SequenceMatcher(None, [v for _, v in speech], [v for _, v in asr], autojunk=False)
    for operation, left, right, a, b in matcher.get_opcodes():
        if operation not in {"equal", "replace"}:
            continue
        for (index, caption), (word, heard) in zip(speech[left:right], asr[a:b]):
            if operation == "replace" and difflib.SequenceMatcher(None, caption, heard).ratio() < .75:
                continue
            # Repeated short words can match a distant utterance; reject implausible time jumps.
            if abs(tokens[index]["start"] - word["start"]) > 8:
                continue
            tokens[index]["start"], tokens[index]["end"] = word["start"], word["end"]
            matched.add(index)
    # Unmatched tokens retain estimated timing, constrained by adjacent real anchors.
    next_start = float("inf")
    for i in range(len(tokens) - 1, -1, -1):
        word = tokens[i]
        if i in matched:
            next_start = word["start"]
        else:
            word["start"] = min(word["start"], next_start)
            word["end"] = min(word["end"], next_start)
    previous = 0
    for word in tokens:
        word["start"] = max(previous, word["start"])
        word["end"] = max(word["start"], word["end"])
        previous = word["start"]
    speech_indices = {i for i, _ in speech}
    starts, resolved, position = [], [], 0
    for line in result:
        first = next((i for i in range(position, position + len(line["words"])) if i in speech_indices), None)
        real = first is not None and first in matched
        starts.append(tokens[first]["start"] if real else line["start"])
        resolved.append(real)
        position += len(line["words"])
    # An unmatched boundary between real anchors must not invert their order.
    for i in range(len(starts)):
        lower = starts[i - 1] + .001 if i else 0
        upper = next((starts[j] - .001 * (j - i) for j in range(i + 1, len(starts)) if resolved[j]), float("inf"))
        adjusted = max(lower, min(starts[i], upper))
        if adjusted != starts[i]:
            resolved[i] = False
        starts[i] = adjusted
    last_end = max(result[-1]["end"], tokens[-1]["end"], starts[-1] + .001)
    for i, line in enumerate(result):
        line["start"], line["end"] = starts[i], starts[i + 1] if i + 1 < len(starts) else last_end
        for word in line["words"]:
            word["start"] = max(line["start"], min(word["start"], line["end"]))
            word["end"] = max(word["start"], min(word["end"], line["end"]))
    estimated = [line["start"] for line, real in zip(result[1:], resolved[1:]) if not real]
    return result, {"matched_tokens": len(matched), "speech_tokens": len(speech),
                    "matched_boundaries": sum(resolved[1:]), "estimated_boundaries": len(estimated),
                    "estimated_boundary_starts": estimated}


def assign_turns(lines, turns):
    out = []
    for line in lines:
        start, end = line["start"], line["end"]
        words = line["words"]
        cuts = set()
        if end - start > 20:
            sentence_ends = [(i + 1, word["end"]) for i, word in enumerate(words[:-1])
                             if lr.SENTENCE_END.search(word["text"]) and start + 3 < word["end"] < end - 3]
            for _, boundary, _ in turns[:-1]:
                if start + 3 < boundary < end - 3 and sentence_ends:
                    cuts.add(min(sentence_ends, key=lambda p: abs(p[1] - boundary))[0])
        bounds = [0, *sorted(cuts), len(words)]
        for left, right in zip(bounds, bounds[1:]):
            a = start if left == 0 else words[left - 1]["end"]
            b = end if right == len(words) else words[right - 1]["end"]
            overlaps = {}
            for x, y, speaker in turns:
                overlap = min(b, y) - max(a, x)
                if overlap > 0:
                    overlaps[speaker] = overlaps.get(speaker, 0) + overlap
            if not overlaps:
                raise ValueError("caption turn has no acoustic overlap")
            out.append({"start": a, "end": b, "text": " ".join(w["text"] for w in words[left:right]),
                        "speaker": max(overlaps, key=overlaps.get)})
    return out


def marker_windows(lines, audio, model, centers, names, original_turns):
    """Classify windows clipped to caption turns, avoiding the adjacent voice's audio."""
    import numpy as np
    import torch

    samples, spans, lengths = [], [], []
    for line in lines:
        a, b = line["start"], min(line["end"], len(audio) / 16000)
        if b - a < 0.1:
            continue
        times = np.arange(a + .375, b, .75).tolist() or [(a + b) / 2]
        edges = [a, *[(x + y) / 2 for x, y in zip(times, times[1:])], b]
        for i, center in enumerate(times):
            first = int(max(a, center - 1.5) * 16000)
            last = min(int(min(b, center + 1.5) * 16000), first + 48000)
            chunk = audio[first:last]
            lengths.append(len(chunk) / 48000)
            samples.append(np.pad(chunk, (0, 48000 - len(chunk))))
            spans.append((edges[i], edges[i + 1]))
    turns = []
    with torch.inference_mode():
        for i in range(0, len(samples), 8):
            batch = torch.from_numpy(np.stack(samples[i:i + 8])).to(model.device)
            lens = torch.tensor(lengths[i:i + 8], device=model.device)
            vectors = model.encode_batch(batch, wav_lens=lens).squeeze(1).float().cpu().numpy()
            vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-8)
            for (a, b), label in zip(spans[i:i + 8], (vectors @ centers.T).argmax(axis=1)):
                speaker = names[label]
                if turns and turns[-1][2] == speaker and turns[-1][1] == a:
                    turns[-1] = (turns[-1][0], b, speaker)
                else:
                    turns.append((a, b, speaker))
    # Extremely short caption turns have too little audio for a reliable standalone embedding.
    for line in lines:
        if min(line["end"], len(audio) / 16000) - line["start"] < .1:
            for a, b, speaker in original_turns:
                x, y = max(a, line["start"]), min(b, line["end"])
                if y > x:
                    turns.append((x, y, speaker))
    return sorted(turns)


def diarize(publisher, item, model, count, use_whisper=False):
    import numpy as np
    import torch

    data = read_lines(publisher, item)
    begun = time.perf_counter()
    caption_lines, turn_timing = caption_turns(publisher, item, data)
    audio = audio_for(publisher, item, data["front"]["url"])
    duration = len(audio) / 16000
    if caption_lines and use_whisper:
        cache = whisper_words(publisher, item, audio)
        caption_lines, alignment = align_caption_words(caption_lines, cache["words"])
        turn_timing.update(alignment)
        turn_timing["whisper_words"] = lr.staging_path(publisher, item, "words.json").relative_to(lr.ROOT).as_posix()
        turn_timing["whisper_runtime_s"] = cache["runtime_s"]
        print(f"{item}: Whisper aligned {alignment['matched_tokens']}/{alignment['speech_tokens']} tokens; "
              f"{alignment['estimated_boundaries']} boundaries still estimated", flush=True)
    if max(line["start"] for line in data["lines"]) >= duration + 1:
        raise ValueError("caption starts extend beyond audio")
    times, samples = [], []
    intervals = [(line["start"], line["end"]) for line in data["lines"] if lr.clean_field(line["text"])]
    cursor = 0
    for center in np.arange(0.75, duration, 0.75):
        while cursor + 1 < len(intervals) and intervals[cursor][1] <= center - 0.75:
            cursor += 1
        if intervals[cursor][0] > center + 0.75 or intervals[cursor][1] < center - 0.75:
            continue
        chunk = audio[max(0, int((center - 1.5) * 16000)):min(len(audio), int((center + 1.5) * 16000))]
        if len(chunk) < 8000 or np.sqrt(np.mean(chunk ** 2)) < 0.003:
            continue
        times.append(float(center))
        samples.append(np.pad(chunk, (0, 48000 - len(chunk))))
    if not samples:
        raise ValueError("no usable speech windows")
    vectors = []
    with torch.inference_mode():
        for i in range(0, len(samples), 8):
            batch = torch.from_numpy(np.stack(samples[i:i + 8])).to(model.device)
            vectors.append(model.encode_batch(batch).squeeze(1).float().cpu().numpy())
            if i % 400 == 0:
                print(f"{item}: embedded {min(i + 8, len(samples))}/{len(samples)}", flush=True)
    vectors = np.concatenate(vectors)
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-8)
    centers, scores = cluster(vectors, count)
    labels = smooth(1 - vectors @ centers.T, times)
    names = {k: f"SPEAKER_{i}" for i, k in enumerate(dict.fromkeys(labels.tolist()))}
    for k in range(len(centers)):
        if k not in names:
            names[k] = f"SPEAKER_{len(names)}"
    boundaries = [0, *[(a + b) / 2 for a, b in zip(times, times[1:])], max(duration, data["lines"][-1]["end"])]
    turns = []
    for i, label in enumerate(labels):
        speaker = names[label]
        if turns and turns[-1][2] == speaker:
            turns[-1] = (turns[-1][0], boundaries[i + 1], speaker)
        else:
            turns.append((boundaries[i], boundaries[i + 1], speaker))
    if caption_lines:
        turns = marker_windows(caption_lines, audio, model, centers, names, turns)
        lines = assign_turns(caption_lines, turns)
    else:
        lines = assign_lines(data["lines"], turns)
    summaries = {}
    for speaker in dict.fromkeys(line["speaker"] for line in lines):
        spoken = [line for line in lines if line["speaker"] == speaker]
        indices = np.linspace(0, len(spoken) - 1, min(5, len(spoken)), dtype=int)
        # Union intervals so overlapping auto-caption display times don't inflate talk time.
        talk, finish = 0, 0
        for line in spoken:
            talk += max(0, line["end"] - max(finish, line["start"]))
            finish = max(finish, line["end"])
        summaries[speaker] = {"talk_s": round(talk, 2), "first_lines": spoken[:3],
                              "sample_lines": [spoken[i] for i in indices]}
    elapsed = time.perf_counter() - begun
    result = {"item": item, "lines": lines, "speakers": summaries,
              "method": "speechbrain/spkrec-ecapa-voxceleb; 3s windows/0.75s hop; normalized Ward/cosine silhouette; Viterbi",
              "speaker_count": len(summaries), "silhouette_scores": scores,
              "audio_s": round(duration, 2), "runtime_s": round(elapsed, 2)}
    if turn_timing is not None:
        result["turn_timing"] = turn_timing
        result["method"] += "; caption-marker turns; clipped-window overlap; sentence-end fallback"
    output = lr.staging_path(publisher, item, "diar.json")
    with output.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"{item}: {len(summaries)} speakers, {elapsed:.1f}s, {elapsed / duration * 3600:.1f}s/audio hour", flush=True)


def self_test():
    import numpy as np
    lines = [{"start": 0, "end": 4, "text": "one two three four"}]
    out = assign_lines(lines, [(0, 2, "SPEAKER_0"), (2, 4, "SPEAKER_1")])
    assert [x["text"] for x in out] == ["one two", "three four"]
    assert " ".join(x["text"] for x in out) == lines[0]["text"]
    assert assign_lines(lines, [(0, 3.5, "a"), (3.5, 4, "b")])[0]["speaker"] == "a"
    assert smooth(np.array([[0., 1.], [.06, 0.], [0., 1.]]), [0, .75, 1.5]).tolist() == [0, 0, 0]
    rng = np.random.default_rng(7)
    vectors = np.vstack([rng.normal([1., 0.], .02, (20, 2)), rng.normal([0., 1.], .02, (20, 2))])
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    assert len(cluster(vectors)[0]) == 2
    assert len(cluster(vectors, 1)[0]) == 1
    single = rng.normal([1., 0.], .02, (40, 2))
    single /= np.linalg.norm(single, axis=1, keepdims=True)
    assert len(cluster(single)[0]) == 1
    document = {"events": [{"tStartMs": 1000, "dDurationMs": 4000, "segs": [
        {"utf8": "Question? ", "tOffsetMs": 0}, {"utf8": ">> ", "tOffsetMs": 2000},
        {"utf8": "[laughter] yes.", "tOffsetMs": 2000}]}]}
    timed, timing = json3_turns(document)
    assert [line["start"] for line in timed] == [1, 3]
    assert timing["estimated_boundaries"] == 0
    assigned = assign_turns(timed, [(0, 3, "host"), (3, 5, "guest")])
    assert [(x["text"], x["speaker"]) for x in assigned] == [("Question?", "host"), ("[laughter] yes.", "guest")]
    no_offsets, timing = json3_turns({"events": [{"tStartMs": 0, "dDurationMs": 6000,
                                                 "segs": [{"utf8": "Question? >> [laughter] yes."}]}]})
    assert timing["estimated_boundaries"] == 1 and no_offsets[1]["start"] == 2
    assert caption_text(no_offsets) == "Question? [laughter] yes."
    assert json3_turns({"events": [{"tStartMs": 0, "dDurationMs": 2000,
                                    "segs": [{"utf8": "No markers."}]}]})[0] == []
    long = {"start": 0, "end": 30, "text": "First sentence. Second sentence.", "words": [
        {"text": "First", "start": 0, "end": 7}, {"text": "sentence.", "start": 7, "end": 15},
        {"text": "Second", "start": 15, "end": 22}, {"text": "sentence.", "start": 22, "end": 30}]}
    assert [x["text"] for x in assign_turns([long], [(0, 12, "a"), (12, 30, "b")])] == ["First sentence.", "Second sentence."]
    import torch
    class TestEncoder:
        device = "cpu"

        def encode_batch(self, batch, wav_lens):
            return torch.tensor([[[1., 0.]] if row.sum() > 0 else [[0., 1.]] for row in batch])

    clipped = marker_windows([{"start": 0, "end": 2}, {"start": 2, "end": 4}],
                             np.concatenate([np.ones(32000), -np.ones(32000)]).astype(np.float32),
                             TestEncoder(), np.eye(2), {0: "host", 1: "guest"}, [])
    assert clipped == [(0, 2, "host"), (2, 4, "guest")]
    aligned, info = align_caption_words(timed, [
        {"word": "question", "start": 1.2, "end": 1.9}, {"word": "yes", "start": 3.3, "end": 3.7}])
    assert caption_text(aligned) == "Question? [laughter] yes."
    assert aligned[1]["start"] == 3.3 and info["estimated_boundaries"] == 0
    failed, info = align_caption_words(timed, [{"word": "question", "start": 1.2, "end": 1.9}])
    assert info["estimated_boundaries"] == 1 and failed[1]["start"] == 3
    assert timed[1]["start"] == 3  # alignment must not mutate cached caption estimates
    _, info = align_caption_words(timed, [{"word": "question", "start": 100, "end": 101}])
    assert info["matched_tokens"] == 0  # reject a distant repetition
    fuzzy = copy.deepcopy(timed)
    fuzzy[1]["text"] = "creators"
    fuzzy[1]["words"] = [{"text": "creators", "start": 3, "end": 5}]
    aligned, info = align_caption_words(fuzzy, [{"word": "question", "start": 1.2, "end": 1.9},
                                               {"word": "creator", "start": 3.4, "end": 4}])
    assert info["estimated_boundaries"] == 0 and aligned[1]["start"] == 3.4
    print("self-test passed")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    brainlib.add_workspace_arg(ap)
    ap.add_argument("publisher", nargs="?")
    ap.add_argument("item", nargs="?")
    ap.add_argument("--all", dest="all_publisher", metavar="PUBLISHER")
    ap.add_argument("--speakers", type=int, choices=range(1, 7))
    ap.add_argument("--whisper-words", action=argparse.BooleanOptionalAction, default=False,
                    help="opt into cached GPU Whisper word alignment (acceptance quality did not qualify it as default)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    lr.init(args.workspace)
    if args.self_test:
        self_test()
        return
    publisher = args.all_publisher or args.publisher
    if not publisher or (args.all_publisher and (args.publisher or args.item)) or (not args.all_publisher and not args.item):
        ap.error("use PUBLISHER ITEM or --all PUBLISHER")
    validate(publisher, args.item or "yt-check")
    items = [p.name.removesuffix(".lines.json") for p in sorted((lr.pub_dir(publisher) / "staging").glob("*.lines.json"))] if args.all_publisher else [args.item]
    items = [item for item in items if not lr.staging_path(publisher, item, "diar.json").exists()]
    if not items:
        print("no pending items")
        return
    # Disable implicit credentials: this model and every download are public.
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    import torch
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy

    torch.set_num_threads(4)
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    print(f"ECAPA on {device}", flush=True)
    model = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                          savedir=str(lr.LIBRARY / ".models" / "ecapa-model"),
                                          run_opts={"device": device}, local_strategy=LocalStrategy.COPY)
    failed = []
    for item in items:
        try:
            diarize(publisher, item, model, args.speakers, args.whisper_words)
        except Exception as exc:
            print(f"FAILED {item}: {exc}", file=sys.stderr, flush=True)
            failed.append(item)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()

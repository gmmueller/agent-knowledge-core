# Library: shared expert sources

Topic brains (`kind: topic` in `brain.md`) draw on a shared library instead of their own `raw/`. A source is crawled once into the library; any brain can select from it. Persona brains keep their own `raw/`.

The library lives in the private workspace at `<workspace>/library/`. Tools that only touch the library take `--workspace <workspace>`. Tools that work on one topic brain take `--brain <brain-folder>` and find the library next to it.

## Layout

```
library/
  people.yaml                      who speaks where (experts are speakers, not channels)
  <publisher>/                     one folder per publisher: a channel owner, blog, podcast, author or vendor
    sources.yaml                   channels, feeds, sites and books of this publisher (schema below)
    catalogue.tsv                  one row per published item, metadata only (every item, crawled or not)
    crawl-log.md                   what each run fetched and what failed
    raw/                           immutable text, written once
      yt/<YYYYMMDD>-<videoid>-<slug>.md
      pod/<YYYYMMDD>-<episode-slug>.md
      web/<YYYYMMDD>-<slug>.md     (date = published; YYYYMM00 / YYYY0000 for partial dates; 00000000 if unknown)
      book/<slug>.md
      paper/<YYYYMMDD>-<slug>.md   (research papers; YYYYMM00 / YYYY0000 for partial dates; 00000000 if unknown)
    examples/<item-id>.yaml        measured facts about a video used as an example (cuts, frames); not opinions
    staging/                       intermediate files (diarization, speaker naming); gitignored
    media/                         audio, video, frames, PDFs; gitignored
  .models/ecapa-model/             speaker model shared by diarize.py; gitignored
```

**What to keep in `media/` and `staging/`:** once an item's raw file exists, its audio, captions, frames and staging files are disposable. Delete them after a brain's build. Keep example videos (`media/video/`, so example annotations can be redone), source PDFs, and `media/meta/` (slim yt-dlp metadata, so catalogue reruns skip about 3 seconds per video). Keep staging and captions for items still waiting for the speaker pass.

**Search:** the `library` qmd collection indexes `*/raw/**/*.md`. Run `qmd update` then `qmd embed` after a crawl.

- `<publisher>` and slugs: kebab-case ASCII. Slugs come from the title, max 60 characters.
- **Item id** (`id` in the catalogue, `source_id` in raw): `yt-<videoid>`, `pod-<slug>`, `web-<slug>`, `book-<slug>`, `paper-<slug>`. Unique within the publisher. Across the library an item is addressed as `<publisher>/<id>`.

## `sources.yaml` (per publisher)

Same fields as a brain's `sources.yaml` (see `template/sources.yaml`, `docs/updates.md`), plus:

```yaml
publisher: example-publisher
display_name: The Expert
default_speaker: The Expert      # speaker for single-voice items; null for multi-voice shows
sources:
  - id: example-publisher-yt
    type: youtube-channel           # youtube-channel | podcast | blog | book | docs | social
    url: https://example.com/channel
    tabs: [videos, shorts]
    format: interview               # solo | interview | panel | mixed; interview/panel/mixed get a speaker pass
    refresh: monthly
    last_crawled: null
    cursor: null
```

## `catalogue.tsv`

UTF-8, tab-separated, header row, no tabs or newlines inside fields. Rewritten on each catalogue run, so new items append and existing rows update metadata. Fields are whitespace-cleaned, so read and write with plain tab splitting, not a CSV library: its quote escaping multiplies backslashes on every rewrite.

| Column | Meaning |
|---|---|
| `id` | item id (above) |
| `kind` | `video`, `short`, `stream`, `podcast`, `post`, `book`, `paper`, `doc` |
| `title` | |
| `published` | `YYYY-MM-DD`, `YYYY-MM` or `YYYY`; empty if unknown |
| `duration_s` | integer seconds; empty for text |
| `views` | integer; empty if unknown |
| `url` | canonical URL |
| `source` | `sources.yaml` source id it came from |
| `description` | first 500 characters, whitespace collapsed |

## Raw file format

Frontmatter (every raw file):

```yaml
---
source_id: yt-abc123
publisher: example-panel
title: "..."
url: https://www.youtube.com/watch?v=abc123
kind: video
published: 2024-05-12
duration: 14:32            # transcripts only
captured: 2026-10-12
method: captions | whisper | transcript-page | page-text | pdf | pdf-ocr-model
speakers: [The Expert, Other Speaker]   # [] if unknown
speaker_method: single | diarized | transcript | none
---
```

Body blocks, one per line, each starting with its **locator**:

| Source | Block | Citation |
|---|---|---|
| transcript | `**[12:41]** The Expert: text` (speaker prefix when `speakers` is non-empty) | `@ 12:41` |
| web page or doc | `**[¶12]** text`; headings are their own block: `**[¶11]** ## Heading` | `@ ¶12` |
| book or PDF | `**[p. 37]**` on its own line, then that page's text | `@ p. 37` |

- Transcript blocks start a new block at every **speaker change**, otherwise roughly every 30 s at a sentence end (forced at 45 s), as in `tools/wistia_to_raw.py`.
- **Dates:** `published` accepts `YYYY`, `YYYY-MM` or `YYYY-MM-DD`. Partial dates record `publication_precision: year` or `month` in frontmatter, and filenames pad missing parts with zeros (`YYYY0000`, `YYYYMM00`, or `00000000` when unknown). If a web page lacks machine-readable date metadata (`published: ""` and `00000000` filename) for a work whose edition year is known, keep raw untouched and record the verified edition year plus `publication_precision: year` on the wiki source page.
- **Pre-capture selection vs immutable raw:** selecting a subset **before** capture is supported and recorded in raw frontmatter (`book_to_raw.py --pages 1-12,40-55` keeps original PDF `p. N` locators; `web_to_raw.py fetch --from-heading "Start" --to-heading "End"` is start-inclusive, end-exclusive, requires exact unique headings, renumbers selected paragraphs from `¶1`, and cannot combine with `--transcript`). Editing a raw file **after** capture is never allowed; tools refuse to overwrite an existing file. Fix a bad file by re-capturing (for web pages, `--recapture` writes a dated capture) and re-anchoring wiki quotes with `tools/requote.py` (which handles timestamps, `¶N` paragraph and `p. N` page locators).

## Citations from a brain wiki

`([[library/<publisher>/raw/yt/<file>]] @ 12:41)`: the path is relative to the workspace root, with `.md` optional. Persona brains keep `([[raw/...]] @ t)`, which is relative to the brain folder.

A quote line in a topic brain always names its speaker:

```
> "the exact words" — The Expert ([[library/example-publisher/raw/yt/20240512-abc123-...]] @ 12:41)
```

Observations from an example video (frames, cuts, on-screen text) cite the measured file with seconds: `([[library/example-publisher/examples/yt-abc123]] @ 1.5s)`. The checker confirms the file exists and the time is within the video. Quotes always cite a raw transcript.

`tools/check_wiki.py` checks the words appear verbatim in the cited block (or the one before or after it), and that the named speaker matches the block's speaker prefix, using aliases from `people.yaml`. Timestamps must fall within the captured duration. If the file has no duration, the final timestamp is the limit. For `@ page text` in a source with speaker turns, the named speaker must have said the passage.

## `people.yaml`

```yaml
expert:
  name: The Expert
  aliases: [Expert]
  roles: [domain-expert]
  appearances:                       # where they speak at length; filled by crawls and triage
    - { item: example-publisher/yt-abc123, role: guest }
    - { item: expert/yt-def456, role: host }
```

## Brain side: `selection.yaml`

Each topic brain lists the library items it uses. `tools/triage_merge.py` builds the list from triage scores. To add an unscored item by hand, supply its `item`, `override` (for example `A`) and `why`. Use `tools/selection_override.py` to override items already in the list.

```yaml
brain: my-topic
triage_version: 1
items:
  - item: example-expert/yt-abc123
    tier: A                      # A deep ingest | B raw + search only | C skip | X example (annotate)
    scores: { relevance: 3, density: 2, voice: 3, unique: 2, fresh: 1 }
    speakers: [The Expert]
    why: "explains the framework with two worked examples"
```

Triage scores (0–3 each): **relevance** to the brain's extraction areas, teaching **density**, **voice** (a listed expert teaching in their own words), **unique**ness vs items already in tier A, **fresh**ness (weighted only when `brain.md` sets `triage: { weight_fresh: true }`). `example` is 1 when the item is worth annotating as a demonstration (tier X). Triage agents write TSV rows with header `item	relevance	density	voice	unique	fresh	example	speakers	why` (speakers `;`-separated) to `<brain>/ingest/triage/<publisher>.tsv`. Details: `docs/triage.md`.

## Multi-speaker items: staging hand-off

Items from a source with `format` other than `solo` (or `tab_format: {shorts: solo}` overrides per tab) don't go straight to `raw/`:

1. The fetcher writes `library/<publisher>/staging/<item-id>.lines.json`: `{"item": id, "front": {raw frontmatter without speakers}, "lines": [{"start": s, "end": s, "text": "..."}]}`.
2. `tools/diarize.py` adds `"speaker": "SPEAKER_0"` per line and writes `<item-id>.diar.json`, including per-speaker talk time and sample lines.
3. A naming step writes `<item-id>.names.yaml` (`SPEAKER_0: The Expert`, plus `roles: {The Expert: host}`), from the title, description and introductions. Give the naming agent `tools/speaker_naming.md` as its brief.
4. `tools/finalize_raw.py` writes the raw file (`speaker_method: diarized`) and adds the appearances to `people.yaml`.

Sources whose publisher already prints a speaker-labelled transcript (for example a podcast's episode pages) skip diarization: `speaker_method: transcript`.

## Library tools

| Task | Tool |
|---|---|
| List a channel, feed or playlist; fetch captions or audio; add single videos | `library_yt.py --workspace <ws> {catalogue,fetch,add} <publisher>` |
| List and capture blogs, docs and transcript pages (use `--from-heading` / `--to-heading` to select sections before capture on paragraph pages; `--recapture` for a fresh dated capture) | `web_to_raw.py --workspace <ws> {list,fetch} <publisher>` |
| Turn a user-supplied book or paper PDF into raw, updating `catalogue.tsv` and appending to `crawl-log.md` (`--published` accepts `YYYY`, `YYYY-MM`, `YYYY-MM-DD`; `--pages 1-12,40-55` keeps original PDF page numbers) | `book_to_raw.py --workspace <ws> <publisher> <pdf> --slug … --title … --author … --published DATE [--pages …]` |
| Speaker pass: cluster voices, then name them | `diarize.py --workspace <ws> <publisher> <item>`, a naming agent, then `finalize_raw.py --workspace <ws> <publisher> <item>` |
| Measure an example video (cuts, frames, opening lines) | `example_frames.py --workspace <ws> <publisher> <yt-id …>` |
| Hash captured raw files (`library/<publisher>/.capture-hashes.json`) and detect changed or missing captures | `raw_guard.py --workspace <ws> {record [--init],check}` |
| Shared helpers (paths, slugs, catalogue read/write, raw writing) | `library_raw.py` (imported by the tools above) |

Each tool's `--help` lists its options. The pipeline order is in `docs/build-pipeline.md`.

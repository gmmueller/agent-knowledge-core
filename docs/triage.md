# Triage: choosing what a topic brain ingests

Catalogues list everything an expert has published. Triage scores each item against one brain so that only the valuable part gets deep-ingested. Contract and file formats: `docs/library.md` ("Brain side: selection.yaml").

## Steps

1. **Catalogue** each publisher (`library_yt.py catalogue`, `web_to_raw.py list`). Metadata only.
2. **Cut inputs.** `triage_inputs.py --brain <brain> <publisher> [--kinds video,short] [--chunk 300] [--shorts-prefilter 150:20]` writes `<brain>/ingest/triage/input/<publisher>-<n>.tsv` with `item, kind, title, published, duration_s, views, description` (the first 200 characters). It skips items already scored (in `<publisher>.tsv`, any `<publisher>-<n>.tsv` chunk output, or `selection.yaml`), so you can re-run it after new crawls. When the first triage covered only a filtered subset of a large catalogue, refresh with `--since <last crawl date>` after `library_yt.py catalogue <publisher> --details N` has dated the new rows; undated rows are skipped and counted.
3. **Score.** One triage agent per input file, using the brief below.
4. **Spot-check** 10 random rows per file. Fix outliers with `selection_override.py` (step 6).
5. **Merge.** `triage_merge.py --brain <brain>` reads `<brain>/ingest/triage/*.tsv` and builds `<brain>/selection.yaml` with tiers A (deep ingest), B (raw + search), C (skip) and X (annotate as example). It keeps hand overrides when you re-run it.
6. **Override.** `selection_override.py --brain <brain> <A|B|C|X> <publisher>/<id> … --why "reason"` changes items already in `selection.yaml`. For an item added by hand outside triage (a guest appearance, a single video), append it to `selection.yaml` directly with `override: A` and a `why`.

Automatic tier A requires `unique` of at least 1, in addition to the teaching scores. A hand override can still place a duplicate in A. Within a tier, unscored entries follow scored entries and sort by item ID.

## Who runs it

A low-cost volume model, one agent per publisher catalogue or per about 150 rows. The orchestrator spot-checks 10 random rows per file before merging.

## Brief for a triage agent

Fill in the **Brain-specific calls** section for each brain, then give the agent this brief.

You score catalogue rows for **one brain**. Read:
1. `<brain>/brain.md`: the **Experts** table and the **Extraction areas**. Those are your rubric.
2. The rows you were given (`<brain>/ingest/triage/input/<file>.tsv`).

For each row, judge from the title, description, duration and kind. Where a raw file or staging file exists, also skim its first three minutes. Score each 0–3:

| Score | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| **relevance** | none of the extraction areas | touches one in passing | clearly teaches one or two | centrally about several |
| **density** | entertainment, vlog, news, gear, promo | mostly story with some lessons | teaching with examples | structured method, reasoning shown |
| **voice** | nobody on the expert list speaks | an expert appears briefly | an expert teaches for part of it, or a strong non-listed practitioner teaches | a listed expert teaches it in their own words |
| **unique** | duplicate or re-upload, or a clip of a longer item | mostly repeats their usual points | some new angles | new material not covered elsewhere |
| **fresh** | platform or tool advice that is clearly outdated | older, may still hold | recent-ish | current (recorded always; counted only when the brain sets `weight_fresh`) |

- `example` = 1 when the item is a strong *demonstration* worth annotating (for instance a high-performing short video in the brain's area), even if it teaches nothing. A live diagnosis of one real case is also an example; score its other columns normally.
- `speakers`: who teaches in it, `;`-separated, as far as you can tell from the title, description and channel. Write `?` if unknown.
- `why`: at most 15 words, specific ("explains 3-part hook with two examples"), not generic ("good video").
- Clips of a longer video: unique = 0, unless the longer one isn't in the catalogue. Reruns ("replay", "greatest hits") of an episode already in the feed: unique = 0, and say "rerun of #N".
- Sponsored or affiliate-heavy items: density ≤ 1 unless the teaching is real.
- Third-party summaries of an expert ("I watched every talk by X") get voice 0. Hosts and interviewers are not the teacher.

### Brain-specific calls (fill in per brain)

- **Listed experts** (voice 3 when they teach in their own words): `{{experts}}`.
- **Strong non-listed practitioners** (voice 2): `{{practitioners}}`. Hosts (`{{hosts}}`) don't count as the teacher.
- **Example = 1 for:** `{{example_kinds}}`.
- **Score low (relevance 0–1):** `{{off_topic}}`.
- **Excluded content (relevance 0):** `{{exclusions}}`. If the brain must never use a whole class of material (for example a copyrighted annual card), say so here. Repeat the exclusion as a hard rule in the ingest brief and in each batch note.
- **Overlap with a sibling brain:** `{{overlap}}`. Say which brain owns it and what to score.
- **fresh:** `{{fresh_scale}}` (for example 3 for the last two years, 2 for two to four years back, 1 for older, 0 for advice tied to a platform that no longer exists).

Output: write TSV rows to the output file you were given in `<brain>/ingest/triage/`, one row per input row, same `item` id, no blanks, no duplicates. Write the header once:

```
item	relevance	density	voice	unique	fresh	example	speakers	why
example-publisher/yt-abc123	3	2	3	2	1	0	The Expert	first-frame hook rules with three demonstrations
```

Scores are integers 0–3 and `example` is 0 or 1. No tabs or newlines inside fields. When done, report: rows written, how many you scored relevance ≥ 2, how many `example` = 1, and up to five rows you were unsure about.

## Calibration

Triage agents calibrate differently on the same channel: one may give relevance 3 to four items where another gives 3 to twenty-five, mostly changelogs. Spot-check every file and fix with `selection_override.py`. Read the "Brain-specific calls" section back to the agent if its scores drift.

## Mechanical pre-filters

For thousands of short videos from one publisher, filter before any model sees them. Take the top 150 by views, plus the top 20 per year so older styles are represented (`triage_inputs.py --shorts-prefilter 150:20`), and dedupe. A triage agent then picks examples for diversity of hook type and story shape, not just views.

For an excluded content class, filter the obvious titles mechanically first. In one build this cut a catalogue of about 1,900 videos to about 800 before any model saw it.

## Saturation

Deep-ingest tier A in score order. After each batch of about 10, count new principle, framework, method and rule pages. If two batches in a row add fewer than about 2 new pages each, demote the rest of tier A to B and record that in `wiki/log.md`.

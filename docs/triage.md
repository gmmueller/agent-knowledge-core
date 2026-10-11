# Triage: choosing what a topic brain ingests

This is the shared-library triage design. The merge tool and catalogue acquisition are outside this port; the brief can be used by a volume worker.

Catalogues list everything an expert has published. Triage scores each item against one brain so that only the valuable part gets deep-ingested. Contract and file formats: `docs/library.md` ("Brain side: selection.yaml").

## Who runs it

A low-cost volume worker, one agent per publisher catalogue or per ~150 rows. The orchestrator spot-checks 10 random rows per file before merging.

## Brief for a triage agent

You score catalogue rows for **one brain**. Read:
1. `<brain>/brain.md`: the **Experts** table and the **Extraction areas**. Those are your rubric.
2. The catalogue rows you were given (`library/<publisher>/catalogue.tsv`, filtered to your range).

For each row, judge from the title, description, duration and kind. Where a raw file or staging file exists, also skim its first ~3 minutes. Score each 0–3:

| Score | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| **relevance** | none of the extraction areas | touches one in passing | clearly teaches one or two | centrally about several |
| **density** | entertainment, vlog, news, gear, promo | mostly story with some lessons | teaching with examples | structured method, reasoning shown |
| **voice** | nobody on the expert list speaks | an expert appears briefly | an expert teaches for part of it, or a strong non-listed practitioner teaches | a listed expert teaches it in their own words |
| **unique** | duplicate or re-upload, or a clip of a longer item | mostly repeats their usual points | some new angles | new material not covered elsewhere |
| **fresh** | platform/tool advice that is clearly outdated | older, may still hold | recent-ish | current (only matters when the brain sets `weight_fresh`) |

- `example` = 1 when the item is a strong *demonstration* worth annotating (for instance a high-performing Short in the brain's area), even if it teaches nothing.
- `speakers`: who teaches in it, `;`-separated, as far as you can tell (title, description, channel). Write `?` if unknown.
- `why`: at most 15 words, specific ("explains 3-part hook with two examples"), not generic ("good video").
- Shorts that are clips of a longer video: unique = 0, unless the longer one isn't in the catalogue.
- Sponsored or affiliate-heavy items: density ≤ 1 unless the teaching is real.

Output: append TSV rows (no header if the file exists) to `<brain>/ingest/triage/<publisher>.tsv`:

```
item	relevance	density	voice	unique	fresh	example	speakers	why
example-publisher/yt-abc123	3	2	3	2	1	0	The Expert	first-frame hook rules with three demonstrations
```

A future `tools/triage_merge.py --brain <brain-folder>` builds `<brain>/selection.yaml` with tiers A (deep ingest), B (raw + search), C (skip) and X (annotate as example).

## Large Shorts catalogues

For thousands of Shorts (e.g. several thousand from one publisher), pre-filter mechanically before any model sees them. Take the top ~150 by views, plus the top ~20 per year so older styles are represented, and dedupe. Then a triage agent picks examples for diversity of hook type and story shape, not just views.

## Saturation

Deep-ingest tier A in score order. After each batch of ~10, count new principle, framework, method and rule pages. If two batches in a row add fewer than ~2 new pages each, demote the rest of tier A to B and record that in `wiki/log.md`.

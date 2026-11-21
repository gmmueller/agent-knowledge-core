# Plain Writing build notes

Built 2026-11-20 (America/Chicago; the UTC clock crossed into November 21). All changes are under `examples/`. No commits, branch changes, package installs, login sessions or paid calls.

## Result and counts

| Artifact | Count |
|---|---:|
| Library publishers / co-authored voices | 3 |
| Final immutable raw files | 8 |
| Source-text words | 48,843 |
| Source pages | 16 |
| Concept pages, excluding debates | 22 |
| Debate pages | 2 |
| Total wiki content pages | 40 |
| Topic / principle / method / glossary pages | 7 / 3 / 3 / 3 |
| Rules: consensus / active / bench / contested | 3 / 0 / 3 / 0 |
| Eval questions / trap questions | 8 / 2 |
| Publisher staging files / concept bundles | 3 / 22 |

Word counts exclude raw frontmatter and locator labels and use whitespace-separated source-body tokens. Final source hashes and per-file counts are in `workspace/plain-writing/ingest/source-manifest.yaml`. Index, hot list, operation log, source registries, people registry, selection, metadata inputs, filled briefs and the generated skill are included.

## Source editions and URLs

- **William Strunk Jr., The Elements of Style (1918):** six chapter captures from https://en.wikisource.org/wiki/The_Elements_of_Style and its Introduction, Rules, Principles, Form, Misuse and Misspelling links. The parent labels the text 1920/1918 and warns of transcription provenance. The captured text has the 1918 arrangement (eight usage rules and ten composition principles), distinct from the separately labelled 1920 version. An additional 1918-labelled typeset text was inspected at https://www.ag.kagawa-u.ac.jp/charlesy/wp/wp-content/uploads/2023/10/The-Elements-of-Style-1918.pdf; it is a re-typesetting, not an original scan, and is not redistributed or cited as a separate authority. This provenance limitation remains explicit.
- **Arthur Quiller-Couch, On the Art of Writing (1916):** https://archive.org/details/onartofwriting00qui ; actual PDF download https://archive.org/download/onartofwriting00qui/onartofwriting00qui.pdf . Verified the title page, copyright page and contents. Selected lectures II (The Practice of Writing), V (Interlude: On Jargon), VI (On the Capital Difficulty of Prose), XII (On Style). Original PDF pages 42–67, 116–168, 294–313; 99 page blocks. Printed pages equal PDF pages minus 16.
- **H. W. Fowler and F. G. Fowler, The King’s English (1906, second edition):** https://en.wikisource.org/wiki/The_King%27s_English/Chapter_1/General_Principles . Final scope: General, then Neologisms through the end of Vocabulary. The unselected Malaprops section was omitted on a fresh capture, not edited out of raw. Two source pages divide general principles from vocabulary in use.

All original books were published before 1931 and are public domain in the United States. No Gutenberg text was used, so no Gutenberg header, footer or licence text was redistributed. Library raw contains historical people and fictional characters named by the authors. The request’s literal ban on every other personal name conflicts with capturing a whole book; it was applied as a ban on private/user identifiers in authored material, while preserving public-domain primary text. The supplied private scrub nevertheless returns no matches in the final example.

## Commands, in execution order

Run from the framework repository root. `$Python` below stands for the already-configured interpreter used for every invocation; its machine-specific path is deliberately omitted. `$Scratch` stands for the temporary directory outside this repository. These are path substitutions only. The scratch authoring scripts mechanically wrote human/agent-authored content; all durable inputs and outputs are retained in the filled briefs, staging, bundles and wiki. They are not additional framework tools. Read-only inspection commands (`Get-Content`, `rg`, tool `--help`, PDF title-page inspection) are described after the build sequence rather than repeated for every excerpt.

```powershell
$Scratch = Join-Path $env:TEMP 'akc-plain-writing-build'
New-Item -ItemType Directory -Force -Path $Scratch
Invoke-WebRequest -Uri 'https://www.ag.kagawa-u.ac.jp/charlesy/wp/wp-content/uploads/2023/10/The-Elements-of-Style-1918.pdf' -OutFile (Join-Path $Scratch 'strunk-1918.pdf')
Invoke-WebRequest -Uri 'https://upload.wikimedia.org/wikipedia/commons/b/b3/On_the_art_of_writing_%28IA_onartofwriting00qui%29.pdf' -OutFile (Join-Path $Scratch 'quiller-couch-1916.pdf')
# Previous command returned HTTP 429; switched to the same original scan at Internet Archive.
Invoke-WebRequest -Uri 'https://archive.org/download/onartofwriting00qui/onartofwriting00qui.pdf' -OutFile (Join-Path $Scratch 'quiller-couch-1916.pdf')
Copy-Item -Recurse template-topic examples/workspace/plain-writing
New-Item -ItemType Directory -Force -Path examples/workspace/library/fowler,examples/workspace/library/strunk,examples/workspace/library/quiller-couch
& $Python -X utf8 -I (Join-Path $Scratch 'setup.py')
& $Python -X utf8 -I tools/web_to_raw.py --workspace examples/workspace fetch strunk --urls 'https://en.wikisource.org/wiki/The_Elements_of_Style/Introduction' 'https://en.wikisource.org/wiki/The_Elements_of_Style/Rules_of_Usage' 'https://en.wikisource.org/wiki/The_Elements_of_Style/Principles_of_Composition' 'https://en.wikisource.org/wiki/The_Elements_of_Style/Form' 'https://en.wikisource.org/wiki/The_Elements_of_Style/Misused_Expressions' 'https://en.wikisource.org/wiki/The_Elements_of_Style/Misspelled_Words' --kind doc
# Two captures succeeded; four guessed URLs returned 404. Read the actual contents links.
& $Python -X utf8 -I tools/web_to_raw.py --workspace examples/workspace fetch strunk --urls 'https://en.wikisource.org/wiki/The_Elements_of_Style/Rules' 'https://en.wikisource.org/wiki/The_Elements_of_Style/Principles' 'https://en.wikisource.org/wiki/The_Elements_of_Style/Misuse' 'https://en.wikisource.org/wiki/The_Elements_of_Style/Misspelling' --kind doc
& $Python -X utf8 -I tools/web_to_raw.py --workspace examples/workspace fetch fowler --urls 'https://en.wikisource.org/wiki/The_King%27s_English/Chapter_1/General_Principles' --kind doc
& $Python -X utf8 -I (Join-Path $Scratch 'select-pages.py')
# This scratch PDF operation retained selected original pages and blanked excluded positions before capture.
& $Python -X utf8 -I tools/book_to_raw.py --workspace examples/workspace quiller-couch (Join-Path $Scratch 'quiller-couch-selected.pdf') --slug on-the-art-of-writing-selected --title 'On the Art of Writing: Lectures II, V, VI, XII (1916)' --author 'Arthur Quiller-Couch' --published 1916-01-01 --url 'https://archive.org/details/onartofwriting00qui' --page-numbering 'p. N = original scan PDF page N; printed page = N minus 16. Unselected pages blanked before capture.' --extra 'selected_pdf_pages=42-67;116-168;294-313' --extra 'publication_precision=year' --extra 'rights=Public domain in the United States'
& $Python -X utf8 -I (Join-Path $Scratch 'author.py')
# Authoring was incremental: source definitions first; then scope, registries, filled briefs, source pages and staging.
# One scratch assertion caught the templates’ literal placeholder-instruction token; it was resolved before output.
& $Python -X utf8 -I tools/triage_inputs.py --brain examples/workspace/plain-writing strunk
& $Python -X utf8 -I tools/triage_inputs.py --brain examples/workspace/plain-writing quiller-couch
& $Python -X utf8 -I tools/triage_inputs.py --brain examples/workspace/plain-writing fowler
# These first three runs correctly said nothing to triage because the tiny hand-scored TSVs already existed.
& $Python -X utf8 -I tools/triage_merge.py --brain examples/workspace/plain-writing
& $Python -X utf8 -I tools/check_wiki.py --brain examples/workspace/plain-writing
& $Python -X utf8 -I tools/merge_topic.py --brain examples/workspace/plain-writing survey
& $Python -X utf8 -I tools/merge_topic.py --brain examples/workspace/plain-writing bundles
& $Python -X utf8 -I (Join-Path $Scratch 'pages.py')
& $Python -X utf8 -I tools/check_wiki.py --brain examples/workspace/plain-writing
# Added the two debates and eight evals to the scratch authoring script, then reran it.
& $Python -X utf8 -I (Join-Path $Scratch 'pages.py')
& $Python -X utf8 -I tools/check_wiki.py --brain examples/workspace/plain-writing
& $Python -X utf8 -I tools/rule_status.py --brain examples/workspace/plain-writing --write
& $Python -X utf8 -I tools/lint_wiki.py --brain examples/workspace/plain-writing --fix-slug-map
& $Python -X utf8 -I tools/build_wiki_index.py --brain examples/workspace/plain-writing
& $Python -X utf8 -I tools/generate_persona.py --brain examples/workspace/plain-writing --out (Join-Path $Scratch 'skills')
& $Python -X utf8 -I (Join-Path $Scratch 'polish.py')
& $Python -X utf8 -I tools/check_wiki.py --brain examples/workspace/plain-writing
& $Python -X utf8 -I tools/merge_topic.py --brain examples/workspace/plain-writing survey
& $Python -X utf8 -I tools/merge_topic.py --brain examples/workspace/plain-writing bundles
& $Python -X utf8 -I (Join-Path $Scratch 'pages.py')
# Moved the three scored TSVs into scratch, ran the next three commands, then moved the same TSVs back unchanged.
& $Python -X utf8 -I tools/triage_inputs.py --brain examples/workspace/plain-writing strunk
& $Python -X utf8 -I tools/triage_inputs.py --brain examples/workspace/plain-writing quiller-couch
& $Python -X utf8 -I tools/triage_inputs.py --brain examples/workspace/plain-writing fowler
& $Python -X utf8 -I tools/triage_merge.py --brain examples/workspace/plain-writing
& $Python -X utf8 -I (Join-Path $Scratch 'finalize.py')
& $Python -X utf8 -I tools/check_wiki.py --brain examples/workspace/plain-writing
& $Python -X utf8 -I tools/rule_status.py --brain examples/workspace/plain-writing --write
& $Python -X utf8 -I tools/lint_wiki.py --brain examples/workspace/plain-writing --fix-slug-map
& $Python -X utf8 -I tools/build_wiki_index.py --brain examples/workspace/plain-writing
& $Python -X utf8 -I (Join-Path $Scratch 'audit.py')
# The private scrub found one historical-name suffix false positive in an uncited Fowler section.
& $Python -X utf8 -I (Join-Path $Scratch 'recapture-fowler.py')
# Wrapper around the framework web adapter: fresh HTTP fetch; pre-capture section selection; --recapture behavior.
& $Python -X utf8 -I (Join-Path $Scratch 'reanchor-fowler.py')
& $Python -X utf8 -I tools/check_wiki.py --brain examples/workspace/plain-writing
& $Python -X utf8 -I tools/merge_topic.py --brain examples/workspace/plain-writing bundles
& $Python -X utf8 -I tools/rule_status.py --brain examples/workspace/plain-writing --write
& $Python -X utf8 -I tools/lint_wiki.py --brain examples/workspace/plain-writing --fix-slug-map
& $Python -X utf8 -I tools/build_wiki_index.py --brain examples/workspace/plain-writing
& $Python -X utf8 -I (Join-Path $Scratch 'audit.py')
# The supplementary drive-path regex initially mistook HTTPS for a drive; fixed the scratch audit, then reran.
& $Python -X utf8 -I (Join-Path $Scratch 'audit.py')
& $Python -X utf8 -I (Join-Path $Scratch 'notes.py')
# Final gates and scratch removal are recorded below.
```

Read-only discovery covered, in the requested order, `README.md`, `AGENTS.md`, `docs/architecture.md`, `docs/library.md`, `docs/triage.md`, the topic pipeline and lessons in `docs/build-pipeline.md`, the three topic briefs and README tool rows. CLI help was read for web capture, PDF capture, triage inputs and paragraph re-anchoring. Source contents and edition pages were checked through public web search; selected raw blocks were then read locally. No fetched material beyond the three specified books was added to the example.

The small-source selection was deliberately trivial. Capture preceded triage, as permitted for selecting everything fetched. The first source/staging drafts were authored together with the hand-scored triage TSVs; all eight items were selected A before the first ingest gate. This is a recorded ordering deviation from the scale-oriented catalogue → triage → fetch sequence, not a claim to have run triage before fetching.

## Acceptance

- `check_wiki.py --brain examples/workspace/plain-writing`: **ok: 43 files** (40 wiki content pages and three staging files).
- `rule_status.py --brain examples/workspace/plain-writing --write`: **3 consensus, 3 bench**, no fabricated contested status.
- `lint_wiki.py --brain examples/workspace/plain-writing --fix-slug-map`: **0 broken link targets, 0 orphan concepts**, no remaining warnings.
- `build_wiki_index.py --brain examples/workspace/plain-writing`: **24 concept/debate pages and 16 source pages**, `wiki/index.md` present.
- Generated skill and `agents/openai.yaml` exist under `examples/skills/plain-writing/`. Machine-specific prefix replaced; HTML comment explains the portable copy. No absolute machine paths remain.
- The supplied private scrub was read at runtime, used over `examples/`, and returned **no matches**. The expression was never copied into this repository. Supplementary drive-path, email and unfilled-placeholder checks also pass.
- Source hashes rechecked after all wiki work. Scratch downloads, scripts, generated intermediate skill and superseded capture were removed after final checks.
- **Not run:** a fresh-agent eval session, broad framework test suites or global search indexing. Eight questions and answer criteria are supplied; no unrun cold evaluation is reported as passing.

## Documentation friction

1. **README → Quick start: topic brain; docs/build-pipeline.md → Catalogue.** The ready-to-run example is almost entirely a video pipeline. It does not show a small, book-only topic workspace, book catalogue creation or a text-source speaker bypass. This build supplies such an example; a short book-specific branch would remove guesswork.
2. **docs/build-pipeline.md → Catalogue; docs/library.md → Library tools.** The table associates `book_to_raw.py` with `catalogue.tsv`, but that tool only writes raw. It also creates no crawl log. Used `library_raw.merge_catalogue` (the framework helper) and wrote a human crawl entry. A new user otherwise reaches triage with no book row.
3. **book_to_raw.py help / docs/library.md → PDF import.** There is no page-range selection. Four lectures required a scratch PDF retaining the selected pages and blank positions so original PDF locators survived. The docs do not explain this workflow or a supported alternative.
4. **docs/library.md → Raw frontmatter; topic-ingest-brief.md → published.** Web pages without machine-readable publication metadata produce `published: ""` and `00000000` filenames even for books with a known edition year. The brief says to copy raw frontmatter. The source pages instead state the verified year with `publication_precision: year`; raw remains untouched. The docs should distinguish edition year from page metadata and unknown publication dates.
5. **book_to_raw.py required --published.** A complete date is shown, while these editions are known only to year. Used a January 1 sentinel and an explicit precision field, and disclosed it. A documented year-only convention would avoid invented precision.
6. **topic-ingest-brief.md / topic-pages-brief.md / debates-brief.md → gold example.** All three require an existing gold page, but the empty topic template supplies none. Wrote the first page of each kind as the local gold. The completed example now offers actual references for future users.
7. **The three briefs → relative paths and acceptance commands.** Read-first instructions point to framework files while the general path rule says paths are workspace-relative; gate commands ask for absolute paths. The archived example briefs clarify the framework-root context and use portable root-relative paths. Specify a working directory and framework/workspace roots once.
8. **topic-pages-brief.md → page-groups.yaml; topic pipeline → Merge.** No exact group schema or item-to-page-map command is supplied. Read the consuming text and wrote `groups: [{name, slugs}]`, `debates: [{slug, title, concepts}]` and a two-column `item-pages.tsv`. A compact schema example would help.
9. **docs/build-pipeline.md → Ingest and merge; library citation conventions.** Partial HTML book captures have no CLI section selector. The privacy false positive forced a fresh capture through the adapter’s own extraction/write functions with selection applied before raw creation. Document a text-section capture path, and explicitly distinguish selection before capture from editing raw.
10. **docs/build-pipeline.md → Rule status and independence.** Voice counting works as documented, but distinct names are not evidence of independent intellectual origin: Strunk cites Quiller-Couch, and Quiller-Couch borrows from the Fowlers. The example records those relationships rather than presenting three voices as independent empirical confirmation.
11. **generate_persona.py → topic loader; README → Thin skills.** The absolute paths are appropriate for local installation, but there is no portable sample mode. Used the requested prefix replacement and comment. The unchanged generated loader also mentions official platform documentation, annotated videos, platform algorithms and view promises although this brain has none; a neutral topic template would fit books and other non-video subjects better.
12. **docs/build-pipeline.md → Evals / template-topic/evals.md.** The pipeline lists evals before skill generation, while cold evals require a generated skill. Generated the sample loader and supplied the eval set; a true cold run is explicitly outstanding. Explain generation of a draft skill before eval, then regeneration after corrections.
13. **README → Keep brains private / AGENTS.md → Privacy.** These correctly protect normal workspaces but do not spell out the public-domain example exception and its provenance obligations. The task supplies that exception; this example documents the exact editions and exclusions.
14. **check_wiki.py gate versus brief acceptance depth.** The gate verified all citations but did not flag a source introduction with only four quotes or two concept pages with only two quotes. A separate manual count caught these and they were strengthened to the brief’s minimum. Document what the gate does and does not enforce.

## Tool behavior and workarounds

No framework tool crashed or required editing. The PDF adapter’s missing catalogue/log side effects and absent section-range option are the main contract gaps. HTML extraction merges some adjacent list lines without spaces; quotes retain exact clean substrings and raw is not repaired. OCR preserves split words and imperfect spacing as the docs warn. The private scrub’s historical-name match was a false positive, resolved by an explicitly scoped fresh capture and verified locator mapping; it was not fixed by mutating raw. Read-only inspection also showed that `requote.py`’s page rewrite regex recognizes timestamp digits/colons, not paragraph labels, so the known paragraph-offset mapping was applied mechanically and verified by the full gate instead of relying on that command. No tool source, tests or framework docs were changed.

## Timings

Times are measured tool wall times where available, not estimates of model work: first web batch 5.98 s; corrected Strunk plus Fowler captures 4.47 s; selected PDF creation plus `book_to_raw.py` 1.57 s; first authored ingest/triage/gate batch 1.65 s; first merge survey/bundles 0.54 s; concept and debate authoring plus gates 1.67 s; finalization plus four checks 1.71 s; fresh Fowler recapture 0.88 s; re-anchor and verification batch 2.67 s. The original PDF download took about three minutes. Scratch was created at 01:45:06 UTC; the main artifacts were finalized by 02:00:54 UTC, with the recapture, privacy audit and build notes following. Initial reading/search was not separately timed. Final completion UTC is appended after the last audit.

Final checks completed at 2026-11-21T02:07:04+00:00. Targeted content/quote-depth/hash/skill assertions passed. Final CLI sequence: `check_wiki.py`, `rule_status.py --write`, `lint_wiki.py --fix-slug-map`, `build_wiki_index.py`, `audit.py`, then verified scratch removal with native PowerShell.

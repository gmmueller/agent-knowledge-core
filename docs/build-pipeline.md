# Build pipeline

Two kinds of brain, two pipelines. A **persona brain** (a course or community) crawls its own sources into `raw/`. A **topic brain** (`kind: topic`) selects items from the shared library. Both end in the same checks, evals and generated skill. See `docs/architecture.md` for the difference.

Run Python tools with `python -I <framework>/tools/<tool>.py …`. Tools that work on one brain take `--brain <brain-folder>`. Tools that only touch the library take `--workspace <workspace>`. `--help` on any tool lists its options.

## Persona brain pipeline

| # | Step | Output | Who |
|---|---|---|---|
| 1 | **Scope.** Who or what, what's in and out, list every source and how to access it | `brain.md` (scope section), `sources.yaml` | orchestrator with user |
| 2 | **Map.** For courses, walk the course outline: modules, lessons, URLs, video host and IDs, attachments | `sources.yaml` filled, `crawl-log.md` | Volume worker (one browser driver per session) |
| 3 | **Crawl.** Download captions or transcripts, lesson text and attachments; parallelize where the session allows it | `raw/<module>/<lesson>.md`, `media/` | Volume workers |
| 4 | **Transcribe.** For videos without captions, transcribe locally with faster-whisper and keep timestamps | `raw/...md` | script run by a subagent |
| 5 | **Verify crawl.** Compare counts against the outline, check for empty or short transcripts, retry failures | `crawl-log.md` | Mechanical worker / script |
| 6 | **Ingest.** Apply the LLM Wiki pattern, one module per task in parallel, then a merge pass | `wiki/` | Volume workers; orchestrator merges |
| 7 | **Extract rules.** Principles, frameworks and rules with quotes; bench vs active | `brain.md`, `wiki/rules/` | orchestrator |
| 8 | **Generate.** Skill from `brain.md` into the explicit output directory (`--out` or `AGENT_KNOWLEDGE_CORE_SKILLS_DIR`) | agent files | orchestrator |
| 9 | **Evaluate.** 5–10 questions with known answers; check citations, drift and inference labels | `evals.md` | orchestrator + user |
| 10 | **Search.** Index `raw/` + `wiki/` with qmd once the brain is past about 100 sources | qmd collection | script |

## Topic brain pipeline

library → catalogue → triage → fetch → speaker pass → ingest waves → merge → debates → evals → skill

| # | Step | Tools and briefs | Output | Who |
|---|---|---|---|---|
| 1 | **Scope.** Experts, extraction areas, evidence types, exclusions, hand-offs to sibling brains. Register each publisher | `template-topic/`; `library/<publisher>/sources.yaml` | `brain.md`, `sources.yaml` per publisher | orchestrator with user |
| 2 | **Catalogue.** List every item of each publisher, metadata only | `library_yt.py catalogue`, `web_to_raw.py list`, `book_to_raw.py` | `catalogue.tsv` | volume worker / script |
| 3 | **Triage.** Score rows against the brain's extraction areas, then merge into tiers | `triage_inputs.py`, `docs/triage.md`, `triage_merge.py`, `selection_override.py` | `ingest/triage/*.tsv`, `selection.yaml` | low-cost volume workers; orchestrator spot-checks |
| 4 | **Fetch.** Fetch the selected items into raw (or staging for multi-speaker items) | `library_yt.py fetch --selection …`, `web_to_raw.py fetch`, `book_to_raw.py` | `library/<publisher>/raw/` | volume worker |
| 5 | **Speaker pass.** Diarize multi-speaker items, name the speakers, finalize | `diarize.py`, `speaker_naming.md`, `finalize_raw.py` | raw with `speakers`, `people.yaml` | script + naming agents |
| 6 | **Examples** (optional). Measure demonstration videos, then annotate them | `example_frames.py`, `check_examples.py`, `link_examples.py` | `library/<publisher>/examples/`, `wiki/examples/` | script + volume workers |
| 7 | **Ingest waves.** Batch workers write source pages and staging; one wave per publisher group | `briefs/topic-ingest-brief.md`, `check_wiki.py` | `wiki/sources/`, `ingest/staging/` | volume workers |
| 8 | **Merge.** Survey concepts, fix duplicate slugs, write bundles, then concept pages | `merge_topic.py survey`, `ingest/slug-map.yaml`, `merge_topic.py bundles`, `briefs/topic-pages-brief.md` | `ingest/bundles/`, `wiki/{topics,principles,…}/` | volume workers; orchestrator plans groups |
| 9 | **Debates.** One page per question on which sources disagree | `briefs/debates-brief.md` | `wiki/debates/` | volume workers |
| 10 | **Rule audit.** Recount rule status by independent voice, lint, rebuild the index | `rule_status.py --write`, `lint_wiki.py --fix-slug-map`, `build_wiki_index.py` | `wiki/rules/`, `index.md` | orchestrator |
| 11 | **Rubrics** (optional). Calibrate scoring checklists with two cold graders | `rubric_agreement.py` | `wiki/rubrics/`, `rubric-calibration/` | volume workers + orchestrator |
| 12 | **Evaluate.** Fresh agent with only the skill answers a fixed set, including traps | `evals.md`, `verify_eval_quotes.py` | `evals-run-<date>.md` | orchestrator |
| 13 | **Skill and search.** Generate the skill; index the wiki and library with qmd | `generate_persona.py`, qmd | skill, qmd collections | orchestrator / script |
| 14 | **Keep current.** Re-catalogue, triage the new rows, ingest a new wave | `docs/updates.md`, `refresh_due.py` | updated wiki | as above |

Work in waves: ingest the best-covered publishers first, run the merge pass on what you have, and check the gate and the evals before adding the next wave. Each wave adds source pages and staging; each merge pass rebuilds bundles and concept pages from all staging so far.

## Raw file format (transcripts)

Persona brains:

```markdown
---
source_id: m03-l02
title: <lesson title>
module: <module title>
url: <lesson url>
video: <host>:<id>
duration: 14:32
captured: YYYY-MM-DD
method: captions | whisper | page-text
---
**[0:00]** text…
**[0:31]** text…
```

Paragraph roughly every 30 seconds, with timestamps kept so citations can deep-link. Library raw files (topic brains) add `publisher`, `kind`, `published`, `speakers` and `speaker_method`; see `docs/library.md`.

## Membership sites (logged-in content)

- Use a **real Chrome window the user logs into**: a dedicated per-brain profile and port (assignments in the private workspace's agent instructions and the port in `crawl.yaml`), opened with `--user-data-dir` and `--remote-debugging-port`, and have agents attach over CDP (Playwright `connect_over_cdp`). This gets past Cloudflare and avoids automation fingerprints. The user does the login and any 2FA; agents never handle the password.
- Prefer the platform's own JSON/API calls made from inside the logged-in page over HTML scraping.
- Video hosts behind course platforms (Wistia, Vimeo, Kajabi's player) often expose captions or a media ID that yt-dlp can fetch. Try captions first, then audio download plus whisper.
- Crawl politely: sequential requests with small delays, no hammering.

## Tool entry points

Run Python tools with `python -I <framework>/tools/<tool>.py --brain <workspace>/my-course` (or `--workspace <workspace>` for library tools). Isolated mode is supported; tools add their own sibling helper directory to the import path.

**Map and crawl (persona brains)**
- Map and inspect: `cdp_status.py`, `cdp_probe.py`, `cdp_lesson_probe.py`, `kajabi_map.py`.
- Skool communities: `skool_session.py` (attach to the logged-in tab), `skool_classroom_map.py`, `skool_classroom_crawl.py`, `skool_feed_index.py`, `skool_feed_stats.py`, `skool_thread_tiers.py`, `skool_thread_crawl.py`, `skool_thread.py`, `skool_attachments.py`, `skool_bulk.py` (chains phases and resumes after a cooldown), `skool_next.py`, `skool_verify.py`, `skool_ingest_batches.py`, `skool_probe.py`, `skool_text.py` (shared parsing). Settings come from `<brain>/crawl.yaml` with `platform: skool`.
- Capture and transcribe: `kajabi_lesson_assets.py`, `wistia_to_raw.py`, `whisper_transcribe.py`, `build_raw.py`, `attachment_to_raw.py`, `yt_to_raw.py`, `whisper_lines.py`, `mux_captions.py`.

**Library (topic brains)**
- Catalogue and fetch: `library_yt.py`, `web_to_raw.py`, `book_to_raw.py` (helpers in `library_raw.py`).
- Speaker pass: `diarize.py`, `speaker_naming.md` (the naming agent's brief), `finalize_raw.py`.
- Examples: `example_frames.py`, `check_examples.py`, `link_examples.py`.
- Triage: `triage_inputs.py`, `triage_merge.py`, `selection_override.py`.

**Ingest and merge**
- Ingest: fill `briefs/ingest-brief.md` (persona) or `briefs/topic-ingest-brief.md` (topic), dispatch isolated batches, run `check_wiki.py` on their source pages and staging.
- Merge, persona brain: `merge_staging.py --brain <path> survey`, resolve duplicate slugs in `ingest/slug-map.yaml`, then `merge_staging.py --brain <path> bundles`. Fill `briefs/pages-brief.md` for concept writers.
- Merge, topic brain: `merge_topic.py --brain <path> survey`, then `slug-map.yaml`, then `merge_topic.py --brain <path> bundles`. Fill `briefs/topic-pages-brief.md` for concept writers and `briefs/debates-brief.md` for debate writers.
- Rule status, topic brain: `rule_status.py --brain <path> [--write]`.

**Check, generate, evaluate**
- Check: `check_wiki.py`, `lint_wiki.py`, `build_wiki_index.py`, `requote.py`; update `wiki/hot.md` and `wiki/log.md` after accepting the changes.
- Evaluate: `verify_eval_quotes.py --brain <path> <answers.md>`; `rubric_agreement.py <grader-a.tsv> <grader-b.tsv>`.
- Generate: `generate_persona.py --brain <path> --out <skills-directory>`.
- Remind: `refresh_due.py --workspace <workspace> --all`.
- Search: `install_qmd.ps1`.

Product headings in the index use registry titles in `sources.yaml` order, with `outline.yaml` titles as fallback. Associate a source with its product using `product:` or `code:`, `crawl.yaml`'s `source_id`, a matching outline product URL, or legacy `(product code main)` notes. Unregistered product codes are still listed.

## Port checks

Run `python -I tests/test_wiki_tools.py --scratch <workspace>/.secrets/scratch` for the targeted offline checks, and `tests/test_topic_checkers.py`, `tests/test_library_tools.py` and `tests/test_skool_tools.py` for the topic, library and Skool tools. On Windows, subprocess output uses the system encoding even under `-I`; the checks decode with that encoding rather than assuming UTF-8. Scratch fixtures are deleted automatically.

## Rule status and independence

Persona brains: `merge_staging.py` keeps a provisional status: one distinct lesson is `bench`, two or more are `active`. The orchestrator reviews independence before accepting a promotion. A lesson and its case-study follow-up count as one source; independent modules or courses provide stronger evidence (or three or more independently supporting lessons). Count an attachment with its lesson, and count community threads as one source kind.

Topic brains: set `rule_status: voices` in `brain.md`. Then `active` needs two or more independent **voices**: distinct speakers after `expert_aliases` (a duo that counts once), `voice_aliases` (platform staff count as the platform) and `hosts` (ignored). `consensus` needs two or more listed experts. `contested` is set by page writers, never by a tool. `rule_status.py` recounts from the bundles and respects `status_locked: true`.

## Lessons learned

Each line says what to do and what happened. They are grouped by stage.

### Crawl

- **Kajabi:** read lesson HTML with in-page `fetch()` + DOMParser (fast, same result as navigating). Attachments 302 to signed S3 URLs that in-page fetch can't follow (CORS): use the context's `ctx.request.get(url, max_redirects=0)` with the browser's User-Agent, then fetch the `location`. Kajabi gives each lesson its own download id for the same file, so dedupe by sha256.
- **Wistia:** `fast.wistia.com/embed/{medias,captions}/<id>.json` are public; captions there are good enough to skip Whisper.
- **Skool access:** fetch `_next/data/<buildId>/<path>.json` and `api2.skool.com` from inside the logged-in tab; course URLs answer with a `__N_REDIRECT` to `?md=<module>`. Page comments with `created-gt=<last>`, not `after`. `POST /files/<id>/download-url?expire=N` returns a signed attachment URL as plain text. Staff roles come from the members list filtered to admins; the gamification role field is not admin.
- **Skool rate limits:** a CDN firewall returned 403 after about 280 requests in 6 minutes. Pacing at 5–7 seconds per request with a 10-minute rest every 60 requests ran about 1,700 requests without a block. Crawlers stop on `RateLimited`; `skool_bulk.py` chains phases and resumes after a cooldown.
- **Video on Skool:** YouTube embeds have good auto-captions; Skool-native video is Mux with an English caption track in the HLS manifest (it needs `Referer` and `Origin` headers); Loom needs Whisper (and some clips are silent intros).
- **Thread files:** two posts can share a date and title slug, so a filename collision must not be treated as an edit. Suffix the post id. `skool_verify.py` checks counts, comment completeness and false `supersedes:`.
- **Lesson ids shift:** ids derived from course position change when the platform inserts lessons at the top. Keep ids in a state file, seeded from the outline, and give new lessons max + 1. A tree-only map has no lesson body, so write a null `content_hash` and compare a hash of the fetched body instead.
- **Refresh runs:** `skool_ingest_batches.py --only-new` skips items already cited or batched and marks edited lessons and existing digests `update: true`. The feed refresh's `changed` list predates the crawls that follow it, so skip threads whose captured count, last comment and hash already match the index.
- **YouTube metadata:** `--flat-playlist` lists a whole channel fast but has no dates or descriptions (short-video tabs especially). Full metadata costs about 3 seconds per video, so fetch details only where triage needs them. Expect 429s and age-gates; `library_yt.py` backs off and logs them.
- **Catalogue TSV:** fields are whitespace-cleaned, so read and write with plain tab splitting. The csv module's escaping round-trip multiplied backslashes on every rewrite.
- **Web pages:** trafilatura handles blogs and docs. JS-rendered or bot-blocked pages need `web_to_raw.py fetch --browser`, which renders them in headless system Chrome.
- **Vendor terms behind accordions:** some legal sections aren't in the served HTML, even with `--browser`. Note the gap on the page rather than paraphrasing the requirement from memory.
- **Check user-supplied PDFs before ingesting.** Look at the first pages. A "book PDF" turned out to be a third-party summary (not primary), another file was a different book with a shared subtitle, and a "full audiobook" video duplicated a book already in the library.
- **Ebook PDF quirks:** shadow-library PDFs stamp a watermark line on every page; drop it with `book_to_raw.py --drop-line "<regex>"`. pypdf returns typographic ligatures and unmapped glyphs as NUL bytes, which make Read and Edit refuse the file; `book_to_raw.py` expands ligatures and maps NUL to U+FFFD. Symbol-font glyphs (game tiles, music notation, chess diagrams) come out as stray letters: tell workers to quote prose only.
- **Papers and scans:** text-layer PDFs convert with pdftotext or pypdf (`raw/paper/`, `@ p. N`). For scanned PDFs, don't have a model transcribe them verbatim: a model copying a copyrighted article page by page was stopped by the API content filter. OCR locally instead (two-column order rebuilt from box positions), set `method: pdf-ocr-model`, and check the scan before quoting.
- **Re-crawls:** after re-crawling a raw file, re-anchor wiki quotes with `requote.py --brain <path>` (review similarity matches before `--apply`; then check exact quotes) instead of re-ingesting.

### Transcripts and speakers

- **Whisper (faster-whisper on Windows):** add the `nvidia/*/bin` wheel dirs with `os.add_dll_directory`, and load 16 kHz WAV with numpy (the bundled PyAV decoder breaks). Always scan output for repeated phrases (`(.{8,80}?)\1{2,}`), not just repeated segments; fix loops with `whisper_transcribe.py --anti-loop` (keeps punctuation). `--no-prev-text` removes loops but loses punctuation.
- **Prefer a publisher's own transcript** (named speakers, timestamps, punctuation) over captions plus diarization. YouTube auto-captions mark turns with `>>` but carry no word offsets.
- **Diarization is about 85% right at turn edges.** Turn-aware ECAPA diarization (`diarize.py`) is the default. Whisper word alignment (`--whisper-words`) did not beat it, so it stays opt-in. Ingest reads quotes in context and logs `speaker_doubts` rather than trusting labels.
- **Duo hosts sound alike to the machine.** When a label is clearly one of two co-hosts but no anchor says which, name it with the duo's name, and map both hosts to that name in `expert_aliases` so the duo counts once.
- **Single-speaker channels play clips of other people.** A block labelled with the channel owner may be a clip. Check that the words are the narrator's before quoting them under their name.
- **Quotes need context.** Exact-match checks miss context flips ("X is dangerous" when the speaker is quoting others). Read rule quotes in context. Label every non-primary speaker on the quote line (`— Other Speaker ([[raw/...]] @ t)`); mixed-presenter Q&As need a speaker pass against the raw text.
- **Host questions are not the guest's claims,** and neither are audience lines.
- **`web_to_raw.py --transcript`** treats any `Label:` at a paragraph start as a speaker, so bullet lists like "Key idea: …" in an interview become fake speakers. For short Q&A articles, capture as a post and note the interviewer prefix in the crawl log.
- **Reader comments** can sit below a page's text. Note the paragraph range in the crawl log and quote only the author's own text.

### Triage

- **Calibrate triage agents.** Split agents score the same channel differently (one gave relevance 3 to 4 items, another to 25, mostly changelogs). Spot-check each file and fix with `selection_override.py`.
- **`selection_override.py` only edits items already in `selection.yaml`.** Append items added by hand outside triage (guest voices, single videos) directly, with `override: A` and a `why`.
- **Excluded content class:** if a whole kind of material is off limits, put the exclusion in the triage brief (relevance 0), filter the obvious titles mechanically before triage, and repeat it as a hard rule in the worker brief and in each batch note that touches such items. Prefer teaching material built on a stand-in.
- **Pre-filter thousands of short videos** to the top by views plus the top per year before any model sees them (`triage_inputs.py --shorts-prefilter`).
- **Example videos:** PySceneDetect's AdaptiveDetector (ratio 3, floor 15, minimum shot 0.1 s) catches jump cuts without flagging handheld shake. A labelled contact sheet per video lets a model read the opening frame, on-screen text and rhythm at a glance.

### Ingest

- **Parallel batch workers write source pages and staging only;** a merge pass builds shared pages from per-concept bundles. Give workers a gold example page, a seed slug vocabulary and `check_wiki.py` as the acceptance gate (it verifies every quote verbatim at its cited block and the speaker against the block's prefix).
- **Cap batches by words and by pages** (at most about 50 source pages per batch). Tell workers to reuse slugs from finished staging files; this kept 1,771 concept entries to 262 slugs.
- **Digest community threads** (for example one monthly Q&A digest) instead of writing one page per thread, so member threads stay as context. `check_wiki.py` verifies thread quotes by comment author (`@ c:<id8>`).
- **Recency:** for fast-moving tool brains, tag every staging point `freshness` (evergreen or tool-version or platform), let `merge_staging.py` attach source dates, and give tool pages a **Current vs dated** section. Limit member threads by age and keep all expert material.
- **Dated facts carry their capture date in the text:** "listed at $174.99 (2026-10-16)".
- **Cut slug sprawl at the source.** Two big books produced 140 new slugs, most of them single-chapter sub-ideas. Budget for a heavy `slug-map.yaml` pass, or tell workers to put sub-parts in the points of one principle slug per chapter.
- **Map items to pages from every field.** Source pages that combine several raw files list one `item`, so a map built from `item` or `items` alone leaves bundle items unmapped. Build `item-pages.tsv` from the union of `item`, `items` and each `sources:` raw file's `publisher/source_id`, then check that every bundle item maps.
- **Mojibake from workers:** writers on some providers wrote `?` for `·` and `–` in dozens of pages; `check_wiki.py` passes these because citations and quotes still resolve. After each wave, diff added lines against HEAD for `]] ? [[`, `\w?\w` and `\d?\d`, and tell writers to write UTF-8, never PowerShell `Set-Content`.
- **No placeholders in paths.** A writer that shortened long raw paths to tokens and planned to substitute them at the end left broken frontmatter when it was stopped. Tell writers to write final paths directly. Then a stopped run can resume by keeping every page that passes the check.
- **Python on Windows:** `python3` is the Microsoft Store alias stub and hangs in agent shells. Tell workers to use the venv's `python -I`, never `python3`. A bare `python -` (script on stdin) with no heredoc also hangs: workers left stuck background jobs that way. Tell them to write a script file or use `-c`.
- **`sed -i` in Git Bash** rewrites CRLF files as LF, and with `autocrlf=true` every file it touches shows as modified. Run it only on the files that need the change, never on a glob.
- **Stalled delegates:** a delegated run can stall silently (status "running", no thread activity). If a batch has written nothing after about 20 minutes, check the child thread's last update, cancel it and rerun it on another provider.
- **Spend limit mid-wave:** a monthly org limit killed a fifth of the workers mid-run. Their work was saved: after the reset, resume each worker with a message that states which pages and staging files already exist, instead of starting new agents.
- **Scale:** dozens of page-writing workers (33 page groups plus 7 debates, up to 23 at once) ran with no rate-limit failures. Each group passed the gate the first time it reported.

### Merge

- **Order matters:** launch debates once their concept groups finish, and variant or hub pages last (they link every page of their variant).
- **Journalists relay researchers.** Voice counting treats a journalist who retells a listed expert's study as a second voice. Tell workers to write "X, relaying Y" in the point text, and lock relayed agreements with `status_locked` after the recount.
- **One author repeating a rule is one voice.** Counting "2+ publishers or 3+ items" promoted 26 rules that a single author repeated across a book and talks. Count voices (`rule_status: voices`), then recount with `rule_status.py --write` and grep the rule pages for prose that still names the old status.
- **Partial agreement:** voice counting promotes a rule as soon as a second expert's points land in its bundle. When a second voice backs only half a rule, or a different context, set `status_locked: true` and a `status_note`.
- **Debate-listed rules aren't contested by default.** Set `contested` only when a source argues against the rule itself. Debate writers report a recommended status. Check an ingest "conflict" before building a debate on it: an apparent disagreement can turn out to be agreement on a closer read.
- **Slug drift:** source pages written before the slug map keep links to merged slugs. Run `lint_wiki.py --fix-slug-map` after the merge pass.
- **Quotes with inner quote marks:** `check_wiki.py` finds the closing mark by the `— Speaker` that follows it, so quotes that contain quotation marks parse.

### Evals and rubrics

- **Calibrate every rubric.** A 0/1/2 scale without anchors gives different scores from different graders. Use 8 to 10 non-overlapping criteria, each with a concrete **Test** and cited 0/1/2 anchors (experts' own before/after examples for the low end, annotated examples for the high end), plus a calibration set. Have two cold graders score held-out items and synthetic items written to spread scores, compare with `rubric_agreement.py`, and turn each disagreement into an edge-case rule. Expect three runs to reach 83 to 100% exact agreement per criterion.
- **A rubric is a gate and a diagnosis, not a forecast.** Test it on the owner's real content too: in one trial, hook scores did not predict views but cut rhythm did.
- **Run evals cold:** a fresh agent with only the generated skill answers each item. Grade pass, partial or fail against `must include` and `must not` points. Run `verify_eval_quotes.py` on the answers.
- **Include trap items:** a question with a missing premise, a request that breaks a hard rule, a claim the research doesn't support, and a premise that is wrong.
- **Fix the eval when the eval is wrong.** If a graded failure traces to an eval criterion that contradicts the sources, correct the criterion and say so in the run file.
- **A rebuilt wiki must score at least as well** as the one it replaces.

### Skills and search

- **`generate_persona.py --out` takes the skills parent folder.** Passing the skill folder itself writes a nested `<brain>/<brain>/` copy. Then run your sync step.
- **Sync scripts that mirror a whole skills folder** also copy other people's in-place edits. When only brain skills changed, copy those folders instead.
- **qmd on Windows:** under Node, qmd crashes (access violation) when loading sqlite-vec, so run it under Bun. `install_qmd.ps1` installs it and rewrites the npm shims; re-run it after every qmd upgrade. Index each persona brain as two collections, `<brain>-wiki` and `<brain>-raw`, each with a `qmd context`. Topic brains get `<brain>-wiki` only and share the `library` collection. Register the MCP server in your agent tooling as `bun <npm>\node_modules\@tobilu\qmd\dist\cli\qmd.js mcp`.

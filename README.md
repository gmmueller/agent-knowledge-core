# Agent Knowledge Core

![Tests](https://github.com/gmmueller/agent-knowledge-core/actions/workflows/tests.yml/badge.svg)

**A central, cited knowledge core your agents consult, built from experts' own words.**

Turn experts' own material (a course, a community, a video library, blogs or books) into **brains**: cited, LLM-maintained wikis, each with a skill card that an AI agent can load. All your brains live in one private workspace on one shared source library, so every agent in every project consults the same knowledge instead of keeping its own copy. Every claim traces back to a timestamped transcript, every quote is checked word for word, and anything the material doesn't support is labelled **Inference:**.

There are two kinds of brain:

- A **persona brain** is one teacher's course or community. It answers in the expert's frameworks and voice.
- A **topic brain** combines several experts on one subject, drawing on a shared **library** of sources crawled once. It has no imitated voice: it applies the experts' methods, names whose they are, and shows where they disagree.

It is built on Andrej Karpathy's "LLM wiki" idea, extended with a crawl → transcribe → ingest → merge → persona → eval pipeline, verification tooling, and parallel delegation to cheaper models for the volume work.

## Use it responsibly

- **Use it only on material you have the right to use.** That means your own content, openly licensed or public-domain material, or courses and communities you have paid for and may use personally.
- **The course and community crawlers are personal-use tools.** They drive *your own* logged-in browser session, see only what your account can see, and never handle your password. Read the platform's terms before you crawl it, keep request rates low, and don't use them to get around a paywall or access you don't have.
- **Keep brains private.** Your brains live in your own private workspace, never in this repo. Paid course content is typically licensed for personal use only: don't publish, share or sell brains built from it.
- **Public-domain exception.** [`examples/`](examples/) is the one brain stored in this repo. It uses only verified public-domain books, with exact edition details and retrieval URLs recorded in each publisher's `sources.yaml`, raw frontmatter and crawl log.

## How it works

Persona brain:

```
sources ──crawl──▶ raw/ ──ingest──▶ wiki/ ──extract──▶ brain.md ──generate──▶ persona skill
 (logged-in        (immutable       (source pages,     (scope, voice,           (loads brain.md
  browser, CDP)     transcripts,     concept pages,     rules with quotes,       and wiki at
                    page text,       rules, glossary)   task loop)               use time)
                    attachments)
```

1. **Scope and map.** List every source in `sources.yaml`. For course platforms, map products → modules → lessons → video IDs into `outline.yaml`, crawling through a real Chrome window you log into (the agent never handles passwords).
2. **Crawl and transcribe.** Prefer the video host's own captions; fall back to local Whisper on your GPU. Lesson page text and attachments (PDFs, images) become text too. `raw/` is immutable: fix problems by re-crawling.
3. **Ingest in parallel.** Batch workers write one source page per lesson plus staging notes (`briefs/ingest-brief.md`). `check_wiki.py` is the gate: every citation must resolve and every quote must be verbatim at its cited timestamp.
4. **Merge.** Pool the staging notes per concept (`merge_staging.py`), map duplicate slugs, and have workers write the shared concept pages (`briefs/pages-brief.md`): topics, principles, frameworks, methods, rules and glossary.
5. **Persona.** Write `brain.md` (scope, voice, worldview, rules with exact quotes, framework map, task loop, boundaries), then generate a thin skill from it (`generate_persona.py`).
6. **Evaluate.** Run a fixed question set with known answers through a fresh agent that has only the skill (`evals.md`), and grade every answer.
7. **Keep it current.** Incremental refreshes from a cursor in `sources.yaml`, with configurable reminders (`refresh_due.py`), plus local search over `raw/` and `wiki/` with [qmd](https://github.com/tobi/qmd).

Topic brain:

```
library ─▶ catalogue ─▶ triage ─▶ fetch ─▶ speaker pass ─▶ ingest waves ─▶ merge ─▶ debates ─▶ draft skill ─▶ evals ─▶ skill
(crawled    (metadata   (score     (raw     (who said      (source pages  (bundles, (where     (generated     (cold    (regenerated
 once per    for every   items;     files)   what)          + staging)     concept    experts   from           agent,   if brain.md
 publisher)  item)       tiers)                                            pages)     disagree) brain.md)      traps)   changed)
```

1. **Library.** Each publisher (a channel, blog, podcast, author or vendor) is crawled once into `library/<publisher>/raw/`. `library/people.yaml` records who speaks where.
2. **Catalogue and triage.** List every item, then score each against the brain's extraction areas. `triage_merge.py` turns the scores into `selection.yaml`: tier A (deep ingest), B (raw and search only), C (skip), X (annotate as an example).
3. **Fetch and speaker pass.** Fetch the selected items. For interviews and panels, diarization clusters the voices, a naming agent labels them, and `finalize_raw.py` writes the raw file with speakers.
4. **Ingest waves.** Batch workers write source pages and staging (`briefs/topic-ingest-brief.md`). Every quote names its speaker, and `check_wiki.py` verifies the speaker against the cited block.
5. **Merge.** `merge_topic.py` pools staging into per-concept bundles. Workers write the concept pages (`briefs/topic-pages-brief.md`) and then the debate pages (`briefs/debates-brief.md`). `rule_status.py` recounts rule status by independent voice.
6. **Generate, evaluate and refine.** Generate a draft skill (`generate_persona.py`), have a fresh agent with only that skill answer `evals.md` (including trap questions), verify its quotes with `verify_eval_quotes.py`, fix gaps, and regenerate the skill if `brain.md` or rule counts changed.

Rules start as `bench` (one source or voice) and become `active` once they're backed by independent sources. Topic brains add `consensus` (two or more listed experts) and `contested` (a source argues against the rule, with a debate page). Quotes by anyone other than the expert carry the speaker's name.

## Layout

```
AGENTS.md / CLAUDE.md   rules for any agent working in a workspace
docs/                   architecture, build pipeline (with lessons learned by stage), token budget, updates, library
                        and triage (shared sources for topic brains), councils, tech choices, references
template/               copy to start a persona brain: brain.md, sources.yaml, crawl.yaml, crawl-log.md, raw/, wiki/, notes/
template-topic/         copy to start a topic brain: brain.md (topic keys), selection.yaml, evals.md, ingest/, wiki/ with every topic page folder, notes/
briefs/                 ingest, page-writing and debate-writing briefs for parallel workers (persona and topic versions)
tools/                  brain tools take --brain <folder>; library and workspace tools take --workspace <folder>
tests/                  unit tests for the wiki, topic, library, Skool, Obsidian, edit-guard and platform tools; acceptance harness for the source adapters
examples/               complete public-domain topic brain (Plain Writing) built from three books, with generated portable skill
```

Your **workspace** is a separate private folder (its own git repo, no remote):

```
my-brains/
  .secrets/             browser profiles, caches, scratch (never committed)
  library/              shared sources for topic brains: people.yaml and one folder per publisher (raw/, catalogue.tsv, …)
  my-course/            a persona brain: brain.md, sources.yaml, crawl.yaml, outline.yaml, raw/, wiki/, notes/, media/ (gitignored)
  my-topic/             a topic brain: brain.md, selection.yaml, evals.md, ingest/, wiki/, notes/ (cites library/)
```

## One core, every project

The workspace is the single home for everything your agents know from these sources. You build each brain once, there, and every agent in every project consults that same copy.

- **Thin skills, live brains.** `generate_persona.py` writes a small skill (`SKILL.md`, plus `agents/openai.yaml` for Codex) into your agent's **user-level** skills folder, for example `~/.claude/skills/` for Claude Code. The skill holds no knowledge itself. By default it points by absolute path at the brain's `brain.md`, `wiki/` and sources, and the agent reads them at use time (pass `--relative-to <dir>` for a portable sample skill).
- **Subject-neutral core, per-brain rules.** The generated wording is subject-neutral (topic brains link `wiki/examples/` automatically when present). Each brain adds its own guidance and boundaries in `brain.md` (`skill.guidance`, `skill.boundaries`), and the generator prints `consider skill.guidance:` suggestions based on the brain's contents when none are set yet.
- **Every project sees the same brain.** A user-level skill is available in every project on the machine. An agent writing a script in one repo and an agent planning content in another consult the same cited pages.
- **Update once, everywhere current.** Refresh a brain (`refresh_due.py` says when) and the next use in every project reads the new pages. Regenerate the skill when `brain.md` (`skill:` settings, name or scope) or rule counts change.
- **Search across all of it.** Index `raw/`, `wiki/` and `library/` with [qmd](https://github.com/tobi/qmd) and any agent can search every brain from one local search server (MCP).
- **Agents that don't read skills** can still use a brain: point them at `brain.md` and `wiki/index.md` and tell them to follow the "How to use it" steps in the generated `SKILL.md`.

## Example

A complete topic brain built from three public-domain books (Strunk, Quiller-Couch, and H. W. & F. G. Fowler) lives in [`examples/`](examples/README.md). It was built from the framework docs alone.

Open first:

- [`examples/README.md`](examples/README.md) — overview and verification commands.
- [`examples/workspace/plain-writing/brain.md`](examples/workspace/plain-writing/brain.md) — the topic brain card.
- [`examples/workspace/plain-writing/wiki/index.md`](examples/workspace/plain-writing/wiki/index.md) — the compiled wiki (16 source pages, 22 concept pages, 2 debate pages).
- [`examples/skills/plain-writing/SKILL.md`](examples/skills/plain-writing/SKILL.md) — the generated portable skill.

## Setup (Windows, macOS, Linux)

Requires Python 3.11+. Create and activate a virtual environment from the repo root:

| Step | Windows (PowerShell) | macOS / Linux (bash) |
|---|---|---|
| Create venv | `python -m venv .venv` | `python3 -m venv .venv` |
| Activate venv | `.\.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` |
| Without activation | `.\.venv\Scripts\python.exe` | `.venv/bin/python` |

With the venv active, install the core dependencies (which `requirements.txt` pulls from `requirements-core.txt`; heavy extras such as Whisper, torch and opencv are commented optional groups in `requirements.txt`):

```sh
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Every `python -X utf8 -I tools/...` command below works identically in PowerShell and bash once the venv is active.

## Quick start: persona brain

Create a private workspace and copy the template:

```powershell
# Windows (PowerShell)
mkdir ..\my-brains; Copy-Item -Recurse template ..\my-brains\my-course
```

```bash
# macOS / Linux (bash)
mkdir -p ../my-brains && cp -r template ../my-brains/my-course
```

Fill in `my-course/brain.md` (scope), `sources.yaml` and `crawl.yaml` (`site`, `cdp_port`, `profile`, products, Whisper prompt), then run with the venv active:

```sh
# 1. Start the brain's dedicated Chrome profile (reads crawl.yaml, stores profile under .secrets/), log in, then map
python -X utf8 -I tools/launch_chrome.py --brain ../my-brains/my-course
python -X utf8 -I tools/kajabi_map.py --brain ../my-brains/my-course

# 2. Crawl, transcribe and assemble raw/
python -X utf8 -I tools/kajabi_lesson_assets.py --brain ../my-brains/my-course --all
python -X utf8 -I tools/whisper_transcribe.py --brain ../my-brains/my-course --all-uncaptioned
python -X utf8 -I tools/build_raw.py --brain ../my-brains/my-course
python -X utf8 -I tools/build_raw.py --brain ../my-brains/my-course --verify

# 3. Ingest with parallel workers (briefs/), then gate, merge, lint and index
python -X utf8 -I tools/check_wiki.py --brain ../my-brains/my-course
python -X utf8 -I tools/merge_staging.py --brain ../my-brains/my-course survey
python -X utf8 -I tools/lint_wiki.py --brain ../my-brains/my-course
python -X utf8 -I tools/build_wiki_index.py --brain ../my-brains/my-course

# 4. Generate a draft skill, run evals with a fresh agent, fix gaps, then regenerate if brain.md changed
python -X utf8 -I tools/generate_persona.py --brain ../my-brains/my-course --out ~/.claude/skills

# 5. Refresh reminders across all brains
python -X utf8 -I tools/refresh_due.py --workspace ../my-brains
```

## Quick start: topic brain

Copy the topic template into your private workspace:

```powershell
# Windows (PowerShell)
Copy-Item -Recurse template-topic ..\my-brains\my-topic
```

```bash
# macOS / Linux (bash)
cp -r template-topic ../my-brains/my-topic
```

Fill in `my-topic/brain.md` (`experts`, `expert_aliases`, `hosts`, `evidence_types`, extraction areas, scope and boundaries) and create `../my-brains/library/<publisher>/sources.yaml` for each publisher (`docs/library.md`), then run with the venv active:

```sh
# 1. Catalogue a publisher (metadata only), then cut and score triage inputs
python -X utf8 -I tools/library_yt.py --workspace ../my-brains catalogue example-publisher
python -X utf8 -I tools/triage_inputs.py --brain ../my-brains/my-topic example-publisher
#    give each file in my-topic/ingest/triage/input/ to a triage agent (docs/triage.md); rows land in ingest/triage/
python -X utf8 -I tools/triage_merge.py --brain ../my-brains/my-topic

# 2. Fetch the selected items; run the speaker pass on interviews and panels
python -X utf8 -I tools/library_yt.py --workspace ../my-brains fetch example-publisher --selection ../my-brains/my-topic/selection.yaml
python -X utf8 -I tools/diarize.py --workspace ../my-brains example-publisher yt-abc123
#    a naming agent follows tools/speaker_naming.md, then:
python -X utf8 -I tools/finalize_raw.py --workspace ../my-brains example-publisher yt-abc123

# 3. Ingest waves: fill in briefs/topic-ingest-brief.md, dispatch batches, gate each one
python -X utf8 -I tools/check_wiki.py --brain ../my-brains/my-topic

# 4. Merge: survey, resolve duplicate slugs in ingest/slug-map.yaml, bundle, then write pages and debates
python -X utf8 -I tools/merge_topic.py --brain ../my-brains/my-topic survey
python -X utf8 -I tools/merge_topic.py --brain ../my-brains/my-topic bundles
#    fill in briefs/topic-pages-brief.md and briefs/debates-brief.md; dispatch writers by page group

# 5. Audit rules, lint and index
python -X utf8 -I tools/rule_status.py --brain ../my-brains/my-topic --write
python -X utf8 -I tools/lint_wiki.py --brain ../my-brains/my-topic --fix-slug-map
python -X utf8 -I tools/build_wiki_index.py --brain ../my-brains/my-topic

# 6. Generate a draft skill, run cold evals with a fresh agent, check quotes, fix gaps, then regenerate
python -X utf8 -I tools/generate_persona.py --brain ../my-brains/my-topic --out ~/.claude/skills
python -X utf8 -I tools/verify_eval_quotes.py --brain ../my-brains/my-topic answers.md
```

**Books and text-only sources:** skip the speaker pass for single-author books and articles (`speaker_method: single`). Capture PDFs with `book_to_raw.py` (which also updates `catalogue.tsv` and `crawl-log.md`) and web chapters with `web_to_raw.py fetch`:

```sh
python -X utf8 -I tools/book_to_raw.py --workspace ../my-brains example-author book.pdf --slug example-book --title "Example Book" --author "Example Author" --published 1920 --pages 1-12,40-55
python -X utf8 -I tools/web_to_raw.py --workspace ../my-brains fetch example-author --urls https://example.com/chapter-1 --from-heading "Chapter 1" --to-heading "Chapter 2"
```

See [`examples/README.md`](examples/README.md) for a full text-only topic brain. The full step-by-step guides, with model assignments and lessons learned by stage, are in [docs/build-pipeline.md](docs/build-pipeline.md). See [docs/token-budget.md](docs/token-budget.md) for keeping orchestrator and worker token costs low across phases.

## View and edit in Obsidian

Each brain is an independent core and opens in place as its own Obsidian vault: the **brain folder itself** (never `<brain>/wiki/`, and never merged with unrelated brains into one vault or graph).

Set up one brain, or every brain in a workspace:

```sh
# One brain
python -X utf8 -I tools/obsidian_setup.py --brain ../my-brains/my-course

# Every brain in a workspace (also writes ../my-brains/.cores-hub/ with links to open each core)
python -X utf8 -I tools/obsidian_setup.py --workspace ../my-brains --all --gitignore-hub
```

Then open the brain folder in Obsidian with **Open folder as vault**. Setup hides working folders (`ingest/`, `media/`, `state/`, `library/`) from search and graph, colors the graph by page type (showing `wiki/` and `notes/`), creates `notes/`, adds `/library` and `/.obsidian/workspace*.json` to the brain's `.gitignore`, and for topic brains creates a `library` directory link (junction on Windows, symlink elsewhere) so library citations open the real source file. It merges into existing `.obsidian/` settings; pass `--reset` to rewrite them. With `--all`, `<workspace>/.cores-hub/` lists every core with `obsidian://open?path=...` links; open each brain folder as a vault once in Obsidian before those links work from elsewhere.

**What you may edit:**

- **`wiki/` pages:** edit directly in Obsidian or any editor. Initialize the baseline once with `python -X utf8 -I tools/wiki_edits.py --brain <brain> record --init`. Once you edit a page, `wiki_edits.py` flags it and protects it during agent runs (agents start every pass with `wiki_edits.py begin`, skip protected pages, and save proposed updates in `ingest/proposals/` via `wiki_edits.py propose`). Review changes with `status` / `proposals` and confirm your edits with `accept <page>` or `accept --all`.
- **`notes/`:** your own folder. Add, edit or delete anything there; notes may link to wiki pages. Agents never touch `notes/`, wiki pages never cite notes as sources, checks ignore them, and `build_wiki_index.py` lists them under **Your notes**.
- **Never edit `raw/` or `library/`:** captured sources are immutable. Capture tools hash every file they write (`raw/.capture-hashes.json`, `library/<publisher>/.capture-hashes.json`), and `raw_guard.py check` and `lint_wiki.py` warn if any raw file changed after capture. Fix source problems by re-crawling.

## Tools

**Map and crawl (persona brains)**

| Tool | Does |
|---|---|
| `launch_chrome.py` | launch a brain's dedicated Chrome/Chromium profile (`--brain <brain> [--chrome <exe>]`), reading `site`, `cdp_port` and `profile` from `crawl.yaml` and keeping profiles under `<workspace>/.secrets/` |
| `kajabi_map.py`, `kajabi_lesson_assets.py`, `cdp_*.py` | map a Kajabi site; fetch lesson page text and attachments through the logged-in browser (CDP) |
| `skool_*.py` | map, crawl, verify and batch a Skool community through the logged-in browser (settings in `crawl.yaml`) |
| `wistia_to_raw.py`, `yt_to_raw.py`, `mux_captions.py` | video-host captions → timestamped transcript |
| `whisper_transcribe.py`, `whisper_lines.py` | local Whisper (faster-whisper) for videos without captions; `--anti-loop` against repetition loops |
| `build_raw.py`, `attachment_to_raw.py` | assemble one raw file per lesson (transcript + page text) and per PDF; `--verify` checks counts and words per minute |

**Library (topic brains)**

| Tool | Does |
|---|---|
| `library_yt.py` | catalogue YouTube channels and feeds; fetch captions or audio into raw or staging |
| `web_to_raw.py` | catalogue and capture blogs, docs and transcript pages (`--browser` for JS-built pages; `--from-heading` / `--to-heading` select sections before capture on paragraph pages) |
| `book_to_raw.py` | user-supplied book or paper PDF → one raw file, one block per page (`--published` accepts `YYYY`, `YYYY-MM` or `YYYY-MM-DD`; `--pages 1-12,40-55` keeps original PDF page numbers); updates `catalogue.tsv` and appends to `crawl-log.md` |
| `diarize.py`, `finalize_raw.py`, `speaker_naming.md` | speaker pass: cluster voices, name them (the naming agent's brief), write raw with speakers |
| `example_frames.py`, `check_examples.py`, `link_examples.py` | measure demonstration videos (cuts, frames); check that example pages cite only their own video; link examples from concept pages |
| `library_raw.py` | shared helpers: paths, slugs, catalogue read and write, raw writing |

**Triage, ingest and merge**

| Tool | Does |
|---|---|
| `triage_inputs.py`, `triage_merge.py`, `selection_override.py` | cut catalogues into triage inputs; merge scores into `selection.yaml`; hand overrides |
| `check_wiki.py` | gate: frontmatter, citations resolve, quotes verbatim at the cited block, speakers match, claims cited (does not enforce minimum quote counts or synthesis depth) |
| `wave_report.py` | check a finished wave of batches at once (`--batches`, `--wave`): staging files, source pages, `check_wiki.py`, `?` corruption scan and protected pages |
| `requote.py` | re-anchor quotes (timestamps, `¶N` paragraph and `p. N` page locators) after a raw file is re-crawled |
| `merge_staging.py` (persona), `merge_topic.py` (topic) | pool ingest staging by concept → per-concept bundles |
| `rule_status.py` | recount topic-brain rule status by independent voice |
| `skool_ingest_batches.py` | cut a Skool brain into ingest batches (`--only-new` for refreshes) |

**Check, evaluate and generate**

| Tool | Does |
|---|---|
| `lint_wiki.py`, `build_wiki_index.py` | broken links, orphans, rule status, slug drift (`--fix-slug-map`), human-edit/proposal/raw-change warnings; rebuild `index.md` (lists `notes/` under **Your notes** and records the wiki baseline) |
| `obsidian_setup.py` | configure a brain folder in place as its own Obsidian vault (`.obsidian/` settings, `notes/`, topic-brain `library` link, `.gitignore`; `--workspace <ws> --all [--gitignore-hub] [--reset]` also writes `.cores-hub/`) |
| `wiki_edits.py` | detect and protect human edits in `wiki/` (`record --init`, `begin`, `status`, `propose`, `proposals`, `accept`) so agent passes never overwrite them |
| `raw_guard.py` | hash captured `raw/` and `library/*/raw/` files (`record --init`, `check`) so post-capture raw edits are caught |
| `content_hashes.py` | shared SHA-256 hash-manifest and file-lock helpers used by `wiki_edits.py` and `raw_guard.py` |
| `verify_eval_quotes.py`, `rubric_agreement.py` | check quotes in eval answers; compare two graders' rubric scores |
| `generate_persona.py` | `brain.md` → subject-neutral skill (`SKILL.md` + agent metadata), persona or topic version; reads optional `skill.guidance` and `skill.boundaries` from `brain.md`, prints `consider skill.guidance:` hints when none are set, links `wiki/examples/` when present (`--relative-to <dir>` writes portable relative paths) |
| `refresh_due.py` | which brains, sources or tool pages are due for a refresh (per-brain on/off switch, per-source cadence) |
| `token_report.py` | measure token usage and input-equivalent cost across Claude Code transcripts, Codex sessions and optional T3 Code DB (`--workspace`, `--since`, `--ctx-warn`, `--json`) |
| `install_qmd.ps1` | install qmd and run it under Bun on Windows (macOS/Linux: `npm install -g @tobilu/qmd`) |

`requirements.txt` installs `requirements-core.txt` by default; optional heavy groups (Whisper, torch/diarization, OpenCV/frames) are commented inside `requirements.txt`. External programs `yt-dlp` and `ffmpeg` must be on `PATH`.

## Platform notes

- **Python flags:** run tools with `-X utf8 -I` (UTF-8 I/O and isolated mode) on Windows, macOS and Linux. The tools add their own folder to the import path.
- **`python` vs `python3`:** use `python3` only to create the venv on macOS and Linux. On Windows, never use the `python3` Microsoft Store alias (it hangs in agent shells), and never pipe a script into a bare `python -`.
- **Chrome:** use `python -X utf8 -I tools/launch_chrome.py --brain <brain> [--chrome <executable>]` on every OS to open the brain's dedicated Chrome/Chromium profile with remote debugging.
- **qmd:** on Windows, Node crashes loading `sqlite-vec`, so run `tools/install_qmd.ps1` to run qmd under Bun. On macOS and Linux, install with `npm install -g @tobilu/qmd`; on macOS, run `brew install sqlite` first (per [tobi/qmd](https://github.com/tobi/qmd)).
- **Whisper:** uses CUDA when available, otherwise CPU (no Apple GPU backend). On Windows, the NVIDIA cuBLAS/cuDNN wheels' DLL folders are registered automatically.
- **External tools:** `yt-dlp` and `ffmpeg` must be installed and on `PATH` for video/audio fetching and transcription.
- **CI:** the test suite runs automatically on Windows, macOS and Linux. More details are in the lessons-learned section of [docs/build-pipeline.md](docs/build-pipeline.md).

## License

MIT. See [LICENSE](LICENSE).

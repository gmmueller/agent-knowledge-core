# Agent Knowledge Core

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
- The example brain in [`examples/`](examples/) is built only from public-domain books.

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
library ─▶ catalogue ─▶ triage ─▶ fetch ─▶ speaker pass ─▶ ingest waves ─▶ merge ─▶ debates ─▶ evals ─▶ skill
(crawled    (metadata   (score     (raw     (who said      (source pages  (bundles, (where     (cold    (generated
 once per    for every   items;     files)   what)          + staging)     concept    experts   agent,   from
 publisher)  item)       tiers)                                            pages)     disagree) traps)   brain.md)
```

1. **Library.** Each publisher (a channel, blog, podcast, author or vendor) is crawled once into `library/<publisher>/raw/`. `library/people.yaml` records who speaks where.
2. **Catalogue and triage.** List every item, then score each against the brain's extraction areas. `triage_merge.py` turns the scores into `selection.yaml`: tier A (deep ingest), B (raw and search only), C (skip), X (annotate as an example).
3. **Fetch and speaker pass.** Fetch the selected items. For interviews and panels, diarization clusters the voices, a naming agent labels them, and `finalize_raw.py` writes the raw file with speakers.
4. **Ingest waves.** Batch workers write source pages and staging (`briefs/topic-ingest-brief.md`). Every quote names its speaker, and `check_wiki.py` verifies the speaker against the cited block.
5. **Merge.** `merge_topic.py` pools staging into per-concept bundles. Workers write the concept pages (`briefs/topic-pages-brief.md`) and then the debate pages (`briefs/debates-brief.md`). `rule_status.py` recounts rule status by independent voice.
6. **Evaluate and generate.** A fresh agent with only the skill answers `evals.md`, including trap questions; `verify_eval_quotes.py` checks its quotes. `generate_persona.py` writes the skill.

Rules start as `bench` (one source or voice) and become `active` once they're backed by independent sources. Topic brains add `consensus` (two or more listed experts) and `contested` (a source argues against the rule, with a debate page). Quotes by anyone other than the expert carry the speaker's name.

## Layout

```
AGENTS.md / CLAUDE.md   rules for any agent working in a workspace
docs/                   architecture, build pipeline (with lessons learned by stage), updates, library and triage
                        (shared sources for topic brains), councils, tech choices, references
template/               copy to start a persona brain: brain.md, sources.yaml, crawl.yaml, crawl-log.md, raw/, wiki/
template-topic/         copy to start a topic brain: brain.md (topic keys), selection.yaml, evals.md, ingest/, wiki/ with every topic page folder
briefs/                 ingest, page-writing and debate-writing briefs for parallel workers (persona and topic versions)
tools/                  brain tools take --brain <folder>; library and workspace tools take --workspace <folder>
tests/                  unit tests for the wiki, topic, library and Skool tools; acceptance harness for the source adapters
```

Your **workspace** is a separate private folder (its own git repo, no remote):

```
my-brains/
  .secrets/             browser profiles, caches, scratch (never committed)
  library/              shared sources for topic brains: people.yaml and one folder per publisher (raw/, catalogue.tsv, …)
  my-course/            a persona brain: brain.md, sources.yaml, crawl.yaml, outline.yaml, raw/, wiki/, media/ (gitignored)
  my-topic/             a topic brain: brain.md, selection.yaml, evals.md, ingest/, wiki/ (cites library/)
```

## One core, every project

The workspace is the single home for everything your agents know from these sources. You build each brain once, there, and every agent in every project consults that same copy.

- **Thin skills, live brains.** `generate_persona.py` writes a small skill (`SKILL.md`, plus `agents/openai.yaml` for Codex) into your agent's **user-level** skills folder, for example `~/.claude/skills/` for Claude Code. The skill holds no knowledge itself. It points by absolute path at the brain's `brain.md`, `wiki/` and sources, and the agent reads them at the moment it uses the skill.
- **Every project sees the same brain.** A user-level skill is available in every project on the machine. An agent writing a script in one repo and an agent planning content in another consult the same cited pages.
- **Update once, everywhere current.** Refresh a brain (`refresh_due.py` says when) and the next use in every project reads the new pages. Regenerate the skill only when `brain.md`'s name, description or scope changes.
- **Search across all of it.** Index `raw/`, `wiki/` and `library/` with [qmd](https://github.com/tobi/qmd) and any agent can search every brain from one local search server (MCP).
- **Agents that don't read skills** can still use a brain: point them at `brain.md` and `wiki/index.md` and tell them to follow the "How to use it" steps in the generated `SKILL.md`.

## Quick start: persona brain

```powershell
# 1. Tools (Python 3.11+; use a venv)
python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt; .\.venv\Scripts\playwright install chromium

# 2. A private workspace and a brain from the template
mkdir ..\my-brains; Copy-Item -Recurse template ..\my-brains\my-course
#    fill in my-course\brain.md (scope), sources.yaml and crawl.yaml (site, CDP port, products, whisper prompt)

# 3. Log in through a dedicated Chrome profile with remote debugging, then map the course
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="..\my-brains\.secrets\chrome-my-course" --remote-debugging-port=9222 https://courses.example.com/login
.\.venv\Scripts\python -I tools\kajabi_map.py --brain ..\my-brains\my-course

# 4. Crawl, transcribe and assemble raw/
.\.venv\Scripts\python -I tools\kajabi_lesson_assets.py --brain ..\my-brains\my-course --all
.\.venv\Scripts\python -I tools\whisper_transcribe.py --brain ..\my-brains\my-course --all-uncaptioned
.\.venv\Scripts\python -I tools\build_raw.py --brain ..\my-brains\my-course
.\.venv\Scripts\python -I tools\build_raw.py --brain ..\my-brains\my-course --verify

# 5. Ingest with parallel workers (briefs/), then gate, merge, lint and index
.\.venv\Scripts\python -I tools\check_wiki.py --brain ..\my-brains\my-course
.\.venv\Scripts\python -I tools\merge_staging.py --brain ..\my-brains\my-course survey
.\.venv\Scripts\python -I tools\lint_wiki.py --brain ..\my-brains\my-course
.\.venv\Scripts\python -I tools\build_wiki_index.py --brain ..\my-brains\my-course

# 6. Persona skill (point --out at your agent's skills folder), then run evals with a fresh agent
.\.venv\Scripts\python -I tools\generate_persona.py --brain ..\my-brains\my-course --out $HOME\.claude\skills

# 7. Refresh reminders across all brains
.\.venv\Scripts\python -I tools\refresh_due.py --workspace ..\my-brains
```

## Quick start: topic brain

```powershell
# 1. Tools and a workspace (as above), then a topic brain from its template
Copy-Item -Recurse template-topic ..\my-brains\my-topic
#    fill in my-topic\brain.md: experts, expert_aliases, hosts, evidence_types, extraction areas, scope and boundaries
#    make ..\my-brains\library\<publisher>\sources.yaml for each publisher (see docs/library.md)
$ws = "..\my-brains"; $brain = "$ws\my-topic"

# 2. Catalogue a publisher (metadata only), then cut and score triage inputs
.\.venv\Scripts\python -I tools\library_yt.py --workspace $ws catalogue example-publisher
.\.venv\Scripts\python -I tools\triage_inputs.py --brain $brain example-publisher
#    give each file in my-topic\ingest\triage\input\ to a triage agent (docs/triage.md); rows land in ingest\triage\
.\.venv\Scripts\python -I tools\triage_merge.py --brain $brain

# 3. Fetch the selected items; run the speaker pass on interviews and panels
.\.venv\Scripts\python -I tools\library_yt.py --workspace $ws fetch example-publisher --selection $brain\selection.yaml
.\.venv\Scripts\python -I tools\diarize.py --workspace $ws example-publisher yt-abc123
#    a naming agent follows tools\speaker_naming.md, then:
.\.venv\Scripts\python -I tools\finalize_raw.py --workspace $ws example-publisher yt-abc123

# 4. Ingest waves: fill in briefs\topic-ingest-brief.md, dispatch batches, gate each one
.\.venv\Scripts\python -I tools\check_wiki.py --brain $brain

# 5. Merge: survey, resolve duplicate slugs in ingest\slug-map.yaml, bundle, then write pages and debates
.\.venv\Scripts\python -I tools\merge_topic.py --brain $brain survey
.\.venv\Scripts\python -I tools\merge_topic.py --brain $brain bundles
#    fill in briefs\topic-pages-brief.md and briefs\debates-brief.md; dispatch writers by page group

# 6. Audit rules, lint, index, evaluate, generate
.\.venv\Scripts\python -I tools\rule_status.py --brain $brain --write
.\.venv\Scripts\python -I tools\lint_wiki.py --brain $brain --fix-slug-map
.\.venv\Scripts\python -I tools\build_wiki_index.py --brain $brain
.\.venv\Scripts\python -I tools\verify_eval_quotes.py --brain $brain answers.md
.\.venv\Scripts\python -I tools\generate_persona.py --brain $brain --out $HOME\.claude\skills
```

The full step-by-step guides, with the model assignment for each step and the lessons learned at each stage, are in [docs/build-pipeline.md](docs/build-pipeline.md).

## Tools

**Map and crawl (persona brains)**

| Tool | Does |
|---|---|
| `kajabi_map.py`, `kajabi_lesson_assets.py`, `cdp_*.py` | map a Kajabi site; fetch lesson page text and attachments through the logged-in browser (CDP) |
| `skool_*.py` | map, crawl, verify and batch a Skool community through the logged-in browser (settings in `crawl.yaml`) |
| `wistia_to_raw.py`, `yt_to_raw.py`, `mux_captions.py` | video-host captions → timestamped transcript |
| `whisper_transcribe.py`, `whisper_lines.py` | local Whisper (faster-whisper) for videos without captions; `--anti-loop` against repetition loops |
| `build_raw.py`, `attachment_to_raw.py` | assemble one raw file per lesson (transcript + page text) and per PDF; `--verify` checks counts and words per minute |

**Library (topic brains)**

| Tool | Does |
|---|---|
| `library_yt.py` | catalogue YouTube channels and feeds; fetch captions or audio into raw or staging |
| `web_to_raw.py` | catalogue and capture blogs, docs and transcript pages (`--browser` for JS-built pages) |
| `book_to_raw.py` | a user-supplied book or paper PDF → one raw file, one block per page |
| `diarize.py`, `finalize_raw.py`, `speaker_naming.md` | speaker pass: cluster voices, name them (the naming agent's brief), write raw with speakers |
| `example_frames.py`, `check_examples.py`, `link_examples.py` | measure demonstration videos (cuts, frames); check that example pages cite only their own video; link examples from concept pages |
| `library_raw.py` | shared helpers: paths, slugs, catalogue read and write, raw writing |

**Triage, ingest and merge**

| Tool | Does |
|---|---|
| `triage_inputs.py`, `triage_merge.py`, `selection_override.py` | cut catalogues into triage inputs; merge scores into `selection.yaml`; hand overrides |
| `check_wiki.py` | gate: frontmatter, citations resolve, quotes verbatim at the cited block, speakers match, claims cited |
| `requote.py` | re-anchor quotes after a raw file is re-crawled |
| `merge_staging.py` (persona), `merge_topic.py` (topic) | pool ingest staging by concept → per-concept bundles |
| `rule_status.py` | recount topic-brain rule status by independent voice |
| `skool_ingest_batches.py` | cut a Skool brain into ingest batches (`--only-new` for refreshes) |

**Check, evaluate and generate**

| Tool | Does |
|---|---|
| `lint_wiki.py`, `build_wiki_index.py` | broken links, orphans, rule status, slug drift (`--fix-slug-map`); rebuild `index.md` |
| `verify_eval_quotes.py`, `rubric_agreement.py` | check quotes in eval answers; compare two graders' rubric scores |
| `generate_persona.py` | `brain.md` → skill (`SKILL.md` + agent metadata), persona or topic version |
| `refresh_due.py` | which brains, sources or tool pages are due for a refresh (per-brain on/off switch, per-source cadence) |
| `install_qmd.ps1` | install qmd and make it run under Bun on Windows |

Python extras for the optional tools (speaker pass, frames, web capture, PDF) are grouped in `requirements.txt`. `yt-dlp` is an external program.

## Windows notes

- Run Python with `-I` (isolated mode). The tools add their own folder to the import path.
- Never use the `python3` alias (it is a Store stub and hangs in agent shells), and don't pipe a script into a bare `python -`.
- qmd under Node crashes on Windows when it loads sqlite-vec; `tools\install_qmd.ps1` runs it under Bun.
- faster-whisper on CUDA needs the NVIDIA cuBLAS/cuDNN wheels; `whisper_transcribe.py` registers their DLL folders.
- More hard-won details are in the lessons-learned section of [docs/build-pipeline.md](docs/build-pipeline.md).

## License

MIT. See [LICENSE](LICENSE).

# Create a Brain

Turn an expert's own material (a course, a community or a video library) into a **brain**: a cited, LLM-maintained wiki plus a persona card that an AI agent can consult and that answers in the expert's frameworks and voice. Every claim traces back to a timestamped transcript, every quote is checked word for word, and anything the material doesn't support is labelled **Inference:**.

It is built on Andrej Karpathy's "LLM wiki" idea, extended with a crawl → transcribe → ingest → merge → persona → eval pipeline, verification tooling, and parallel delegation to cheaper models for the volume work.

> **Use it only on material you have the right to use.** Brains live in your own private workspace, never in this repo. Paid course content is typically licensed for personal use: don't publish brains built from it.

## How it works

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

Rules start as `bench` (one source) and become `active` once they're backed by independent sources. Quotes by anyone other than the expert carry the speaker's name.

## Layout

```
AGENTS.md / CLAUDE.md   rules for any agent working in a workspace
docs/                   architecture, build pipeline (with lessons learned), updates, library and triage
                        (shared sources for topic brains), councils, tech choices, references
template/               copy to start a brain: brain.md, sources.yaml, crawl.yaml, crawl-log.md, raw/, wiki/
briefs/                 ingest and page-writing briefs for parallel workers
tools/                  every tool takes --brain <folder> (refresh_due.py takes --root <workspace>)
tests/                  unit tests for the wiki tools; acceptance harness for the source adapters
```

Your **workspace** is a separate private folder (its own git repo, no remote):

```
my-brains/
  .secrets/             browser profiles, caches, scratch (never committed)
  my-course/            one brain: brain.md, sources.yaml, crawl.yaml, outline.yaml, raw/, wiki/, media/ (gitignored)
  another-brain/
```

## Quick start

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
.\.venv\Scripts\python -I tools\refresh_due.py --root ..\my-brains
```

The full step-by-step guide, with the model assignment for each step, is in [docs/build-pipeline.md](docs/build-pipeline.md).

## Tools

| Tool | Does |
|---|---|
| `kajabi_map.py`, `kajabi_lesson_assets.py`, `cdp_*.py` | map a Kajabi site; fetch lesson page text and attachments through the logged-in browser (CDP) |
| `wistia_to_raw.py` | Wistia captions → timestamped transcript |
| `whisper_transcribe.py`, `whisper_lines.py` | local Whisper (faster-whisper) for videos without captions; `--anti-loop` against repetition loops |
| `yt_to_raw.py` | YouTube captions → raw |
| `build_raw.py`, `attachment_to_raw.py` | assemble one raw file per lesson (transcript + page text) and per PDF; `--verify` checks counts and words per minute |
| `check_wiki.py` | gate: frontmatter, citations resolve, quotes verbatim at the cited block, claims cited |
| `requote.py` | re-anchor quotes after a raw file is re-crawled |
| `merge_staging.py` | pool ingest staging by concept → per-concept bundles |
| `lint_wiki.py`, `build_wiki_index.py` | broken links, orphans, rule status; rebuild `index.md` |
| `generate_persona.py` | `brain.md` → persona skill (`SKILL.md` + agent metadata) |
| `refresh_due.py` | which brains or sources are due for a refresh (per-brain on/off switch, per-source cadence) |
| `install_qmd.ps1` | install qmd and make it run under Bun on Windows |

## Windows notes

- Run Python with `-I` (isolated mode). The tools add their own folder to the import path.
- qmd under Node crashes on Windows when it loads sqlite-vec; `tools\install_qmd.ps1` runs it under Bun.
- faster-whisper on CUDA needs the NVIDIA cuBLAS/cuDNN wheels; `whisper_transcribe.py` registers their DLL folders.
- More hard-won details are in the lessons-learned section of [docs/build-pipeline.md](docs/build-pipeline.md).

## License

MIT. See [LICENSE](LICENSE).

# Agent & CLI Reference

This guide holds the end-to-end command sequences, full tool catalog, and platform/shell notes for AI agents and power users operating **Agent Knowledge Core**.

For agent rules and delegation policy, read [`AGENTS.md`](../AGENTS.md) first. For stage-by-stage walkthroughs and lessons learned, see [`docs/build-pipeline.md`](build-pipeline.md).

---

## Workspace setup notes (for agents)

When setting up a new private workspace:

- Ask the owner whether they want a backup and where (such as another drive or an encrypted archive). Keep the workspace off public remotes and record the choice in the workspace's own notes. Skipping the backup is fine.
- Keep `raw/` and `library/<publisher>/raw/` immutable. Fix capture issues by re-crawling.
- Initialize edit protection once per brain (`wiki_edits.py --brain <brain> record --init`), start every agent pass with `wiki_edits.py --brain <brain> begin`, and end it with `build_wiki_index.py`.

---

## Persona brain workflow

Create a private workspace and copy `template/`:

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

# 3. Initialize edit protection once, then begin each ingest or merge pass before dispatching workers (briefs/)
python -X utf8 -I tools/wiki_edits.py --brain ../my-brains/my-course record --init
python -X utf8 -I tools/wiki_edits.py --brain ../my-brains/my-course begin
python -X utf8 -I tools/check_wiki.py --brain ../my-brains/my-course
# Update wiki/hot.md and wiki/log.md before closing the ingest pass.
python -X utf8 -I tools/build_wiki_index.py --brain ../my-brains/my-course
python -X utf8 -I tools/wiki_edits.py --brain ../my-brains/my-course begin
python -X utf8 -I tools/merge_staging.py --brain ../my-brains/my-course survey
python -X utf8 -I tools/lint_wiki.py --brain ../my-brains/my-course
# Update wiki/hot.md and wiki/log.md before closing the merge pass.
python -X utf8 -I tools/build_wiki_index.py --brain ../my-brains/my-course

# 4. Generate a draft skill, run evals with a fresh agent, fix gaps, then regenerate if brain.md changed
python -X utf8 -I tools/generate_persona.py --brain ../my-brains/my-course --out ~/.claude/skills

# 5. Refresh reminders across all brains
python -X utf8 -I tools/refresh_due.py --workspace ../my-brains
```

---

## Topic brain workflow

Copy `template-topic/` into your private workspace:

```powershell
# Windows (PowerShell)
Copy-Item -Recurse template-topic ..\my-brains\my-topic
```

```bash
# macOS / Linux (bash)
cp -r template-topic ../my-brains/my-topic
```

Fill in `my-topic/brain.md` (`experts`, `expert_aliases`, `hosts`, `evidence_types`, extraction areas, scope and boundaries) and create `../my-brains/library/<publisher>/sources.yaml` for each publisher ([`docs/library.md`](library.md)), then run with the venv active:

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

# 3. Initialize edit protection once, then begin the ingest pass before dispatching batches (briefs/topic-ingest-brief.md)
python -X utf8 -I tools/wiki_edits.py --brain ../my-brains/my-topic record --init
python -X utf8 -I tools/wiki_edits.py --brain ../my-brains/my-topic begin
python -X utf8 -I tools/check_wiki.py --brain ../my-brains/my-topic
# Update wiki/hot.md and wiki/log.md before closing the ingest pass.
python -X utf8 -I tools/build_wiki_index.py --brain ../my-brains/my-topic

# 4. Merge: survey, resolve duplicate slugs in ingest/slug-map.yaml, bundle, then write pages and debates
python -X utf8 -I tools/wiki_edits.py --brain ../my-brains/my-topic begin
python -X utf8 -I tools/merge_topic.py --brain ../my-brains/my-topic survey
python -X utf8 -I tools/merge_topic.py --brain ../my-brains/my-topic bundles
#    fill in briefs/topic-pages-brief.md and briefs/debates-brief.md; dispatch writers by page group

# 5. Audit rules, lint and index
python -X utf8 -I tools/rule_status.py --brain ../my-brains/my-topic --write
python -X utf8 -I tools/lint_wiki.py --brain ../my-brains/my-topic --fix-slug-map
# Update wiki/hot.md and wiki/log.md before closing the merge pass.
python -X utf8 -I tools/build_wiki_index.py --brain ../my-brains/my-topic

# 6. Generate a draft skill, run cold evals with a fresh agent, check quotes, fix gaps, then regenerate
python -X utf8 -I tools/generate_persona.py --brain ../my-brains/my-topic --out ~/.claude/skills
python -X utf8 -I tools/verify_eval_quotes.py --brain ../my-brains/my-topic answers.md
```

### Books and text-only sources

Skip the speaker pass for single-author books and articles (`speaker_method: single`). Capture PDFs with `book_to_raw.py` (which also updates `catalogue.tsv` and `crawl-log.md`) and web chapters with `web_to_raw.py fetch`:

```sh
python -X utf8 -I tools/book_to_raw.py --workspace ../my-brains example-author book.pdf --slug example-book --title "Example Book" --author "Example Author" --published 1920 --pages 1-12,40-55
python -X utf8 -I tools/web_to_raw.py --workspace ../my-brains fetch example-author --urls https://example.com/chapter-1 --from-heading "Chapter 1" --to-heading "Chapter 2"
```

See [`examples/README.md`](../examples/README.md) for a complete text-only topic brain.

---

## Tools catalog

### Map and crawl (persona brains)

| Tool | Does |
|---|---|
| `launch_chrome.py` | Launch a brain's dedicated Chrome/Chromium profile (`--brain <brain> [--chrome <exe>]`), reading `site`, `cdp_port` and `profile` from `crawl.yaml` and keeping profiles under `<workspace>/.secrets/` |
| `kajabi_map.py`, `kajabi_lesson_assets.py`, `cdp_*.py` | Map a Kajabi site; fetch lesson page text and attachments through the logged-in browser (CDP) |
| `skool_*.py` | Map, crawl, verify and batch a Skool community through the logged-in browser (settings in `crawl.yaml`) |
| `wistia_to_raw.py`, `yt_to_raw.py`, `mux_captions.py` | Video-host captions → timestamped transcript |
| `whisper_transcribe.py`, `whisper_lines.py` | Local Whisper (`faster-whisper`) for videos without captions; `--anti-loop` against repetition loops |
| `build_raw.py`, `attachment_to_raw.py` | Assemble one raw file per lesson (transcript + page text) and per PDF; `--verify` checks counts and words per minute |

### Library (topic brains)

| Tool | Does |
|---|---|
| `library_yt.py` | Catalogue YouTube channels and feeds; fetch captions or audio into raw or staging |
| `web_to_raw.py` | Catalogue and capture blogs, docs and transcript pages (`--browser` for JS-built pages; `--from-heading` / `--to-heading` select sections before capture on paragraph pages) |
| `book_to_raw.py` | User-supplied book or paper PDF → one raw file, one block per page (`--published` accepts `YYYY`, `YYYY-MM` or `YYYY-MM-DD`; `--pages 1-12,40-55` keeps original PDF page numbers); updates `catalogue.tsv` and appends to `crawl-log.md` |
| `diarize.py`, `finalize_raw.py`, `speaker_naming.md` | Speaker pass: cluster voices, name them (the naming agent's brief), write raw with speakers |
| `example_frames.py`, `check_examples.py`, `link_examples.py` | Measure demonstration videos (cuts, frames); check that example pages cite only their own video; link examples from concept pages |
| `library_raw.py` | Shared helpers: paths, slugs, catalogue read and write, raw writing |

### Triage, ingest and merge

| Tool | Does |
|---|---|
| `triage_inputs.py`, `triage_merge.py`, `selection_override.py` | Cut catalogues into triage inputs; merge scores into `selection.yaml`; hand overrides |
| `check_wiki.py` | Check `brain.md`, wiki pages and staging for corrupt text, invalid locators, misquotes, speaker attribution and uncited claims in key sections |
| `wave_report.py` | Check a finished wave (`--batches`, `--wave`). Run `check_wiki.py` on staging and pages, match explicit capture paths, and check protected pages |
| `requote.py` | Re-anchor quotes (timestamps, `¶N` paragraph and `p. N` page locators) after a raw file is re-crawled |
| `merge_staging.py` (persona), `merge_topic.py` (topic) | Pool ingest staging by concept → per-concept bundles |
| `rule_status.py` | Recount topic-brain rule status by independent voice |
| `skool_ingest_batches.py` | Cut a Skool brain into ingest batches (`--only-new` for refreshes) |

### Check, evaluate and generate

| Tool | Does |
|---|---|
| `lint_wiki.py`, `build_wiki_index.py` | Broken links, orphans, rule status, slug drift (`--fix-slug-map`), human edit and proposal warnings, errors for changed captures; rebuild `wiki/index.md` (concepts, plus `notes/` under **Your notes**) and `wiki/sources-index.md` (sources), and record the wiki baseline |
| `obsidian_setup.py` | Configure a brain folder in place as its own Obsidian vault (`.obsidian/` settings, `notes/`, topic-brain `library` link, `.gitignore`; `--workspace <ws> --all [--gitignore-hub] [--reset]` also writes `.cores-hub/`) |
| `wiki_edits.py` | Detect and protect human edits in `wiki/` (`record --init`, `begin`, `status`, `propose`, `proposals`, `accept`) so agent passes never overwrite them |
| `raw_guard.py` | Record capture hashes and fail on edited or missing captures. Workspace checks cover the library and each brain |
| `content_hashes.py` | Shared SHA-256 hash-manifest and file-lock helpers used by `wiki_edits.py` and `raw_guard.py` |
| `verify_eval_quotes.py`, `rubric_agreement.py` | Fail on reported eval quote problems, or compare two graders' rubric scores |
| `generate_persona.py` | `brain.md` → subject-neutral skill (`SKILL.md` + agent metadata), persona or topic version; reads optional `skill.guidance` and `skill.boundaries` from `brain.md`, prints `consider skill.guidance:` hints when none are set, links `wiki/examples/` when present (`--relative-to <dir>` writes portable relative paths; `--check` reports drift without writing) |
| `refresh_due.py` | Report which brains, sources or tool pages are due for a refresh (per-brain on/off switch, per-source cadence) |
| `token_report.py` | Measure token usage and input-equivalent cost across Claude Code transcripts, Codex sessions and optional T3 Code DB (`--workspace`, `--since`, `--ctx-warn`, `--json`) |
| `install_qmd.ps1` | Install qmd and run it under Bun on Windows (macOS/Linux: `npm install -g @tobilu/qmd`) |

`requirements.txt` installs `requirements-core.txt` by default; optional heavy groups (Whisper, torch/diarization, OpenCV/frames) are commented inside `requirements.txt`. External programs `yt-dlp` and `ffmpeg` must be on `PATH`.

---

## Platform & shell notes

- **Python flags:** Run tools with `-X utf8 -I` (UTF-8 I/O and isolated mode) on Windows, macOS and Linux. The tools add their own folder to the import path.
- **`python` vs `python3`:** Use `python3` only to create the venv on macOS and Linux. On Windows, never use the `python3` Microsoft Store alias (it hangs in agent shells), and never pipe a script into a bare `python -`.
- **Chrome:** Use `python -X utf8 -I tools/launch_chrome.py --brain <brain> [--chrome <executable>]` on every OS to open the brain's dedicated Chrome/Chromium profile with remote debugging.
- **qmd:** On Windows, Node crashes loading `sqlite-vec`, so run `tools/install_qmd.ps1` to run qmd under Bun. On macOS and Linux, install with `npm install -g @tobilu/qmd`; on macOS, run `brew install sqlite` first (per [tobi/qmd](https://github.com/tobi/qmd)).
- **Whisper:** Uses CUDA when available, otherwise CPU (no Apple GPU backend). On Windows, the NVIDIA cuBLAS/cuDNN wheels' DLL folders are registered automatically.
- **External tools:** `yt-dlp` and `ffmpeg` must be installed and on `PATH` for video/audio fetching and transcription.
- **CI:** The test suite runs automatically on Windows, macOS and Linux. More details are in the lessons-learned section of [`docs/build-pipeline.md`](build-pipeline.md).

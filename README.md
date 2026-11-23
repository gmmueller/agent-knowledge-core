<div align="center">

# Agent Knowledge Core

[![Tests](https://github.com/gmmueller/agent-knowledge-core/actions/workflows/tests.yml/badge.svg)](https://github.com/gmmueller/agent-knowledge-core/actions/workflows/tests.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**A central, cited knowledge core your AI agents consult — built from experts' own words.**

[How it works](#how-it-works) •
[One core, every project](#one-core-every-project) •
[Example](#example) •
[Getting started](#getting-started) •
[Obsidian](#view-and-edit-in-obsidian) •
[Agent & CLI reference](docs/agent-reference.md)

</div>

---

Turn experts' own material (courses, communities, video libraries, blogs, or books) into **brains**: cited, LLM-maintained wikis paired with a thin skill card that any AI agent can load.

All of your brains live in one private workspace backed by a shared source library, so every agent in every project consults the same knowledge instead of keeping stale copies. Every claim traces back to a timestamped transcript or page, every quote is verified word for word, and anything the source material doesn't directly support is labelled **Inference:**.

Built on Andrej Karpathy's "LLM wiki" idea, extended with a full capture → ingest → merge → verify → skill pipeline, edit protection for human notes, and parallel delegation to lower-cost models for bulk work.

## Two kinds of brain

<table>
  <tr>
    <th width="50%" align="left">Persona Brain</th>
    <th width="50%" align="left">Topic Brain</th>
  </tr>
  <tr>
    <td valign="top">
      <strong>One expert, one voice.</strong><br><br>
      Built from a single teacher's course, community, or channel with its own <code>raw/</code> folder. Answers using the expert's frameworks, terminology, and voice.
    </td>
    <td valign="top">
      <strong>Multiple experts, one subject.</strong><br><br>
      Draws from a shared <code>library/</code> of sources crawled once. No imitated voice: applies each expert's methods, attributes every quote by speaker, and maps where experts disagree in dedicated debate pages.
    </td>
  </tr>
</table>

Topic brains can also use current authoritative documents as their evidence. See [reference topic brains](docs/agent-reference.md#reference-topic-brains) and [local document capture](docs/documents.md).

## How it works

### Persona brain flow

<table>
  <tr>
    <td align="center" width="18%"><strong>1. Sources</strong><br><sub>Courses, videos,<br>communities, PDFs</sub></td>
    <td align="center"><strong>→</strong></td>
    <td align="center" width="18%"><strong>2. <code>raw/</code></strong><br><sub>Immutable transcripts,<br>page text &amp; PDFs</sub></td>
    <td align="center"><strong>→</strong></td>
    <td align="center" width="18%"><strong>3. <code>wiki/</code></strong><br><sub>Source pages, concepts,<br>rules &amp; glossary</sub></td>
    <td align="center"><strong>→</strong></td>
    <td align="center" width="18%"><strong>4. <code>brain.md</code></strong><br><sub>Scope, voice, quoted<br>rules &amp; task loop</sub></td>
    <td align="center"><strong>→</strong></td>
    <td align="center" width="18%"><strong>5. Skill</strong><br><sub>Thin loader for<br>any AI agent</sub></td>
  </tr>
</table>

<details>
<summary><strong>Step-by-step breakdown</strong></summary>

1. **Scope and map.** List every source in `sources.yaml`. For course platforms, map products → modules → lessons → video IDs into `outline.yaml` through a real Chrome window you log into (the agent never handles passwords).
2. **Crawl and transcribe.** Prefer the video host's own captions; fall back to local Whisper on your GPU. Lesson page text and attachments (PDFs, images) become text too. `raw/` is immutable: fix problems by re-crawling.
3. **Ingest in parallel.** Batch workers write one source page per lesson plus staging notes (`briefs/ingest-brief.md`). `check_wiki.py` catches corrupt text, invalid citations, unsupported claims, and misquotes.
4. **Merge.** Pool staging notes per concept (`merge_staging.py`), resolve duplicate slugs, and write shared concept pages (`briefs/pages-brief.md`): topics, principles, frameworks, methods, rules, and glossary.
5. **Persona & skill.** Write `brain.md` (scope, voice, worldview, quoted rules, framework map, task loop, boundaries), then generate a thin skill (`generate_persona.py`).
6. **Evaluate & refresh.** Run a fixed question set through a cold agent that has only the skill (`evals.md`), grade every answer, and keep the brain current with incremental refreshes (`refresh_due.py`) and local search via [qmd](https://github.com/tobi/qmd).

</details>

### Topic brain flow

<table>
  <tr>
    <th colspan="7" align="left">Phase 1 — Collect &amp; Select</th>
  </tr>
  <tr>
    <td align="center" width="22%"><strong>1. Library</strong><br><sub>Crawl each publisher<br>once into <code>library/</code></sub></td>
    <td align="center"><strong>→</strong></td>
    <td align="center" width="22%"><strong>2. Catalogue</strong><br><sub>Metadata index<br>for every item</sub></td>
    <td align="center"><strong>→</strong></td>
    <td align="center" width="22%"><strong>3. Triage</strong><br><sub>Score &amp; tier items<br>(A / B / C / X)</sub></td>
    <td align="center"><strong>→</strong></td>
    <td align="center" width="22%"><strong>4. Fetch &amp; Speakers</strong><br><sub>Capture raw files;<br>label voices</sub></td>
  </tr>
  <tr>
    <th colspan="7" align="left">Phase 2 — Synthesize &amp; Verify</th>
  </tr>
  <tr>
    <td align="center" width="22%"><strong>5. Ingest Waves</strong><br><sub>Source pages &amp;<br>staging notes</sub></td>
    <td align="center"><strong>→</strong></td>
    <td align="center" width="22%"><strong>6. Merge &amp; Debates</strong><br><sub>Concept pages &amp;<br>expert disagreements</sub></td>
    <td align="center"><strong>→</strong></td>
    <td align="center" width="22%"><strong>7. Eval &amp; Verify</strong><br><sub>Cold-agent traps &amp;<br>quote verification</sub></td>
    <td align="center"><strong>→</strong></td>
    <td align="center" width="22%"><strong>8. Skill</strong><br><sub>Thin loader pointing<br>at live wiki</sub></td>
  </tr>
</table>

<details>
<summary><strong>Step-by-step breakdown</strong></summary>

1. **Library.** Each publisher (channel, blog, podcast, author, or vendor) is crawled once into `library/<publisher>/raw/`. `library/people.yaml` tracks who speaks where.
2. **Catalogue and triage.** List every item, score each against the brain's extraction areas, and merge scores into `selection.yaml`: tier **A** (deep ingest), **B** (raw and search only), **C** (skip), **X** (annotate as an example).
3. **Fetch and speaker pass.** Fetch selected items. For interviews and panels, diarization clusters the voices, a naming agent labels them, and `finalize_raw.py` writes the speaker-attributed raw file. (Single-author books and articles skip diarization.)
4. **Ingest waves.** Batch workers write source pages and staging (`briefs/topic-ingest-brief.md`). Every quote names its speaker, and `check_wiki.py` verifies the speaker against the cited block.
5. **Merge and debates.** `merge_topic.py` pools staging into per-concept bundles. Workers write concept pages (`briefs/topic-pages-brief.md`) and debate pages (`briefs/debates-brief.md`). `rule_status.py` recounts rule status by independent voice.
6. **Generate, evaluate, and refine.** Generate a draft skill (`generate_persona.py`), test a cold agent against `evals.md` (including trap questions), verify its quotes with `verify_eval_quotes.py`, and fix any gaps. Use `generate_persona.py --check` to detect drift.

</details>

> **How rules earn status:** Rules start as `bench` and become `active` once backed by two or more independent sources. Topic brains add `consensus` (at least two listed experts support the rule with none opposing) and `contested` (a source argues against it, linked to a debate page).

## One core, every project

Your private workspace is the single source of truth. Build each brain once, and every agent across every repo on your machine consults the same live, cited pages.

<table>
  <tr>
    <td align="center" width="28%"><strong>Private Workspace</strong><br><sub><code>library/</code> + persona &amp; topic brains<br>maintained in one place</sub></td>
    <td align="center"><strong>→</strong></td>
    <td align="center" width="32%"><strong>Thin Skills &amp; Search</strong><br><sub><code>SKILL.md</code> in <code>~/.claude/skills/</code><br>(and Codex) + local <a href="https://github.com/tobi/qmd">qmd</a> MCP</sub></td>
    <td align="center"><strong>→</strong></td>
    <td align="center" width="28%"><strong>Every Project</strong><br><sub>Any agent reads live <code>brain.md</code><br>and <code>wiki/</code> at use time</sub></td>
  </tr>
</table>

- **Thin skills, live brains.** `generate_persona.py` writes a small `SKILL.md` (plus `agents/openai.yaml` for Codex) that points at your brain's `brain.md`, `wiki/`, and sources — holding no stale copy of the knowledge itself. (Pass `--relative-to <dir>` for a portable sample skill.)
- **Subject-neutral core, per-brain rules.** Each brain defines its own `skill.guidance` and `skill.boundaries` in `brain.md`. Refreshing a brain updates what every project sees on the next run.
- **Cross-brain search.** Index `raw/`, `wiki/`, and `library/` with [qmd](https://github.com/tobi/qmd) so any agent can search all brains from one local MCP server.

## Example

A complete topic brain built from three public-domain books (Strunk, Quiller-Couch, and H. W. & F. G. Fowler) lives in [`examples/`](examples/README.md). It was built from the framework docs alone.

- [`examples/README.md`](examples/README.md) — overview and verification commands
- [`examples/workspace/plain-writing/brain.md`](examples/workspace/plain-writing/brain.md) — the topic brain card
- [`examples/workspace/plain-writing/wiki/index.md`](examples/workspace/plain-writing/wiki/index.md) — compiled wiki (16 source pages in [`sources-index.md`](examples/workspace/plain-writing/wiki/sources-index.md), 22 concept pages, 1 rubric, 2 debate pages)
- [`examples/skills/plain-writing/SKILL.md`](examples/skills/plain-writing/SKILL.md) — generated portable skill

## Getting started

### 1. Install dependencies

Requires **Python 3.11+** (plus `yt-dlp` and `ffmpeg` on `PATH` if capturing video/audio). Create and activate a virtual environment from the repo root:

| Step | Windows (PowerShell) | macOS / Linux (bash) |
|---|---|---|
| Create venv | `python -m venv .venv` | `python3 -m venv .venv` |
| Activate venv | `.\.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` |
| Without activation | `.\.venv\Scripts\python.exe` | `.venv/bin/python` |

Install the core dependencies and Playwright Chromium:

```sh
python -m pip install -r requirements.txt
python -m playwright install chromium
```

> Heavy optional extras (local Whisper, PyTorch/diarization, OpenCV) are listed as commented groups in [`requirements.txt`](requirements.txt).

### 2. Create a private workspace

Keep your brains in a separate private folder outside this repo (its own git repo, no public remote):

```powershell
# Windows (PowerShell) — start a persona or topic brain
mkdir ..\my-brains
Copy-Item -Recurse template ..\my-brains\my-course       # persona brain
Copy-Item -Recurse template-topic ..\my-brains\my-topic  # topic brain
```

```bash
# macOS / Linux (bash) — start a persona or topic brain
mkdir -p ../my-brains
cp -r template ../my-brains/my-course         # persona brain
cp -r template-topic ../my-brains/my-topic    # topic brain
```

### 3. Build a brain (with your AI agent or CLI)

Fill in `brain.md` (and `sources.yaml` / `crawl.yaml` for persona brains, or `library/<publisher>/sources.yaml` for topic brains), then point your AI coding agent (Claude Code, Codex, etc.) at this repo and your new brain folder. Agents automatically read [`AGENTS.md`](AGENTS.md) / [`CLAUDE.md`](CLAUDE.md) and follow the pipeline.

For the full end-to-end CLI commands, tools catalog, and platform/shell notes, see **[`docs/agent-reference.md`](docs/agent-reference.md)**.

## Layout

<table>
  <tr>
    <th width="50%" align="left">This repo (public framework)</th>
    <th width="50%" align="left">Your workspace (private, local)</th>
  </tr>
  <tr>
    <td valign="top">

```text
AGENTS.md / CLAUDE.md  agent rules & conventions
docs/                  architecture, pipelines,
                       CLI & agent reference
template/              persona brain starter
template-topic/        topic brain starter
briefs/                parallel worker briefs
tools/                 Python CLI tools
tests/                 unit & adapter tests
examples/              public-domain topic brain
```

</td>
    <td valign="top">

```text
my-brains/
  .secrets/            browser profiles & caches
                       (never committed)
  library/             shared topic sources
                       (people.yaml, publishers)
  my-course/           persona brain
                       (brain.md, raw/, wiki/,
                        notes/, media/)
  my-topic/            topic brain
                       (brain.md, selection.yaml,
                        wiki/, notes/)
```

</td>
  </tr>
</table>

## View and edit in Obsidian

Each brain opens in place as its own Obsidian vault (open the **brain folder itself**, never `<brain>/wiki/` and never merged with unrelated brains).

```sh
# One brain
python -X utf8 -I tools/obsidian_setup.py --brain ../my-brains/my-course

# Every brain in a workspace (also writes ../my-brains/.cores-hub/ with quick-open links)
python -X utf8 -I tools/obsidian_setup.py --workspace ../my-brains --all --gitignore-hub
```

Then open the brain folder in Obsidian via **Open folder as vault**. Setup hides working folders from search/graph, color-codes the graph by page type, creates `notes/`, and links `library/` for topic brains so citations open the real source file.

<table>
  <tr>
    <th align="left">Folder</th>
    <th align="left">Owner</th>
    <th align="left">Editing rule</th>
  </tr>
  <tr>
    <td><code>wiki/</code></td>
    <td>Shared (LLM + you)</td>
    <td>Edit freely between agent passes. <code>wiki_edits.py</code> detects your edits and protects them — agents save updates as proposals under <code>ingest/proposals/</code> instead of overwriting.</td>
  </tr>
  <tr>
    <td><code>notes/</code></td>
    <td>Yours</td>
    <td>Add, edit, or delete anything and link to wiki pages. Agents never touch <code>notes/</code> and never cite them as sources.</td>
  </tr>
  <tr>
    <td><code>raw/</code> &amp; <code>library/</code></td>
    <td>Immutable</td>
    <td>Never edit by hand. Capture hashes verify integrity (<code>raw_guard.py</code>); fix source issues by re-crawling.</td>
  </tr>
</table>

## Use it responsibly

- **Use it only on material you have the right to use.** That means your own content, openly licensed or public-domain material, or courses and communities you have paid for and may use personally.
- **Course and community crawlers are personal-use tools.** They drive *your own* logged-in browser session, see only what your account can see, and never handle your password. Read the platform's terms before crawling, keep request rates low, and don't bypass paywalls or access controls.
- **Keep brains private.** Your brains live in your own private workspace, never in this repo. Paid course content is typically licensed for personal use only: don't publish, share, or sell brains built from it.
- **Public-domain exception.** [`examples/`](examples/) is the one brain stored in this repo. It uses only verified public-domain books, with exact edition details and retrieval URLs recorded in each publisher's `sources.yaml`, raw frontmatter, and crawl log.

## Documentation

| Doc | What's inside |
|---|---|
| [`docs/agent-reference.md`](docs/agent-reference.md) | Full persona & topic CLI workflows, complete tools catalog, and platform/shell notes |
| [`AGENTS.md`](AGENTS.md) | Core rules, page conventions, and delegation policy for AI agents |
| [`docs/build-pipeline.md`](docs/build-pipeline.md) | Stage-by-stage build guide with model assignments and lessons learned |
| [`docs/architecture.md`](docs/architecture.md) | System design, ownership, and edit-guard mechanics |
| [`docs/library.md`](docs/library.md) & [`docs/triage.md`](docs/triage.md) | Shared source library and topic-brain triage workflow |
| [`docs/updates.md`](docs/updates.md) | Incremental refreshes and update cadences |
| [`docs/token-budget.md`](docs/token-budget.md) | Keeping orchestrator and worker token costs low across phases |
| [`docs/council.md`](docs/council.md) | Multi-brain / council usage patterns |

## License

MIT. See [LICENSE](LICENSE).

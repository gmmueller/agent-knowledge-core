# Agent Knowledge Core: agent instructions

This is Agent Knowledge Core, a public framework for "brains": cited LLM wikis compiled from experts' own material. Actual brains live in a separate private workspace; `examples/` is the one place a brain lives in this repo, using verified public-domain material only. There are two kinds. **Persona brains** are one voice with their own `raw/`. **Topic brains** (`kind: topic`) combine several experts and draw on a shared `library/`: read `docs/library.md` before using library citations and `docs/triage.md` before selecting their inputs. Apply the per-brain rules below when working there. Read `docs/architecture.md` before structural work, `docs/build-pipeline.md` when building a brain, `docs/agent-reference.md` for full CLI command sequences, tools catalog and platform notes, and `docs/updates.md` when refreshing one.

## Tool conventions

- Tools that work on one brain take `--brain <brain-folder>`. Tools that touch the library, or scan all brains, take `--workspace <workspace-folder>`. `refresh_due.py` takes `--workspace` (`--root` is an alias). `rubric_agreement.py` takes two score files.
- A topic-brain tool finds the library at `<workspace>/library`, where `<workspace>` is the folder that holds the brain.
- Platform settings belong in `<brain>/crawl.yaml` (see `template/crawl.yaml`), not in framework code. Brain-specific values (expert aliases, hosts, evidence types, community URLs, ports, product lists) come from `brain.md`, `crawl.yaml`, `sources.yaml` or CLI flags. Library-specific values come from files under `library/`.
- Caches, profiles and scratch belong in `<workspace>/.secrets/`; media belongs in `<brain>/media/` or `library/<publisher>/media/`. Use `tools/brainlib.py` helpers in Python tools.
- Keep personal identifiers, licensed source text, cookies, tokens and browser profiles out of this public framework. Use generic placeholders in examples.
- Use forward slashes in tool commands (they work in PowerShell on Windows and bash on macOS/Linux). Activate the venv first (`.\.venv\Scripts\Activate.ps1` on Windows; `source .venv/bin/activate` on macOS/Linux), or call the venv interpreter directly (`.\.venv\Scripts\python.exe` / `.venv/bin/python`). Run tools as `python -X utf8 -I <framework>/tools/<tool>.py …`. Use `python3` only to create the venv on macOS/Linux; never use the `python3` alias on Windows (it hangs in agent shells), and never pipe a script into a bare `python -` (write a script file or use `-c`). Python reads and writes text with `encoding="utf-8"`.

## Core rules

1. **`raw/` is immutable**, in brains and in `library/<publisher>/raw/` alike. Write to it only while crawling. Never edit or "clean up" a raw file afterwards. Capture tools hash every raw file. `raw_guard.py check` and `lint_wiki.py` fail if they find a changed or missing capture. Fix problems by re-crawling.
2. **`wiki/` is LLM-maintained, with human edits protected.** Edit wiki pages by hand only between agent passes. `wiki_edits.py status` shows whether a pass is open. Start every agent pass (ingest, merge, page writing, refresh) with `python -X utf8 -I <framework>/tools/wiki_edits.py --brain <brain> begin`. Give each worker a draft folder outside `wiki/` and [publish every draft with `wiki_edits.py write`](docs/agent-reference.md#registering-wiki-writes). For protected pages, use `wiki_edits.py --brain <brain> propose <page> --from <file> --why "..."` and ask the user. End the pass with `build_wiki_index.py`.
3. **`notes/` is human-owned.** Never create, edit or delete anything in `<brain>/notes/`. Notes may link to wiki pages; wiki pages never cite `notes/` as sources.
4. **Every claim traces to a source.** Wiki pages cite raw files as `[[raw/<path>]]` with a timestamp or page where one exists, e.g. `(raw/m03-l02.md @ 12:41)`; topic brains cite `[[library/<publisher>/raw/<path>]]` and name the speaker on every quote. Anything not directly supported is marked **Inference:**.
5. **Rules need quotes.** Each rule in `brain.md` or `wiki/rules/` carries at least one exact quote and its source. Run `check_wiki.py` on both. Keep wikilinks inside the vault. Persona rules become `active` at two independent sources. For topic rule statuses, stance and independence, follow [Rule status and independence](docs/build-pipeline.md#rule-status-and-independence).
6. **Primary sources only.** Use the expert's own words. No third-party summaries unless `sources.yaml` marks them as such.
7. **Log everything.** Crawls go in `<brain>/crawl-log.md` (library crawls in `library/<publisher>/crawl-log.md`). Ingests, queries filed back, and lint passes go in `wiki/log.md` with the prefix `## [YYYY-MM-DD] <op> | <title>`.
8. **Privacy.** Never publish the private workspace; only generic framework code and the verified public-domain example in `examples/` (with edition and URL provenance recorded) belong in the public repo. Never commit cookies, tokens or browser profiles; they go in `.secrets/`. Never paste course text into external services other than the model APIs doing the work.

## Wiki operations (per brain)

- **Ingest / merge / refresh pass**: start with `wiki_edits.py --brain <brain> begin` and pass its protected list to workers. Read the source → write `wiki/sources/<slug>.md` (summary, key claims with timestamps, quotes, links to concepts) → update every untouched topic, principle, method, framework and rule page it touches → run `check_wiki.py` → update `hot.md` (last ~20 changes) and `log.md` → run `build_wiki_index.py` to rebuild both indexes and close the pass. File proposals for protected pages. Review open proposals and unrecorded changes with the user before reporting done. Mention contradictions with existing pages. Never write in `notes/`.
- **Query**: read `brain.md` and the concept index `wiki/index.md`. Use qmd (persona brains: `<brain>-wiki` and `<brain>-raw`; topic brains: the wiki and the `library` collection) or grep to find relevant pages, and open `wiki/sources-index.md` only to locate a specific source. Answer with citations. File valuable answers back as pages.
- **Lint**: look for broken links, orphan pages, duplicate concepts, stale or contradicted claims, rules missing quotes, bench rules that now have a second source, human-edited pages, open proposals, and raw files changed after capture.

## Page conventions

- Filenames: kebab-case. Links: Obsidian `[[wikilinks]]`.
- Frontmatter on every wiki page:
  ```yaml
  type: source | topic | principle | method | framework | rule | glossary   # topic brains also: example | rubric | tool | debate
  sources: [raw/...]        # raw files this page draws on (topic brains: library/<publisher>/raw/...)
  updated: YYYY-MM-DD
  status: active | bench    # rules only; topic brains also consensus | contested
  evidence: ...             # topic brains: one of brain.md's evidence_types
  freshness: evergreen | platform | tool-version | dated   # topic brains, for anything that changes
  ```
- Source pages for course lessons: `module`, `lesson`, `duration`, `url` in frontmatter. Source pages in topic brains: `publisher`, `item`, `url`, `title`, `published`, `speakers`.
- `type: tool` pages carry `reviewed` and `recheck_by` dates; `refresh_due.py` flags them when the date passes.

## Topic-brain pipeline

library → catalogue → triage → fetch → speaker pass → ingest waves → merge → debates → evals → skill. Details and lessons by stage: `docs/build-pipeline.md`.

| Stage | Tools | Brief |
|---|---|---|
| Library crawl and catalogue | `library_yt.py`, `web_to_raw.py`, `book_to_raw.py` (`--workspace`) | |
| Triage | `triage_inputs.py`, `triage_merge.py`, `selection_override.py` (`--brain`) | `docs/triage.md` |
| Fetch | `library_yt.py fetch`, `web_to_raw.py fetch`, `book_to_raw.py` | |
| Speaker pass | `diarize.py`, `finalize_raw.py` (`--workspace`) | `tools/speaker_naming.md` |
| Examples | `example_frames.py` (`--workspace`), `check_examples.py`, `link_examples.py` (`--brain`) | |
| Ingest waves | `check_wiki.py` as the gate | `briefs/topic-ingest-brief.md` |
| Merge | `merge_topic.py survey` then `bundles`, `lint_wiki.py --fix-slug-map` | `briefs/topic-pages-brief.md` |
| Debates | `check_wiki.py` | `briefs/debates-brief.md` |
| Rule audit | `rule_status.py --write`, `check_wiki.py`, `lint_wiki.py`, `build_wiki_index.py` | |
| Rubrics | `rubric_agreement.py` | |
| Evals | `verify_eval_quotes.py` | `template-topic/evals.md` |
| Skill | `generate_persona.py` (`--relative-to` for portable samples), qmd (`install_qmd.ps1` on Windows; `npm install -g @tobilu/qmd` on macOS/Linux) | |

Persona brains use `merge_staging.py` and the briefs `briefs/ingest-brief.md` and `briefs/pages-brief.md`. Skool communities use the `skool_*.py` tools; platform settings go in `crawl.yaml` with `platform: skool`.

## Delegation

Use a delegation tool for independent volume work. Keep planning, rule extraction, persona editing and final review in the main thread.

| Work | Role |
|---|---|
| Scope, rule extraction, persona card, brief fill-in, rule audit, final review | Orchestrator |
| Browser crawling, outline mapping, downloads, per-lesson extraction, bulk ingest, concept and debate pages, independent cross-checks | Volume workers |
| Triage scoring, speaker naming | Low-cost volume workers, spot-checked by the orchestrator |
| Renaming, index rebuilds, format fixes and count checks | Mechanical worker or script |

Run independent modules, sources or page groups in parallel. Each worker gets a complete brief with input paths, allowed outputs and acceptance checks (fill in every `{{placeholder}}` of the brief first). Spot-check returned work before marking it done. Batch ingest workers write source pages and staging only; concept writers write only assigned concepts (see `briefs/`). The orchestrator merges, updates indexes and logs, and judges source independence. If a worker has written nothing after about 20 minutes, check whether it stalled, cancel it and rerun it elsewhere.

## Browser sessions

Each login-based brain has its own Chrome profile under `<workspace>/.secrets/` and distinct debugging port set in `crawl.yaml`. Launch it on any OS with `python -X utf8 -I <framework>/tools/launch_chrome.py --brain <brain> [--chrome <executable>]` (it reads `site`, `cdp_port` and `profile` from `crawl.yaml`, defaulting `profile` to `chrome-<brain>`). Record assignments in the private workspace's agent instructions.

Within one session, run only one browser-driving worker at a time. Use only the assigned brain's browser window and profile. The user handles login and 2FA.

## Updates

Brains are refreshed over time. See `docs/updates.md`. Every crawler must be able to run **incrementally**, picking up only new or changed items since the cursor in `sources.yaml`.

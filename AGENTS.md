# Brains: agent instructions

This is a public framework for persona "brains": cited LLM wikis compiled from an expert's own material. Actual brains live in a separate private workspace. Topic brains draw on a shared library: read `docs/library.md` before using library citations and `docs/triage.md` before selecting their inputs. Apply the per-brain rules below when working there. Read `docs/architecture.md` before structural work, `docs/build-pipeline.md` when building a brain and `docs/updates.md` when refreshing one.

## Tool conventions

- Every single-brain tool takes `--brain <brain-folder>`; `refresh_due.py` takes `--root <workspace>` because it scans all brains.
- Platform settings belong in `<brain>/crawl.yaml` (see `template/crawl.yaml`), not in framework code.
- Caches, profiles and scratch belong in `<workspace>/.secrets/`; media belongs in `<brain>/media/`. Use `tools/brainlib.py` helpers in Python tools.
- Keep personal identifiers, licensed source text, cookies, tokens and browser profiles out of this public framework. Use generic placeholders in examples.
- In PowerShell, use native paths and commands. Python reads and writes text with `encoding="utf-8"`.

## Core rules

1. **`raw/` is immutable**, in brains and in `library/<publisher>/raw/` alike. Write to it only while crawling. Never edit or "clean up" a raw file afterwards. Fix problems by re-crawling.
2. **`wiki/` is LLM-owned.** You write and maintain it. The user reads it.
3. **Every claim traces to a source.** Wiki pages cite raw files as `[[raw/<path>]]` with a timestamp or page where one exists, e.g. `(raw/m03-l02.md @ 12:41)`; topic brains cite `[[library/<publisher>/raw/<path>]]` and name the speaker on every quote. Anything not directly supported is marked **Inference:**.
4. **Rules need quotes.** Each rule in `brain.md` or `wiki/rules/` carries at least one exact quote and its source. A rule with one source has status `bench`. It becomes `active` at two or more independent sources.
5. **Primary sources only.** Use the expert's own words. No third-party summaries unless `sources.yaml` marks them as such.
6. **Log everything.** Crawls go in `<brain>/crawl-log.md`. Ingests, queries filed back, and lint passes go in `wiki/log.md` with the prefix `## [YYYY-MM-DD] <op> | <title>`.
7. **Privacy.** Never publish the private workspace; only generic framework code belongs in the public repo. Never commit cookies, tokens or browser profiles; they go in `.secrets/`. Never paste course text into external services other than the model APIs doing the work.

## Wiki operations (per brain)

- **Ingest** (one source): read it → write `wiki/sources/<slug>.md` (summary, key claims with timestamps, quotes, links to concepts) → update every topic, principle, method, framework and rule page it touches → update `index.md`, `hot.md` (last ~20 changes) and `log.md`. Mention contradictions with existing pages; don't silently overwrite them.
- **Query**: read `wiki/index.md` first, then the relevant pages, and use `qmd` search over `raw/` + `wiki/` when the index isn't enough. Answer with citations. File valuable answers back as pages.
- **Lint**: look for broken links, orphan pages, duplicate concepts, stale or contradicted claims, rules missing quotes, and bench rules that now have a second source.

## Page conventions

- Filenames: kebab-case. Links: Obsidian `[[wikilinks]]`.
- Frontmatter on every wiki page:
  ```yaml
  type: source | topic | principle | method | framework | rule | glossary
  sources: [raw/...]        # raw files this page draws on
  updated: YYYY-MM-DD
  status: active | bench    # rules only
  ```
- Source pages for course lessons: `module`, `lesson`, `duration`, `url` in frontmatter.

## Delegation

Use a delegation tool for independent volume work. Keep planning, rule extraction, persona editing and final review in the main thread.

| Work | Role |
|---|---|
| Scope, rule extraction, persona card, final review | Orchestrator |
| Browser crawling, outline mapping, downloads, per-lesson extraction, bulk ingest and independent cross-checks | Volume workers |
| Renaming, index rebuilds, format fixes and count checks | Mechanical worker or script |

Run independent modules or sources in parallel. Each worker gets a complete brief with input paths, allowed outputs and acceptance checks. Spot-check returned work before marking it done. Batch ingest workers write source pages and staging only; concept writers write only assigned concepts (see `briefs/`). The orchestrator merges, updates indexes and logs, and judges source independence.

## Browser sessions

Each login-based brain has its own Chrome profile under `<workspace>/.secrets/` and distinct debugging port set in `crawl.yaml`. For example, use `.secrets/chrome-my-course` with port `9222`, and a different profile and port for the next brain. Record assignments in the private workspace's agent instructions.

Within one session, run only one browser-driving worker at a time. Use only the assigned brain's browser window and profile. The user handles login and 2FA.

## Updates

Brains are refreshed over time. See `docs/updates.md`. Every crawler must be able to run **incrementally**, picking up only new or changed items since the cursor in `sources.yaml`.

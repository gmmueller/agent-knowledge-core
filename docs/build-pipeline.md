# Build pipeline (per brain)

| # | Step | Output | Who |
|---|---|---|---|
| 1 | **Scope.** Who or what, what's in and out, list every source and how to access it | `brain.md` (scope section), `sources.yaml` | orchestrator with user |
| 2 | **Map.** For courses, walk the course outline: modules, lessons, URLs, video host and IDs, attachments | `sources.yaml` filled, `crawl-log.md` | Volume worker (one browser driver per session) |
| 3 | **Crawl.** Download captions or transcripts, lesson text and attachments; parallelize where the session allows it | `raw/<module>/<lesson>.md`, `media/` | Volume workers |
| 4 | **Transcribe.** For videos without captions, transcribe locally with faster-whisper and keep timestamps | `raw/...md` | script run by a subagent |
| 5 | **Verify crawl.** Compare counts against the outline, check for empty or short transcripts, retry failures | `crawl-log.md` | Mechanical worker / script |
| 6 | **Ingest.** Apply the LLM Wiki pattern, one module per task in parallel, then a merge pass | `wiki/` | Volume workers; orchestrator merges |
| 7 | **Extract rules.** Principles, frameworks and rules with quotes; bench vs active | `brain.md`, `wiki/rules/` | orchestrator |
| 8 | **Generate.** Skill from `brain.md` into the explicit output directory (`--out` or `CREATE_A_BRAIN_SKILLS_DIR`) | agent files | orchestrator |
| 9 | **Evaluate.** 5–10 questions with known answers; check citations, drift and inference labels | `evals.md` | orchestrator + user |
| 10 | **Search.** Index `raw/` + `wiki/` with qmd once the brain is past ~100 sources | qmd collection | script |

## Raw file format (transcripts)

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

Paragraph roughly every 30 seconds, with timestamps kept so citations can deep-link.

## Membership sites (logged-in content)

- Use a **real Chrome window the user logs into**: a dedicated per-brain profile and port (assignments in the private workspace AGENTS.md and port in `crawl.yaml`), opened with `--user-data-dir` and `--remote-debugging-port`, and have agents attach over CDP (Playwright `connect_over_cdp`). This gets past Cloudflare and avoids automation fingerprints. The user does the login and any 2FA; agents never handle the password.
- Prefer the platform's own JSON/API calls made from inside the logged-in page over HTML scraping.
- Video hosts behind course platforms (Wistia, Vimeo, Kajabi's player) often expose captions or a media ID that yt-dlp can fetch. Try captions first, then audio download plus whisper.
- Crawl politely: sequential requests with small delays, no hammering.

## Lessons learned (course build, 2026-10-11)

- **Kajabi:** read lesson HTML with in-page `fetch()` + DOMParser (fast, same result as navigating). Attachments 302 to signed S3 URLs that in-page fetch can't follow (CORS): use the context's `ctx.request.get(url, max_redirects=0)` with the browser's User-Agent, then fetch the `location`. Kajabi gives each lesson its own download id for the same file, so dedupe by sha256.
- **Wistia:** `fast.wistia.com/embed/{medias,captions}/<id>.json` are public; captions there are good enough to skip Whisper.
- **Whisper (faster-whisper on Windows):** add the `nvidia/*/bin` wheel dirs with `os.add_dll_directory`, and load 16 kHz WAV with numpy (the bundled PyAV decoder breaks). Always scan output for repeated phrases (`(.{8,80}?)\1{2,}`), not just repeated segments; fix loops with `tools/whisper_transcribe.py --anti-loop` (keeps punctuation). `--no-prev-text` removes loops but loses punctuation.
- **Ingest at scale:** parallel batch workers write source pages + staging only; a merge pass builds shared pages from per-concept bundles. Give workers a gold example page, a seed slug vocabulary and `tools/check_wiki.py` as the acceptance gate (it verifies every quote verbatim at its cited block).
- **Quotes:** exact-match checks miss context flips ("X is dangerous" when the speaker is quoting others); read rule quotes in context. Label every non-primary speaker on the quote line (`— Other Speaker ([[raw/...]] @ t)`); mixed-presenter Q&As need a speaker pass against the raw text.
- **Rule status:** count independent sources as distinct modules/courses (or 3+ lessons), not lessons; a lesson and its case-study follow-up are one source.
- **Re-crawls:** after re-crawling a raw file, re-anchor wiki quotes with `tools/requote.py --brain <path>` (review similarity matches before `--apply`; then check exact quotes) instead of re-ingesting.
- **qmd on Windows:** under Node, qmd crashes (access violation) when loading sqlite-vec, so run it under Bun. `tools/install_qmd.ps1` installs it and rewrites the npm shims; re-run it after every qmd upgrade. Index each brain as two collections, `<brain>-wiki` and `<brain>-raw`, each with a `qmd context`. Register the MCP server in your agent tooling as `bun <npm>\node_modules\@tobilu\qmd\dist\cli\qmd.js mcp`.

## Tool entry points

Run Python tools with `python -I <framework>/tools/<tool>.py --brain <workspace>/my-course`. Isolated mode is supported; tools add their own sibling helper directory to the import path.

- Map and inspect: `cdp_status.py`, `cdp_probe.py`, `cdp_lesson_probe.py`, `kajabi_map.py`.
- Capture and transcribe: `kajabi_lesson_assets.py`, `wistia_to_raw.py`, `whisper_transcribe.py`, `build_raw.py`, `attachment_to_raw.py`, `yt_to_raw.py`, `whisper_lines.py`, `mux_captions.py`.
- Ingest: fill `briefs/ingest-brief.md`, dispatch isolated batches, run `check_wiki.py` on their source pages and staging.
- Merge: use `merge_staging.py --brain <path> survey`, resolve duplicate slugs in `ingest/slug-map.yaml`, then `merge_staging.py --brain <path> bundles`. Fill `briefs/pages-brief.md` for concept writers.
- Check: `check_wiki.py`, `lint_wiki.py`, `build_wiki_index.py`; update `wiki/hot.md` and `wiki/log.md` after accepting the changes.
- Generate: `generate_persona.py --brain <path> --out <skills-directory>`.
- Remind: `refresh_due.py --root <workspace> --all`.

Product headings in the index use registry titles in `sources.yaml` order, with `outline.yaml` titles as fallback. Associate a source with its product using `product:` or `code:`, `crawl.yaml`'s `source_id`, a matching outline product URL, or legacy `(product code main)` notes. Unregistered product codes are still listed.

## Port checks

Run `python -I tests/test_wiki_tools.py --scratch <workspace>/.secrets/scratch` for the targeted offline checks. On Windows, subprocess output uses the system encoding even under `-I`; the checks decode with that encoding rather than assuming UTF-8. Scratch fixtures are deleted automatically.

## Rule independence

`merge_staging.py` retains the original provisional rule status calculation: one distinct lesson is `bench`, two or more are `active`. The orchestrator must review independence before accepting a promotion. A lesson and its case-study follow-up count as one source; independent modules or courses provide stronger evidence (or three or more independently supporting lessons).

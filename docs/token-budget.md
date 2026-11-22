# Token budget

A brain build runs from one orchestrator thread that dispatches parallel workers for ingest batches and concept pages. Every orchestrator turn re-reads the entire conversation, so keeping the orchestrator thread short matters more than trimming worker prompts.

## Why

Measurements from real builds show where tokens go:

- In one persona brain build, the orchestrator context reached 818K tokens and averaged 357K per turn. The orchestrator accounted for most of the total cost.
- 58% of that orchestrator's cost came from turns triggered by worker-completion notifications, each followed by a status call or spot-check at roughly 370K context.
- 16% came from a weekly refresh reminder running inside the long build thread. Each reminder rebuilt about 700K tokens of history just to report that nothing was due.
- The same refresh job cost 7.9M input-equivalent tokens in a ~700K-context thread versus 1.5M right after compaction (about 5x).
- Workers were fairly lean (about 1M tokens each, 90% cached), though 15 to 20% of their reading went to instructions they did not need (workspace-wide docs, or an `AGENTS.md` their runtime already loads automatically), and some re-read the same raw file twice.

## Practices

### One thread per phase

Run each build phase in its own thread so every phase starts at zero context instead of replaying earlier phases on every turn.

Split a build along these boundaries:

1. Scope and crawl (plus catalogue, triage, fetch and speaker pass for a topic brain)
2. Ingest
3. Merge and debates
4. Rule audit, skill generation and evals
5. Each refresh run

Compact or hand over to a fresh thread whenever orchestrator context passes about 200K tokens. Pass state between phases through `<brain>/ingest/STATE.md` using this template:

````markdown
# <brain> build state

## Phase
<current phase and wave>

## Done
- <completed steps, batch counts, passing check outputs>

## Next step
- <exact next action to run>

## Open decisions
- <unresolved slug merges, rule independence calls, user questions>

## Files that matter
- <brain-relative paths: batches.yaml, slug-map.yaml, page-groups.yaml, etc.>

## Commands to resume
```sh
python -X utf8 -I <framework>/tools/wiki_edits.py --brain <brain> begin
<next tool command>
```
````

### One review per wave

After dispatching a wave of workers, answer each worker-completion notification with no tool calls until the last worker finishes. Skipping mid-wave status checks and spot-checks removes the ~370K-context turns that drove 58% of orchestrator spend.

Once the whole wave has landed, run `wave_report.py` once:

```sh
python -X utf8 -I <framework>/tools/wave_report.py --brain <brain> --batches <brain-relative yaml> [--wave KEY] [--max-lines 25]
```

`wave_report.py` checks every batch in one pass: that each staging file exists and parses, that every batch item has a source page, that `check_wiki.py` passes on staging and pages, that no `?` corruption slipped in, and that no protected pages changed during an open agent pass. It prints one line per batch plus a summary, and exits 1 if any batch fails. After it passes, spot-check 2 to 3 pages it names or picks, and rerun only failed batches. It covers ingest waves only; for a merge wave of concept pages, run `check_wiki.py` once over all the assigned pages instead.

### Fresh sessions for scheduled reminders

Run scheduled refresh reminders in a fresh session (or a separate thread), and start each actual refresh in a new thread. A reminder that fires inside a long build thread rebuilds hundreds of thousands of tokens of history just to say nothing is due.

### Model routing

Use a cheaper model to drive mechanical phases (dispatching waves, running scripts, crawls) and keep the strongest model for scope, rule extraction, merge planning and final review. Mechanical work follows fixed scripts and gates, while scope, rule independence and synthesis need the highest judgment.

### Lean worker briefs

Keep every worker brief self-contained and list the exact files the worker should read, so workers skip workspace-wide docs and avoid loading instructions twice.

- Do not tell workers to read `AGENTS.md` or `docs/workspace.md`; state any rule they need inline in the brief.
- Read each raw file once, in full, combining several small reads into one call where possible.
- Cap ingest batches at about 50 source pages (roughly 60K words) so worker context stays under about 150K tokens.
- Verify output by running `check_wiki.py` instead of re-reading finished files.

### Keep bulk out of the orchestrator

Read files with line limits in the orchestrator thread, and avoid opening images or whole raw files there. Every large read stays in the conversation and is billed again on every later turn. Send "read and judge" work (reading long transcripts, comparing full pages, grading rubrics) to a fresh subagent that returns a short verdict.

### Measure

Run `token_report.py` after each phase and compare numbers across builds so regressions show up immediately:

```sh
python -X utf8 -I <framework>/tools/token_report.py --workspace <path> [--since YYYY-MM-DD] [--claude-dir D] [--codex-dir D] [--t3-db F] [--ctx-warn 200000] [--top 30] [--json]
```

`token_report.py` reads local Claude Code transcripts, Codex sessions and optionally a T3 Code state database. It prints per-session turns, max and mean context, cache reads and writes, output tokens, and an input-equivalent cost (weights: input 1, cache read 0.1, cache write 1.25, output 5). It flags sessions whose context passed `--ctx-warn` (default 200,000) and splits Claude cost by trigger (user, worker notifications, scheduled).

Claude Code deletes transcripts after 30 days by default (`cleanupPeriodDays` in `settings.json`). Raise `cleanupPeriodDays` before starting a build you want to measure.

## What does not change

Accuracy checks are cheap and stay intact:

- `check_wiki.py` remains the acceptance gate on every worker output (run by each worker and again across the wave by `wave_report.py`).
- Cold evals still run with a fresh agent that has only the generated skill (`evals.md` and `verify_eval_quotes.py`).
- Any rebuilt wiki must score at least as well on evals as the one it replaces.

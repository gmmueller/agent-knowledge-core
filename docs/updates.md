# Keeping brains current

Every brain can go stale. Communities (Skool) change daily; courses change rarely. Refreshes are incremental: crawl only what's new or changed, ingest only that delta.

## Per-source fields (`sources.yaml`)

```yaml
refresh: daily | weekly | monthly | quarterly | yearly | manual | never   # cadence; manual/never = no reminder
last_crawled: 2026-10-11T00:00:00Z
cursor: <newest post id/timestamp, or lesson-list hash>   # where the next incremental crawl starts
```

## Refresh run

1. **Check the session.** Attach to the brain's Chrome (see AGENTS.md "Browser sessions"). If it's logged out, stop and notify the user; never try to log in yourself.
2. **Diff.** List items newer than `cursor`, plus changed ones (new lessons, edited posts, new comments on tracked threads). Courses: compare the lesson list against `outline.yaml`.
3. **Crawl the delta** into `raw/`. Raw files are immutable, so an edited post becomes a new dated file that references the old one.
4. **Ingest the delta.** Update source pages, touched topics and rules. Promote bench rules that gained a second source. Flag claims that contradict older material, since newer usually wins; record that on the page.
5. **Lint** the touched pages, update `index.md`, `hot.md` and `log.md`, advance `cursor` and `last_crawled`, and commit.
6. **Report:** a short "what's new in <brain>" summary (new items, changed rules, notable new advice).

## Scheduling

Once a brain is `active` and its refresh script runs unattended, schedule it with your scheduler (e.g. weekly), bound to the private workspace. Each scheduled run executes the steps above and posts the report. Browser sessions expire, so a refresh that finds the session logged out reports `NEEDS_USER` instead of failing silently.

## Reminders

- **Per brain:** `refresh: { reminders: false }` in the brain's `brain.md` frontmatter switches reminders off for that whole brain (default: on). Use it for brains you don't plan to update.
- **Per source:** the `refresh` cadence in `sources.yaml`. `manual` or `never` means no reminder for that source.
- **Check:** `python -I <framework>/tools/refresh_due.py --workspace <workspace> [--all]` (`--root` also works) lists sources whose `last_crawled` + cadence has passed. It reads files only (no browser, no network).
- **Schedule:** a weekly scheduled reminder runs the check and reports the list to the user. It only reminds; the refresh itself is started by the user, because most sources need the logged-in browser.

The reminder check also reads `library/*/sources.yaml` and flags `type: tool` wiki pages whose `recheck_by` date has passed.

## Topic brains

A topic brain refreshes through the library, then through the brain:

1. Re-catalogue the publisher (`library_yt.py catalogue`, `web_to_raw.py list`). New items append to `catalogue.tsv`.
2. Score only the new rows. `triage_inputs.py` skips items already scored; then run `triage_merge.py` again. Hand overrides survive.
3. Fetch the new tier A, B and X items, run the speaker pass on the multi-speaker ones, and ingest them as a new wave.
4. Re-run `merge_topic.py` and the concept-page writers for the concepts the new wave touched. Re-run `rule_status.py` to recount rule status.
5. Re-check dated pages: `type: tool` pages carry a `recheck_by` date, and `refresh_due.py` flags them when it passes.

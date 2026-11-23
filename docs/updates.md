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
3. **Crawl the delta** into `raw/`. Raw files are immutable (capture tools record a hash in `raw/.capture-hashes.json`), so an edited post becomes a new dated file that references the old one.
4. **Start the edit pass and ingest the delta.** Run `python -X utf8 -I <framework>/tools/wiki_edits.py --brain <brain> begin` before dispatching workers, and pass the protected list to them. Workers update source pages, touched topics and rules, skip any protected page (saving a proposal with `wiki_edits.py propose` instead), and never touch `notes/`. Promote bench rules that gained a second source. Flag claims that contradict older material, since newer usually wins; record that on the page.
5. **Lint, rebuild indexes and review proposals.** Run `lint_wiki.py` and fix broken links or changed captures before continuing. Review any human-edited pages and open proposals. Update `hot.md` and `log.md`, proposing changes to protected pages, then run `build_wiki_index.py` to rebuild the concept and source indexes, record agent changes and close the pass. Advance `cursor` and `last_crawled` after the rebuild succeeds. Review open proposals (`wiki_edits.py --brain <brain> proposals`) with the user before reporting the refresh done. The user accepts edits with `wiki_edits.py --brain <brain> accept <page>` or, between passes, `accept --all`.
6. **Report:** a short "what's new in <brain>" summary (new items, changed rules, notable new advice, and any proposals awaiting review).

**Adopting edit guards on existing data:** run once per existing brain or library before the first guarded pass:

```sh
python -X utf8 -I <framework>/tools/wiki_edits.py --brain <brain> record --init
python -X utf8 -I <framework>/tools/raw_guard.py --brain <brain> record --init
python -X utf8 -I <framework>/tools/raw_guard.py --workspace <workspace> record --init
```

If an agent pass runs without `wiki_edits.py begin`, its changes show up as human edits; review them with `wiki_edits.py --brain <brain> status` and confirm them with `wiki_edits.py --brain <brain> accept`.

## Scheduling

Once a brain is `active` and its refresh script runs unattended, schedule it with your scheduler (e.g. weekly), bound to the private workspace. Run every scheduled job in a fresh session, and start every manual refresh in a new thread: running a refresh inside a long build thread replays hundreds of thousands of tokens of old history on every turn (measured at roughly 5x the cost of a fresh context; see `docs/token-budget.md`). Each run executes the steps above and posts the report. Browser sessions expire, so a refresh that finds the session logged out reports `NEEDS_USER` instead of failing silently.

## Reminders

- **Per brain:** `refresh: { reminders: false }` in the brain's `brain.md` frontmatter switches reminders off for that whole brain (default: on). Use it for brains you don't plan to update.
- **Per source:** the `refresh` cadence in `sources.yaml`. `manual` or `never` means no reminder for that source.
- **Check:** `python -X utf8 -I <framework>/tools/refresh_due.py --workspace <workspace> [--all]` (`--root` also works) lists overdue sources and periodic sources that have captures but no `last_crawled` date. It reads files only. `--all` also shows sources that are not due.
- **Schedule:** a weekly scheduled reminder runs the check and reports the list to the user. Run the reminder in a fresh session (or a separate thread), never inside a build thread, so a routine "nothing due" check does not rebuild a long conversation's context. When items are due, the user starts the refresh in a new thread, because most sources need the logged-in browser.

The reminder check also reads `library/*/sources.yaml` and flags `type: tool` wiki pages whose `recheck_by` date has passed.

## Skool

The feed index keeps the previous activity cursor when a scan stops early. Rerun refresh with enough pages to reach the previous cursor or the end. Thread changes stay queued across scans and leave the queue only after a complete capture. Successful full crawls update the matching source's `last_crawled` date. A tracked thread still in the queue keeps the community source due. Lesson and attachment crawls keep successful items when one fails and exit with an error so the run can be retried.

## Topic brains

A topic brain refreshes through the library, then through the brain:

1. Re-catalogue the publisher (`library_yt.py catalogue`, `web_to_raw.py list`). New items append to `catalogue.tsv`. YouTube updates `last_crawled` once every requested tab succeeds. A successful web listing or complete fetch dates the sources it covered.
2. Score only the new rows. `triage_inputs.py` skips items already scored; then run `triage_merge.py` again. Hand overrides survive.
3. Fetch the new tier A, B and X items, run the speaker pass on the multi-speaker ones, then start an edit pass (`wiki_edits.py --brain <brain> begin`) and ingest them as a new wave. Pass the protected list to workers so they can file proposals. Update `hot.md` and `log.md` before closing the pass with `build_wiki_index.py`.
4. Start the merge pass with `wiki_edits.py --brain <brain> begin`, re-run `merge_topic.py` and the concept-page writers for the concepts the new wave touched, then re-run `rule_status.py --write` and `lint_wiki.py --fix-slug-map`. Update `hot.md` and `log.md` before closing the pass with `build_wiki_index.py`. Review open proposals (`wiki_edits.py proposals`) with the user before reporting done.
5. Recheck known web URLs with `web_to_raw.py fetch <publisher> --catalogue --recheck` or use `--items` or `--urls` for a selection. The tool compares the extracted content with the latest capture and writes a new raw revision only when it changes. Use those revisions as inputs for the next ingest wave.
6. Re-check dated pages: `type: tool` pages carry a `recheck_by` date, and `refresh_due.py` flags them when it passes.

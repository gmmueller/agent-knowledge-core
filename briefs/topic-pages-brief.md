# {{brain_name}} merge pass: concept page brief (for page writers)

You write the shared **concept pages** of the {{brain_name}} brain ({{brain_topic}}): topics, principles, methods, frameworks, rules, rubrics, glossary terms and tool pages, synthesised **across sources and experts**. The source pages already exist. Your input is one **bundle** per concept, holding everything the ingest workers extracted about it from every source.

Fill in every `{{placeholder}}` and the "fill in per brain" sections before dispatching a worker. This brief must stand alone.

**Paths and Python:**
- Framework root (`{{framework_path}}`): `AGENTS.md`, `docs/`, `tools/`, `examples/`.
- Workspace root (`{{workspace}}`): `library/` and `{{brain_name}}/`. All wiki, ingest and library paths below are relative to `{{workspace}}`.
- Run commands from `{{framework_path}}` (or pass full paths to `tools/` and `--brain`). Run Python as `{{python}} -X utf8 -I`; never `python3` on Windows, never a bare `python -` with stdin (both hang in agent shells). Write UTF-8 (never PowerShell `Set-Content`). Write final citation paths directly: never shorten paths to placeholder tokens to substitute later.

Read first:
1. `{{framework_path}}/AGENTS.md`.
2. `{{framework_path}}/docs/library.md` (citations, speakers).
3. `{{workspace}}/{{brain_name}}/brain.md` (scope, evidence types, experts, hosts, rule statuses, and what the brain must never do).
4. The gold example `{{gold_concept_page}}`. Copy its shape. If you are starting a brand-new brain with no local pages yet, point this at a reference page such as `{{framework_path}}/examples/workspace/plain-writing/wiki/methods/jargon-audit.md` (or write the first concept page yourself as the local gold). If it comes from another brain, ignore its topic.

## Inputs

- `{{brain_name}}/ingest/bundles/<slug>.yaml`: `type`, `names`, `aliases`, `evidence`, `freshness`, `items` (library items), `experts` (listed experts backing it), `speakers`, `status` (rules), `summaries`, and `points` and `quotes`. Each point and quote has `speaker`, `raw`, `at` and `item`; points may also carry brain-defined fields such as `variant` and `kind`.
- `{{brain_name}}/ingest/bundles/_conflicts.yaml`, `_speaker_doubts.yaml`, and where the brain has them `_findings.yaml` (research results with design and medium), `_examples.yaml`, `_tropes.yaml` and `_equipment.yaml`: use the entries about your concepts.
- `{{brain_name}}/wiki/sources/*.md`, `{{brain_name}}/wiki/examples/*.md` and the raw files under `library/`: open them to confirm a quote's context, speaker or meaning.
- `{{brain_name}}/ingest/item-pages.tsv`: two-column TSV (`item<TAB>page`) mapping each library item (`<publisher>/<source_id>`) to its source or example page slug(s); multi-chapter items repeat `item` across rows.
- `{{brain_name}}/ingest/page-groups.yaml`: defines `groups: [{name, slugs}]` (your assigned concept slugs) and `debates: [{slug, title, concepts}]` (for debate links).

## What you write (and nothing else)

One page per slug in your group (`{{brain_name}}/ingest/page-groups.yaml` → `groups`) at `{{brain_name}}/wiki/<dir>/<slug>.md`, where the type maps to a folder: topic → `topics`, principle → `principles`, method → `methods`, framework → `frameworks`, rule → `rules`, rubric → `rubrics`, tool → `tools`, glossary → `glossary`. Don't edit any other file: not source pages, not other groups' pages, not `notes/`, not `library/`, and not `index.md`, `hot.md`, `log.md` or `brain.md`. No git, no installs. Other writers work on other groups at the same time.

**Protected pages (from `wiki_edits.py begin`):** {{protected_pages}}

Never edit any page on that list, and never create, edit or delete anything in `{{brain_name}}/notes/`. If a slug in your group is protected, write the proposed full page to a temporary file and file it with `{{python}} -X utf8 -I "{{framework_path}}/tools/wiki_edits.py" --brain "{{workspace}}/{{brain_name}}" propose <page> --from <file> --why "<reason>"` (saves under `ingest/proposals/`), then list it in your report.

## Page format

```markdown
---
type: method
sources: [library/example-publisher/raw/yt/<file>.md, ...]   # every raw file you cite, with .md
updated: {{date}}
evidence: practitioner          # one value from the brain's evidence types: the strongest that genuinely applies
freshness: evergreen            # platform | tool-version | dated for anything that changes
status: consensus               # rules only: copy the bundle's (or contested, see below)
aliases: [...]                  # optional, from the bundle
---
# Example concept

One paragraph: what it is, who teaches it (by name), and how strong the support is. Link related concepts as [[slug]].

## Key points
- Synthesised point, attributed: "A and B both…", "C alone…". ([[library/...]] @ 12:41; [[library/...]] @ 4:10)

## How sources differ        (when they do; otherwise omit)
- A: … ([[library/...]] @ 12:41). B: … ([[library/...]] @ 3:05). Link [[debate-...]] where one exists.

## In their words
> "exact quote" — The Expert ([[library/...]] @ 13:04)

## Related
- [[other-slug]]: how it connects

## Sources
- [[source-page-slug]] · [[example-page-slug]] · ...
```

- **Sections flex with the brain.** Add the sections the brain's content needs, such as `## Evidence` (one bullet per study or source type: design, medium, outcome measured), `## What the platform says vs what creators believe`, `## Official rule` / `## Common practice` / `## Strategy`, or `## Cases`. Fill in below. Keep `## In their words`, `## Related` and `## Sources` on every page.
- Don't write a section named `## Examples`: `tools/link_examples.py` generates it.
- **Rule pages** use the rule (imperative) as the H1 and add `## Why` and `## When it applies` (cited, or **Inference:**) before `## In their words`.
- **Status** (rules): copy the bundle's. `consensus` = two or more listed experts (`experts` in `brain.md`; a duo that `expert_aliases` maps to one name counts once). `active` = two or more independent voices (hosts don't count; platform staff count as the platform). `bench` = one voice. `contested` = a source argues against the rule itself, and the page links a debate.
- **Debate pages are written by separate agents.** Their slugs and titles are under `debates:` in `page-groups.yaml`. If a concept is the subject of a debate, link it (`[[debate-...]]`) under `## How sources differ`. Set a rule to `contested` only when a source actually argues against the rule itself. A rule listed under a debate is often guidance every side shares: keep the bundle's status and report your doubt.
- **Partial support and borrowing.** If a second voice in the bundle backs only part of a rule, or a different context, say so in prose, add `status_locked: true` and a one-line `status_note:` to the frontmatter, and keep the status the evidence supports (for example `bench`). Voice counting also counts distinct names even when one author cites or borrows from another; note known borrowing in prose and lock the status when voices are not truly independent.
- **Merged concepts.** Bundles absorbed smaller concepts (see `{{brain_name}}/ingest/slug-map.yaml`); their names are in the bundle's `aliases`. Keep the useful sub-ideas as `###` sub-sections or bullets so nothing extracted is lost.
- **Sources section.** Map the bundle's `items` to page slugs with `ingest/item-pages.tsv`. A book item maps to several chapter pages: list only the chapters you actually cite.
- **Tool pages** (`type: tool`, folder `tools/`: platform features, metrics, vendors, products, programs): what the owner says the thing is and how it works, with every statement dated ("Help page, captured 2026-10-16:"). Add `reviewed: {{date}}` and `recheck_by: {{date_plus_90_days}}` to the frontmatter, and `freshness: platform` or `dated`. Give every price, commission or number in the form "listed at $174.99 (2026-10-16)". Separate the owner's own claims (marketing) from facts checked elsewhere. Put how practitioners use or read it in a separate, attributed and dated section.
- **Rubric pages** (`type: rubric`, frontmatter `scale: 0-2`): 6–10 non-overlapping criteria for judging one thing. Start with a `## Scoring sheet` table (# · criterion · from · must-pass). Then, per criterion, a `###` block with **Checks:** (what, linking the rule or concept pages), **Test:** (a concrete check a grader can run, quoting the expert's own test where one exists) and cited **2 / 1 / 0** anchors using the experts' own before/after examples or the example pages. Add `## How to use` and `## Verdicts` (score bands), labelled **Inference:** because the numbers are this wiki's, not the experts'.
- **Platform facts** (`freshness: platform`): give each source's date in the bullet. Prefer the most recent statement and say when an older one has been superseded. Never state an expert's claim about the platform as fact: "X believes (2026)…".

## Brain-specific page rules: fill in per brain

{{brain_page_rules}}

Examples of what belongs here (delete the ones that don't apply):
- **Hub pages** (one per variant, school or platform): start with a **passport table** of the facts that distinguish it, each cell cited or marked **Inference:**, then link every concept page for that label. Write hubs last.
- **Multi-label pages** (shared basics): one `###` sub-section per label under each section. Never blend two labels' rules into one sentence.
- **Label values** outside the allowed frontmatter list: map them as the brain says, and use the source's own name for the label in the text.
- **Authority kinds** (official rule, common practice, strategy) are always separate statements.
- **Humor, tropes, content angles:** built from `_tropes.yaml`, grouped by theme, every item cited, with the brain's tone limits stated on the page.

## Seed vocabulary: fill in per brain

{{seed_vocabulary}}

The canonical concept list is in `{{brain_name}}/ingest/page-groups.yaml` (groups and debates). Link concepts only to slugs on that list, and source pages by their file slug. Don't invent slugs.

## Content rules

- **Synthesise; don't list.** Merge points that say the same thing and cite all of their sources on one bullet. Order points from most to least fundamental. A big topic should have 8–20 key points; a glossary term 2–5. Use `###` sub-headings on big topics if that helps.
- **Name who says what.** Agreement between independent voices is the most valuable signal in a topic brain: make it visible ("A, B and C all…"). Disagreement goes under `## How sources differ`, never smoothed over. Guests and platform staff add weight in prose, cited by name.
- **Every key point needs at least one citation** `([[library/<publisher>/raw/<path without .md>]] @ <block>)`, copied from the bundle (`raw` + `at`). Several citations go in one parenthesis, separated by `;`. Anything you add beyond the sources is a bullet starting `- **Inference:**`.
- **Quotes are exact.** Copy them from the bundle (they were already checked) or straight from the raw file. 3–8 per page; rules need at least 1, preferably from a listed expert. No ellipses, no edits. Check each quote's context in the raw file before using it: don't use a quote whose meaning flips without its surrounding sentence.
- **Speakers.** Every quote names its speaker exactly as in the bundle; the checker verifies it against the block's speaker. A host's question isn't the guest's claim. `Unknown Speaker N` is never anyone's claim. Skip quotes listed in `_speaker_doubts.yaml` and quotes that contain excluded or garbled material. For a rule page, prefer a listed expert's own words; if the only quotes are someone else's, keep them labelled and say in `## Why` who teaches the rule.
- **Evidence honesty.** Performance numbers are self-reported unless the platform published them. A case is an illustration; one case doesn't generalise (mark any generalisation **Inference:**). Correlation is not causation. A talk retelling a study is weaker than the paper. A speaker relaying another's work is "X, relaying Y". Date anything about a changing system, and prefer the most recent statement where sources conflict.
- **Numbers and dates.** Attribute figures to their source and date; material spans several years. Don't present platform rules or numbers as current facts.
- **Conflicts.** Put the relevant entries from `_conflicts.yaml` under `## How sources differ`, with both citations.
- Promos (gear guides, affiliate tools, events, upsells) are never key points.

## Acceptance check

```sh
{{python}} -X utf8 -I "{{framework_path}}/tools/check_wiki.py" --brain "{{workspace}}/{{brain_name}}" <page paths...>
```

Pass paths that resolve from your working directory (or absolute paths). Iterate until it prints `ok: N files`. It verifies frontmatter, rule status, that every citation resolves, that every quote is verbatim at its block and that its speaker matches. It does not enforce minimum quote counts or synthesis depth; check the brief's minimums separately.

## Report back (short)

- Pages written (count) and the check's final line.
- Any proposals filed under `ingest/proposals/` for protected pages.
- Concepts you think should be merged or split, and any slug you linked that is missing from the list.
- Rules you think are contested or wrongly statused (one line each); rules whose only quotes aren't a listed expert's; anything odd.
- Stop and report if you're blocked for more than 30 minutes on one problem.

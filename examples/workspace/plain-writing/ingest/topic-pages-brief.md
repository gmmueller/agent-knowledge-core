# plain-writing merge pass: concept page brief (for page writers)

You write the shared **concept pages** of the plain-writing brain (clear English prose): topics, principles, methods, frameworks, rules, rubrics, glossary terms and tool pages, synthesised **across sources and experts**. The source pages already exist. Your input is one **bundle** per concept, holding everything the ingest workers extracted about it from every source.

Fill in every `field` and the "fill in per brain" sections before dispatching a worker. This brief must stand alone.

Paths are relative to the workspace `examples/workspace` unless they start with `tools/` (relative to `.`). Run Python as `python -X utf8 -I`; never `python3`, never a bare `python -` with stdin (both hang in agent shells). Write UTF-8 (never PowerShell `Set-Content`). Write final citation paths directly: never shorten paths to placeholder tokens to substitute later.

Read first (framework references are relative to the framework repository root):
1. `AGENTS.md`.
2. `docs/library.md` (citations, speakers).
3. `plain-writing/brain.md` (scope, evidence types, experts, hosts, rule statuses, and what the brain must never do).
4. The gold example `plain-writing/wiki/principles/economy-without-compression.md`. Copy its shape. If it comes from another brain, ignore its topic.

## Inputs

- `plain-writing/ingest/bundles/<slug>.yaml`: `type`, `names`, `aliases`, `evidence`, `freshness`, `items` (library items), `experts` (listed experts backing it), `speakers`, `status` (rules), `summaries`, and `points` and `quotes`. Each point and quote has `speaker`, `raw`, `at` and `item`; points may also carry brain-defined fields such as `variant` and `kind`.
- `plain-writing/ingest/bundles/_conflicts.yaml`, `_speaker_doubts.yaml`, and where the brain has them `_findings.yaml` (research results with design and medium), `_examples.yaml`, `_tropes.yaml` and `_equipment.yaml`: use the entries about your concepts.
- `plain-writing/wiki/sources/*.md`, `plain-writing/wiki/examples/*.md` and the raw files under `library/`: open them to confirm a quote's context, speaker or meaning.
- `plain-writing/ingest/item-pages.tsv`: maps each library item to its source or example page slug(s).

## What you write (and nothing else)

One page per slug in your group (`plain-writing/ingest/page-groups.yaml` → `groups`) at `plain-writing/wiki/<dir>/<slug>.md`, where the type maps to a folder: topic → `topics`, principle → `principles`, method → `methods`, framework → `frameworks`, rule → `rules`, rubric → `rubrics`, tool → `tools`, glossary → `glossary`. Don't edit any other file: not source pages, not other groups' pages, not `index.md`, `hot.md`, `log.md` or `brain.md`. No git, no installs. Other writers work on other groups at the same time.

## Page format

```markdown
---
type: method
sources: [library/example-publisher/raw/yt/<file>.md, ...]   # every raw file you cite, with .md
updated: 2026-11-20
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
- **Partial support.** If a second voice in the bundle backs only part of a rule, or a different context, say so in prose, add `status_locked: true` and a one-line `status_note:` to the frontmatter, and keep the status the evidence supports (for example `bench`).
- **Merged concepts.** Bundles absorbed smaller concepts (see `plain-writing/ingest/slug-map.yaml`); their names are in the bundle's `aliases`. Keep the useful sub-ideas as `###` sub-sections or bullets so nothing extracted is lost.
- **Sources section.** Map the bundle's `items` to page slugs with `ingest/item-pages.tsv`. A book item maps to several chapter pages: list only the chapters you actually cite.
- **Tool pages** (`type: tool`, folder `tools/`: platform features, metrics, vendors, products, programs): what the owner says the thing is and how it works, with every statement dated ("Help page, captured 2026-10-16:"). Add `reviewed: 2026-11-20` and `recheck_by: 2027-02-18` to the frontmatter, and `freshness: platform` or `dated`. Give every price, commission or number in the form "listed at $174.99 (2026-10-16)". Separate the owner's own claims (marketing) from facts checked elsewhere. Put how practitioners use or read it in a separate, attributed and dated section.
- **Rubric pages** (`type: rubric`, frontmatter `scale: 0-2`): 6–10 non-overlapping criteria for judging one thing. Start with a `## Scoring sheet` table (# · criterion · from · must-pass). Then, per criterion, a `###` block with **Checks:** (what, linking the rule or concept pages), **Test:** (a concrete check a grader can run, quoting the expert's own test where one exists) and cited **2 / 1 / 0** anchors using the experts' own before/after examples or the example pages. Add `## How to use` and `## Verdicts` (score bands), labelled **Inference:** because the numbers are this wiki's, not the experts'.
- **Platform facts** (`freshness: platform`): give each source's date in the bullet. Prefer the most recent statement and say when an older one has been superseded. Never state an expert's claim about the platform as fact: "X believes (2026)…".

## Brain-specific page rules: fill in per brain

Synthesize only what the bundles support. Keep caveats attached to the recommendation. Historical spelling and dialect advice is dated. New practical procedures are explicitly **Inference:**. No official platform, video example, rubric or tool pages are assigned.


## Seed vocabulary: fill in per brain

- `clear-prose` (topic): Clear prose
- `paragraph-unity` (topic): Paragraph unity
- `sentence-emphasis` (topic): Sentence emphasis
- `voice-and-agency` (topic): Voice and agency
- `diction-and-register` (topic): Diction and register
- `punctuation-and-attachment` (topic): Punctuation and attachment
- `historical-usage` (topic): Historical usage
- `economy-without-compression` (principle): Economy without compression
- `meaning-before-etymology` (principle): Meaning before etymology
- `reader-attention` (principle): Reader attention
- `revision-pass` (method): A revision pass
- `paragraph-plan` (method): Plan a paragraph
- `jargon-audit` (method): Audit jargon
- `circumlocution` (glossary): Circumlocution
- `concrete-language` (glossary): Concrete language
- `parallelism` (glossary): Parallelism
- `rule-prefer-familiar-words` (rule): Prefer familiar words
- `rule-prefer-concrete-words` (rule): Prefer concrete words
- `rule-omit-needless-words` (rule): Omit needless words
- `rule-prefer-active-voice` (rule): Prefer the active voice when it suits the subject
- `rule-preserve-parallel-form` (rule): Preserve parallel form
- `rule-keep-related-words-together` (rule): Keep related words together

The canonical concept list is in `plain-writing/ingest/page-groups.yaml` (groups and debates). Link concepts only to slugs on that list, and source pages by their file slug. Don't invent slugs.

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

```
python -X utf8 -I "./tools/check_wiki.py" --brain "examples/workspace/plain-writing" <absolute page paths...>
```

Iterate until it prints `ok: N files`. It verifies frontmatter, rule status, that every citation resolves, that every quote is verbatim at its block and that its speaker matches.

## Report back (short)

- Pages written (count) and the check's final line.
- Concepts you think should be merged or split, and any slug you linked that is missing from the list.
- Rules you think are contested or wrongly statused (one line each); rules whose only quotes aren't a listed expert's; anything odd.
- Stop and report if you're blocked for more than 30 minutes on one problem.

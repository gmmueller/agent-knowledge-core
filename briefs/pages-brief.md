# {{brain_name}} merge pass: concept page brief (for page writers)

You write the shared **concept pages** of the {{brain_name}} brain wiki: topics, principles, methods, frameworks, rules and glossary terms taught across {{expert_name}}'s {{source_scope}}. The per-lesson source pages already exist. Your input is one **bundle** per concept, with everything the ingest workers extracted about it from every lesson.

Read the workspace `AGENTS.md` first. Paths are relative to `{{brain_path}}` unless they start with `tools/` (relative to `{{framework_path}}`). Fill in every placeholder before dispatching a worker.

## Inputs

- `ingest/bundles/<slug>.yaml`: one per concept. It has `type`, `names`, `aliases`, `lessons` (distinct lesson ids), `status` (rules only), `summaries` (from each batch), `points` (paraphrased teaching points with `raw`, `at`, `lesson`, `presenter`) and `quotes` (exact quotes, same fields, sometimes `speaker`).
- `ingest/bundles/_conflicts.yaml`: contradictions found during ingest. Use the ones about your concepts.
- `wiki/sources/<lesson-id>.md`: the source pages. Open them when a bundle point is unclear.
- `raw/...`: the transcripts. Open them to confirm a quote's context, speaker or meaning.

## What you write (and nothing else)

One page per slug in your group, at `wiki/<dir>/<slug>.md`, where `<dir>` comes from the bundle `type`: topic → `topics`, principle → `principles`, method → `methods`, framework → `frameworks`, rule → `rules`, glossary → `glossary`. Don't edit any other file: not source pages, not other groups' pages, not `index.md`, `hot.md`, `log.md` or `brain.md`. No git, no installs.

## Page format

```markdown
---
type: framework                      # from the bundle
sources: [raw/{{product}}/.../l01-x.md, ...] # every raw file you cite, with .md
updated: {{date}}
status: active                       # rules only: copy the bundle's status
aliases: ["{{framework_alias}}"] # optional, from the bundle
---
# {{concept_name}}

One paragraph: what it is, in {{expert_name}}'s terms, and why it matters to the expert. Link related concepts as [[slug]].

## Key points
- Synthesised teaching point, merged across lessons where they say the same thing. ([[raw/{{product}}/m02-x/l01-y]] @ 1:07; [[raw/{{product}}/m07-s01-x/l03-z]] @ 4:12)
- ...

## In {{expert_name}}'s words
> "exact quote" — ([[raw/...]] @ 1:07)
> "exact quote by someone else" — {{other_speaker}} ([[raw/...]] @ 12:30)

## Tensions and changes            (only if there are any)
- Lesson A says X ([[raw/...]] @ t); lesson B says Y ([[raw/...]] @ t). **Inference:** probably because ...

## Related
- [[other-slug]]: one line on how it connects

## Sources
- [[{{lesson_id}}]] · [[{{other_lesson_id}}]] · ...   (the source pages: the bundle's `lessons`)
```

Rule pages also have these sections, before `## In {{expert_name}}'s words`:
- `# <the rule, imperative, {{expert_name}}'s phrasing where possible>`
- `## Why`: {{expert_name}}'s reasoning, with citations.
- `## When it applies`: scope and exceptions, with citations, or **Inference:** if you're deducing them.

## Content rules

- **Synthesise; don't list.** Merge points that say the same thing and cite all of their sources on one bullet. Order points from most to least fundamental. A big topic should have 8–20 key points; a glossary term 2–5. Use sub-headings (`###`) on big topics if that helps.
- **Every key point needs at least one citation** in the form `([[raw/<path without .md>]] @ <block label | p. N | page text>)`, taken from the bundle (`raw` + `at`). Several citations go in one parenthesis, separated by `;`. Anything you add beyond the sources is a bullet starting `- **Inference:**`.
- **Quotes are exact.** Copy them from the bundle (they were already checked) or straight from the raw file. 3–8 per page, choosing the most quotable and teaching-dense ones; rules need at least 1. No ellipses, no edits.
- **Speakers.** A quote with no name is {{expert_name}}'s. Put the speaker's name before the citation when it isn't {{expert_name}}: check the bundle's `speaker` or `presenter`, and the raw file if the presenter is mixed (e.g. "{{expert_name}}; {{other_speaker}}"). Team members may teach some courses; guests may appear in live workshops. Confirm speakers from each source. For rule pages, prefer {{expert_name}}'s own words. If the only quotes are someone else's, keep them labelled, and add a line in `## Why` saying who teaches the rule.
- **Context check.** Don't use a quote whose meaning flips without its surrounding sentence (e.g. "{{quote_presented_as_someone_elses_view}}" when {{expert_name}} is presenting it as other people's view). Open the raw block when in doubt.
- **Numbers and dates.** Attribute figures to their lesson ("in a 2023 session {{expert_name}} reports…"); course material spans several years. Don't present platform rules or numbers as current facts.
- **Conflicts.** Put relevant entries from `_conflicts.yaml` under `## Tensions and changes`, with both citations.
- **Links.** Link other concepts as `[[slug]]` using their canonical slugs; the full list is in `ingest/page-groups.yaml`. Link source pages as `[[<lesson-id>]]`. Don't invent slugs that aren't in the list.
- Promos (gear guides, affiliate tools, events, upsells) are never key points.

## Seed vocabulary: fill in per brain

{{seed_vocabulary}}

Use the canonical concept list in `ingest/page-groups.yaml`; the orchestrator fills vocabulary and groups before dispatching.

## Acceptance check

```powershell
python -I "{{framework_path}}/tools/check_wiki.py" --brain "{{brain_path}}" <absolute page paths...>
```

Use absolute paths for the brain and page files. It verifies frontmatter, rule status and quotes, and that every citation resolves and every quote is verbatim at its block. Iterate until it prints `ok: N files`.

## Report back (short)

- Pages written (count) and the check's final line.
- Concepts you thought should be merged or split, and any slug you linked that is missing from the list.
- Rules whose only quotes aren't {{expert_name}}'s; anything odd.

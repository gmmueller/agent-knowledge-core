# plain-writing merge pass: debate page brief (for debate writers)

You write **debate pages**: one page per question on which the sources disagree, rule differently, or speak from different positions. Read `./briefs/topic-pages-brief.md` (filled in for this brain: `plain-writing/ingest/topic-pages-brief.md`) first. Its inputs, speaker rules, citation rules, quote rules, evidence discipline and acceptance check all apply here too.

This is the filled brief retained for this completed example. This brief must stand alone apart from the page brief it points to.

Paths are relative to the workspace `examples/workspace`. Run Python as `python -X utf8 -I`; never `python3`, never a bare `python -` with stdin. Write UTF-8.

- **Your list:** `plain-writing/ingest/page-groups.yaml` → `debates:`. Each entry gives a `slug`, a `title` (the question) and the `concepts` it covers.
- **Gold example:** `plain-writing/wiki/debates/debate-economy-and-beauty.md`. Copy its shape and tone. If it comes from another brain, ignore its topic.
- **Inputs:**
  - the bundles for the listed concepts (`plain-writing/ingest/bundles/<slug>.yaml`);
  - `_conflicts.yaml` (the ingest workers' disagreements, each with both sides cited) and, where the brain has it, `_findings.yaml`;
  - the concept pages under `plain-writing/wiki/`, if they already exist (other writers are producing them now);
  - the source and example pages, mapped through `plain-writing/ingest/item-pages.tsv`, and the raw files.

## Page format

Write each page at `plain-writing/wiki/debates/<slug>.md`.

Frontmatter:
- `type: debate`
- `sources: [...]`: every raw file you cite.
- `updated: 2026-11-20`
- `evidence`: the strongest type that genuinely applies.
- `freshness`
- publication_precision: year; paragraphs: first-last for HTML sections

Then these sections, in order:

1. **`# <title>`**
2. **Opening paragraph:** each side, who holds it (by name), what kind of evidence or authority each side rests on, and how strong it is.
3. **`## Key points`:** one bold-led bullet per position or ruling. Attribute each one and cite it. Give the context it was said in (size, niche, year, format, or for rules the document and version), because many disagreements are really about different contexts or different years.
4. **`## Where they actually differ`** (for rules and facts: the exact cases where the outcome changes, a table helps) or **`## When each side applies`** (for strategy: the conditions under which each position holds). For culture or values debates, say what each side is objecting to or defending, in their own terms. Cite where a source says so; otherwise label it **Inference:**.
5. **`## What to do in practice`** (how the brain should answer when the question comes up, for example "ask which ruleset the event uses" or "state the rule, then the common custom") or **`## What would settle it`** (a test someone could run on their own case). Label it **Inference:** unless a source says it.
6. **`## In their words`:** 5–8 exact quotes, at least one per side, each naming its speaker.
7. **`## Related`:** links to the listed concepts and other debates.
8. **`## Sources`:** source and example page slugs.

## Brain-specific rules: fill in per brain

Distinguish actual opposition from differences of emphasis. Do not call a shared clarity rule contested just because it appears in a debate. The hybrid-coinage debate is a genuine disagreement in priorities; the economy debate records shared qualifications and different aims.


## Rules

- **Don't pick a winner.** For rules debates, say which document governs which events. Where one side clearly has stronger support, say so plainly and say why.
- **Report a recommended rule status.** If a listed rule is the direct subject of your debate, say whether a source argues against the rule itself (then `contested` fits) or every side shares it (then it doesn't). Don't edit the rule page.
- Check an ingest "conflict" in the raw text before building a debate on it. Some turn out to be agreement on a closer read; if so, say so in your report and write the page about what remains.
- Write only your debate pages. No git, no installs. Other writers work at the same time.
- Run `python -X utf8 -I "./tools/check_wiki.py" --brain "examples/workspace/plain-writing" <your files>` until it prints `ok: N files`.
- **Report:** the pages you wrote, the check's final line, and one line per debate on where it stands (where the support leans, and your recommended status for any listed rule).

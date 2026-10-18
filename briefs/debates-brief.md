# {{brain_name}} merge pass: debate page brief (for debate writers)

You write **debate pages**: one page per question on which the sources disagree, rule differently, or speak from different positions. Read `{{framework_path}}/briefs/topic-pages-brief.md` (filled in for this brain: `{{pages_brief_path}}`) first. Its inputs, speaker rules, citation rules, quote rules, evidence discipline and acceptance check all apply here too.

Fill in every `{{placeholder}}` before dispatching a worker. This brief must stand alone apart from the page brief it points to.

Paths are relative to the workspace `{{workspace}}`. Run Python as `{{python}} -I`; never `python3`, never a bare `python -` with stdin. Write UTF-8.

- **Your list:** `{{brain_name}}/ingest/page-groups.yaml` → `debates:`. Each entry gives a `slug`, a `title` (the question) and the `concepts` it covers.
- **Gold example:** `{{gold_debate_page}}`. Copy its shape and tone. If it comes from another brain, ignore its topic.
- **Inputs:**
  - the bundles for the listed concepts (`{{brain_name}}/ingest/bundles/<slug>.yaml`);
  - `_conflicts.yaml` (the ingest workers' disagreements, each with both sides cited) and, where the brain has it, `_findings.yaml`;
  - the concept pages under `{{brain_name}}/wiki/`, if they already exist (other writers are producing them now);
  - the source and example pages, mapped through `{{brain_name}}/ingest/item-pages.tsv`, and the raw files.

## Page format

Write each page at `{{brain_name}}/wiki/debates/<slug>.md`.

Frontmatter:
- `type: debate`
- `sources: [...]`: every raw file you cite.
- `updated: {{date}}`
- `evidence`: the strongest type that genuinely applies.
- `freshness`
- {{extra_frontmatter}}

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

{{brain_debate_rules}}

Examples of what belongs here (delete the ones that don't apply):
- Which side wins when one has stronger support (a platform's own statement against an expert's belief; several experts against one; a recent statement against an old one): say so plainly and say why.
- Keep the platform's statements and experts' beliefs apart, and date both.
- For culture debates, present each community's view with respect and attribution. Never frame one group's practice as illegitimate.

## Rules

- **Don't pick a winner.** For rules debates, say which document governs which events. Where one side clearly has stronger support, say so plainly and say why.
- **Report a recommended rule status.** If a listed rule is the direct subject of your debate, say whether a source argues against the rule itself (then `contested` fits) or every side shares it (then it doesn't). Don't edit the rule page.
- Check an ingest "conflict" in the raw text before building a debate on it. Some turn out to be agreement on a closer read; if so, say so in your report and write the page about what remains.
- Write only your debate pages. No git, no installs. Other writers work at the same time.
- Run `{{python}} -I "{{framework_path}}/tools/check_wiki.py" --brain "{{workspace}}/{{brain_name}}" <your files>` until it prints `ok: N files`.
- **Report:** the pages you wrote, the check's final line, and one line per debate on where it stands (where the support leans, and your recommended status for any listed rule).

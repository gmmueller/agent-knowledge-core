# {{brain_name}} ingest brief (for batch workers)

You are ingesting part of the **{{brain_name}} brain**: a topic brain on {{brain_topic}}. It is built from {{source_scope}} in the shared library (`{{workspace}}/library/<publisher>/raw/`). You turn raw files into **wiki source pages** (and example pages, where your batch marks them), plus **staging notes** that a later merge pass uses to build shared concept, rule, rubric and debate pages.

Fill in every `{{placeholder}}` and the "fill in per brain" sections before dispatching a worker. This brief must stand alone: the worker sees nothing else of the conversation.

**Paths and Python:**
- Framework root (`{{framework_path}}`): `AGENTS.md`, `docs/`, `tools/`, `examples/`.
- Workspace root (`{{workspace}}`): `library/` and `{{brain_name}}/`. All wiki, ingest and library paths below are relative to `{{workspace}}`.
- Run commands from `{{framework_path}}` (or pass full paths to `tools/` and `--brain`). Run Python as `{{python}} -X utf8 -I` (your venv's Python). Never use `python3` on Windows, and never pipe a script into a bare `python -` (both hang in agent shells): write a script file or use `-c`. Write UTF-8, and never use PowerShell `Set-Content`.

Read first:
1. `{{workspace}}/{{brain_name}}/brain.md` (scope, evidence types, experts, extraction areas, what the brain must never do).
2. The gold example `{{gold_source_page}}`. Copy its shape. If you are starting a brand-new brain with no local pages yet, point this at a reference page such as `{{framework_path}}/examples/workspace/plain-writing/wiki/sources/strunk-concision.md` (or write the first source page yourself as the local gold). If it comes from another brain, ignore its topic.

Core rules (self-contained): use primary sources only (no third-party summaries unless `sources.yaml` marks them as such), cite every claim or mark it **Inference:**, back every rule with at least one verbatim quote, and keep source text private (never paste it into external services).

## Reading budget

- Read only the files this brief lists (`brain.md`, the gold example, `ingest/slugs.txt` and `ingest/slug-map.yaml` if they exist, and your assigned raw files).
- Do not open `AGENTS.md`, `docs/workspace.md`, or other workspace-wide docs.
- Read each raw file once, in full.
- Batch several small reads into one command where possible.
- Do not re-read a file you just wrote to check it; run `check_wiki.py` instead.

## What you write (and nothing else)

1. For each item in your batch, ONE of:
   - `{{brain_name}}/wiki/sources/<slug>.md` (type `source`): every item except those marked `page: example` in your batch. When the batch gives a page range of a book or paper, write **one page per chapter or section**.
   - `{{brain_name}}/wiki/examples/<slug>.md` (type `example`): items marked `page: example` (a live diagnosis or demonstration of one real case). Omit this line for brains without example pages.
   Slug: `<publisher>-<short title slug>`, kebab-case, at most 60 characters (for example `{{example_slug}}`).
2. `{{brain_name}}/ingest/staging/<batch>.yaml`: one file for your whole batch.

**Protected pages (from `wiki_edits.py begin`):** {{protected_pages}}

Never edit any page on that list, and never create, edit or delete anything in `{{brain_name}}/notes/`. If your batch needs to update a protected page, write the proposed full page to a temporary file and file it with `{{python}} -X utf8 -I "{{framework_path}}/tools/wiki_edits.py" --brain "{{workspace}}/{{brain_name}}" propose <page> --from <file> --why "<reason>"` (saves under `ingest/proposals/`), then list it in your report.

Write nothing else. Never edit `library/` (raw is immutable) or `{{brain_name}}/notes/`. Don't run git. Don't install anything. Other workers are writing other batches at the same time.

Save each intended wiki page in a separate draft and check `wiki_edits.py status` before writing the live page. Register each completed write with `{{python}} -X utf8 -I "{{framework_path}}/tools/wiki_edits.py" --brain "{{workspace}}/{{brain_name}}" mark-written <page> --from <draft>`.

## Hard rules for this brain: fill in per brain

{{hard_rules}}

Examples of what belongs here (delete the ones that don't apply):
- **Excluded content.** Never write out material the brain must not reproduce (for example a copyrighted annual card), even if a raw file contains it. Describe it in general terms. Skip quotes that contain it.
- **Labels on every claim.** If the topic has variants, platforms or schools (rule sets, versions, countries), every key claim, concept and point names which one it applies to, and rulebook claims name the document and version.
- **Authority kinds stay separate.** An official rule, a common practice and a strategy opinion are three different claims. "X says many do A, but the rule is B" is two claims.
- **Health, money or safety claims.** Observational research is "associated with", never "prevents" or "improves", unless a source reports a randomised trial (then name the trial).
- **Dated facts.** Prices, commissions, counts, stock and feature lists carry their capture date (`captured` in the raw frontmatter) in the text: "listed at $174.99 (2026-10-16)".
- **Culture and sensitivity.** Record each community's practice in its own terms. Attribute contested arguments to the people making them.

## Source page format

- **Frontmatter:**
  - `type: source`
  - `sources: [library/<publisher>/raw/<path>.md]` (every raw file you cite, with `.md`)
  - `updated: {{date}}`
  - `publisher`, `item` (`<publisher>/<source_id>`), `url`, `title`, `published`, `method` and `speaker_method` (copied from raw; if a web capture has empty `published` because the page lacked date metadata, record the verified edition year and `publication_precision: year` on the source page and leave raw untouched)
  - `speakers` (who talks); for books, papers and rulebooks, `authors` instead
  - `pages: <first>-<last>` for a book section (PDF page numbers); `duration` for video or audio
  - `evidence:` one of {{evidence_types}} (defined in `brain.md`; `inference` is always allowed)
  - `freshness: evergreen | platform | tool-version | dated` (use anything but `evergreen` for platform behaviour, tool versions, prices and other dated facts)
  - {{extra_frontmatter}}
- `# <title>` (for a section: `# <Document>: <section title>`)
- **Summary:** one paragraph of 3–6 sentences: who speaks or wrote it (host vs guest), what they teach, and how strong the support is (study, own numbers, client cases, anecdote). Link concepts with `[[slug]]`.
- **`## Key claims`:** 8–25 bullets (more for a two-hour item or a long chapter). Each is one claim in your words, **attributed** ("X argues…", "the rulebook says…"), followed by its citation. Capture the *reasoning* behind a recommendation, not just the recommendation. Anything not directly supported is a bullet starting `- **Inference:**`.
- **`## Evidence`** (papers and chapters that report studies only): one bullet per study: design, sample and medium, the main result, and the authors' own limits. Say plainly when a point rests on an anecdote or a case, not a study.
- **`## Quotes`:** 5–14 exact quotes: `> "exact words" — <Speaker or Author> ([[library/<publisher>/raw/<path-without-.md>]] @ <where>)`. Every quote names its speaker, written as in the block's speaker prefix. Books and papers: the author(s) as in the raw frontmatter. Rulebooks: the issuing body. In staging, put `speaker:` on every quote.
- **`## Examples`:** one bullet per case the source uses (a channel, a video, a client, a hand, a story): what happened, what the speaker says it shows, any numbers (marked self-reported where they are), and the citation. Cases illustrate; they don't prove.
- **`## Concepts`:** bullets of `[[slug]]: how this source uses it`.

### Example page format (only for items marked `page: example`)

A live diagnosis or demonstration of one real case. The page is a **case**, written so a reader can learn the reasoning.

- **Frontmatter:** `type: example`, `sources` (the raw transcript and, for measured videos, `library/<publisher>/examples/<item-id>.yaml`), `updated`, `item`, `url`, `title`, `published`, `duration`, `method`, `speaker_method`, `speakers`, `evidence`, `freshness`, plus `{{example_frontmatter}}` (for example `subject:` the case under review and `diagnosed_by:`).
- `# <title>`, then a summary paragraph: whose case, its size and goal as stated, the core problem, the expert's verdict.
- **`## Key points`** (every bullet cited or **Inference:**), in this order: the case and its goal; the symptoms and numbers shown (values as stated); the diagnosis and the reasoning chain behind it; each prescription with its reason; the principles applied (`[[slug]]`).
- **`## Quotes`:** 6–12 exact quotes, mostly the expert's diagnosis. The case owner's own account can be quoted under their own name as context.
- **`## Concepts`.**
- A long stream that reviews several cases gets one example page, with a `###` sub-block per case under Key points.
- Observations from a measured video (cuts, frames, on-screen text) cite the examples file with seconds: `([[library/<publisher>/examples/<item-id>]] @ 1.5s)`. A page may cite only its own video's files (`check_examples.py` enforces this).

### Citations and quotes (the checker enforces these)

- Citation: `([[library/<publisher>/raw/<path without .md>]] @ <where>)`, where `<where>` is the block label exactly as it appears in bold at the start of the block: `@ 12:41` (transcripts), `@ ¶12` (web pages), `@ p. 37` (books, rulebooks and papers: PDF page). Use the block where the words **start**.
- Quotes are **verbatim and contiguous** from the block text after any speaker prefix: no ellipses, no brackets, no grammar fixes, no joining of separate sentences. At most 40 words. You may start or end mid-sentence.
- Choose quotes that carry method, findings or reasoning: definitions, tests, rules of thumb, numbers, the "because". Skip banter, promos and filler.
- **Auto-captions** have odd words and no punctuation fixes. **Book and paper text** has PDF artefacts: odd capitals in running heads, page headers mid-sentence, split words. **OCR text** has errors (missing spaces, dropped letters). Quote clean stretches only; paraphrase the rest.
- **Symbol fonts:** diagrams, notation and glyph-based examples may come out as stray letters. Quote prose only, and say on the page if a worked example is unreadable.
- **Reader comments** below a page: the crawl log (`library/<publisher>/crawl-log.md`) gives the paragraph range. Quote only the author's own text. Paraphrase a commenter as "a reader asked…"; their claims never count as the author's.
- **News reports:** quote the journalist's report or a named quoted person. Note "news reporting" and the date.

### Speakers

- `speaker_method: transcript` is the publisher's own labelling: reliable.
- `speaker_method: diarized` is machine-assigned and about 85% right at turn edges. Before you quote or attribute anything, read the block **and its neighbours**. If the words clearly belong to someone else (a host's question, an audience member, another co-host, a clip), don't quote it. Paraphrase it in Key claims with the right attribution and add a `speaker_doubts` entry. Never "fix" a speaker mismatch by renaming to a label you believe is wrong.
- `speaker_method: single` labels every block with one name, but a talk may play clips of other people. Check that a block is the narrator's own words before quoting it under their name.
- **Hosts' questions are not the guest's claims.** Cite hosts under their own names; their claims never count as an expert's. Cite guests under their own names too.
- Some captions carry inline markers ("SPEAKER NAME:", "AUDIENCE:"). Trust those over the block prefix, and don't quote audience lines.
- `Unknown Speaker N` is never anyone's claim.
- Platform staff speak for the platform: tag them `evidence: official` and date the claim.

### Evidence discipline

- An expert's claim about how a platform or system works is their belief, dated ("X believes (2025)…"). Only the platform's own staff and help pages state how it works.
- Self-reported performance numbers are self-reported: say so.
- A case story is an illustration, not proof. A correlation is not a cause. Record the medium a study measured; don't stretch a finding about one medium to another without marking that **Inference:**.
- A speaker relaying someone else's study is "X, relaying Y".
- When sources disagree (two experts; an expert and the platform; an older and a newer statement by the same person; two rulebooks), add a `conflicts` entry with both citations. Don't pick a winner.
{{evidence_rules}}

## Staging file: `{{brain_name}}/ingest/staging/<batch>.yaml`

```yaml
batch: a
items:                        # every page you wrote
  - item: example-publisher/yt-abc123
    page: example-publisher-short-title
    kind: source              # source | example
    pages: 27-50              # book sections only
    speakers: {The Expert: guest, The Host: host}
concepts:
  - slug: example-concept
    type: method              # topic | principle | method | framework | rule | glossary | rubric | tool
    name: "Example concept"
    aliases: ["another name"]
    evidence: practitioner    # one of the brain's evidence types
    freshness: evergreen
    summary: "One or two sentences on what your batch's sources say this is."
    points:                   # distinct teaching points, each with a citation and who made it
      - text: "The Expert says to test an idea against three audiences before making it."
        speaker: The Expert
        cite: {raw: library/example-publisher/raw/yt/20240512-abc123-example, at: "12:41"}
        # optional classification fields the brain defines, copied to bundles: variant, kind
    quotes:
      - text: "<exact words>"
        speaker: The Expert
        cite: {raw: library/example-publisher/raw/yt/20240512-abc123-example, at: "12:41"}
  - slug: rule-example-imperative
    type: rule                # guidance the brain applies; needs at least one exact quote
    status: bench             # leave bench for the merge pass
    name: "Test every idea before making it"
    summary: "..."
    points: []
    quotes:
      - text: "<exact words>"
        speaker: The Expert
        stance: supports      # optional on each rule point or quote; supports | nuances | opposes
        cite: {raw: ..., at: "12:41"}
findings:                     # optional: research results, one per study
  - text: "..."
    design: "observational, 7,000 articles over 3 months"
    medium: "news articles"
    authors: "Author and Author"
    cite: {raw: ..., at: "p. 7"}
examples:                     # optional: every case a source uses
  - case: "Name of the case"
    case_slug: name-of-case
    speaker: The Expert
    shows: "what the speaker says it shows"
    numbers: "self-reported: ..."
    cite: {raw: ..., at: "..."}
conflicts:
  - text: "A says X; B says Y."
    cites: [{raw: ..., at: ...}, {raw: ..., at: ...}]
speaker_doubts:
  - {raw: ..., at: "..", note: "block labelled A but the words answer A's question; possibly B"}
```

- Other optional lists (`tropes`, `equipment`, or any list your brain defines) use the same shape as `findings`: `text`, `cite`, and the fields you name below. `merge_topic.py` pools `conflicts`, `examples`, `speaker_doubts`, `findings`, `tropes` and `equipment` into `_*.yaml` files beside the bundles.
- **Rule stance.** Use `nuances` when the source supports only part of the rule or limits it to a narrower context. Use `opposes` when the source explicitly rejects the rule. `supports` is the default. The merge copies these labels to the bundles.
- **Be generous.** The merge pass works only from staging plus your pages, so anything you leave out is lost. Aim for every 20 minutes of talk, or every chapter, to feed 6–15 concepts.
- **Types:** topic = a subject area; principle = a belief or truth the experts teach; method = a step-by-step how-to; framework = a named multi-part model; glossary = a term; **rule** = an imperative the brain should apply when answering or making things (slug starts with `rule-`, needs at least one exact quote by the person who says it); **rubric** = how a source *judges* something, with the criteria as points; **tool** = a platform feature, metric or product as its owner defines it, dated, with `reviewed: <today>` and `recheck_by: <today + 90 days>` (a creator's use of a metric is a `topic`, not a `tool`). Facts that are not guidance for the brain (a game rule, a definition) go in points under a topic or method, not in a `rule` page.
- **Slugs** are kebab-case and unique wiki-wide. Before inventing one, check `{{brain_name}}/ingest/slugs.txt` (concepts from earlier waves, if it exists) and the seed vocabulary below. Reuse a slug whenever the idea matches, and put sub-parts in points instead of new slugs. If `{{brain_name}}/ingest/slug-map.yaml` exists, never use a slug that appears as a key in it: use its canonical slug. New slugs need a genuinely new idea with three or more points; the merge pass folds thin ones.

## Seed vocabulary: fill in per brain

{{seed_vocabulary}}

List canonical slugs, grouped by area, before dispatching. Reuse them. Add the extra staging fields your brain uses (for example `variant`, `kind`, `freshness`) and what each value means.

## Acceptance check (must pass before you report)

```sh
{{python}} -X utf8 -I "{{framework_path}}/tools/check_wiki.py" --brain "{{workspace}}/{{brain_name}}" <page files...> "{{workspace}}/{{brain_name}}/ingest/staging/<batch>.yaml"
```

Pass paths that resolve from your working directory (or absolute paths). `check_wiki.py` flags corrupt text, checks each raw link and locator, and verifies exact quotes and their speakers. Keep Key claims populated. Cite each claim in Key claims and Evidence, or label it as an inference. It does not enforce minimum quote counts, coverage depth or prose quality; check the brief's minimums separately. Fix every error and re-run until it prints `ok: N files`. "Found elsewhere: fix the timestamp" means the quote exists but you cited the wrong block. Never fix a speaker mismatch by renaming to a label you believe is wrong: drop the quote and log a `speaker_doubts` entry.

## Report back (short)

- Pages written (count), and the check's final output line.
- Any proposals filed under `ingest/proposals/` for protected pages.
- New slugs not in the seed vocabulary (slug, type, one line each).
- Conflicts, speaker doubts, and anything odd about the material (wrong speaker labels, missing transcript stretches, unreadable PDF pages).
- Stop and report if you're blocked for more than 30 minutes on one problem.

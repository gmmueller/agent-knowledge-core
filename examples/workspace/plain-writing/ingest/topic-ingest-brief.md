# plain-writing ingest brief (for batch workers)

You are ingesting part of the **plain-writing brain**: a topic brain on clear English prose. It is built from the 1918 Strunk text, four lectures from the 1916 Quiller-Couch edition, and Chapter I of the 1906 Fowlers in the shared library (`examples/workspace/library/<publisher>/raw/`). You turn raw files into **wiki source pages** (and example pages, where your batch marks them), plus **staging notes** that a later merge pass uses to build shared concept, rule, rubric and debate pages.

Fill in every `field` and the "fill in per brain" sections before dispatching a worker. This brief must stand alone: the worker sees nothing else of the conversation.

Paths below are relative to the workspace `examples/workspace` unless they start with `tools/` (relative to `.`). Run Python as `python -X utf8 -I` (your venv's Python). Never use `python3`, and never pipe a script into a bare `python -` (both hang in agent shells): write a script file or use `-c`. Write UTF-8, and never use PowerShell `Set-Content`.

Read first (framework references are relative to the framework repository root):
1. `AGENTS.md` (core rules).
2. `docs/library.md` (raw formats, speakers, citations).
3. `plain-writing/brain.md` (scope, evidence types, experts, extraction areas, what the brain must never do).
4. The gold example `plain-writing/wiki/sources/strunk-paragraphs.md`. Copy its shape. If it comes from another brain, ignore its topic.

## What you write (and nothing else)

1. For each item in your batch, ONE of:
   - `plain-writing/wiki/sources/<slug>.md` (type `source`): every item except those marked `page: example` in your batch. When the batch gives a page range of a book or paper, write **one page per chapter or section**.
   - `plain-writing/wiki/examples/<slug>.md` (type `example`): items marked `page: example` (a live diagnosis or demonstration of one real case). Omit this line for brains without example pages.
   Slug: `<publisher>-<short title slug>`, kebab-case, at most 60 characters (for example `strunk-paragraphs`).
2. `plain-writing/ingest/staging/<batch>.yaml`: one file for your whole batch.

Write nothing else. Never edit `library/` (raw is immutable). Don't run git. Don't install anything. Other workers are writing other batches at the same time.

## Hard rules for this brain: fill in per brain

Use only the selected public-domain editions. Name the author on every quote. Treat the Fowlers as one voice. Preserve historical wording; do not endorse dated social judgments. Use paragraph citations for HTML and original scan PDF pages for the book. Source-page publication years come from the edition registry when HTML metadata is blank. Mark unsupported additions **Inference:**. No example-video pages are assigned.


## Source page format

- **Frontmatter:**
  - `type: source`
  - `sources: [library/<publisher>/raw/<path>.md]` (every raw file you cite, with `.md`)
  - `updated: 2026-11-20`
  - `publisher`, `item` (`<publisher>/<source_id>`), `url`, `title`, `published`, `method` and `speaker_method` (copied from raw)
  - `speakers` (who talks); for books, papers and rulebooks, `authors` instead
  - `pages: <first>-<last>` for a book section (PDF page numbers); `duration` for video or audio
  - `evidence:` one of practitioner (a teacher’s argument and examples; not empirical research) (defined in `brain.md`; `inference` is always allowed)
  - `freshness: evergreen | platform | tool-version | dated` (use anything but `evergreen` for platform behaviour, tool versions, prices and other dated facts)
  - publication_precision: year; paragraphs: first-last for HTML sections
- `# <title>` (for a section: `# <Document>: <section title>`)
- **Summary:** one paragraph of 3–6 sentences: who speaks or wrote it (host vs guest), what they teach, and how strong the support is (study, own numbers, client cases, anecdote). Link concepts with `[[slug]]`.
- **`## Key claims`:** 8–25 bullets (more for a two-hour item or a long chapter). Each is one claim in your words, **attributed** ("X argues…", "the rulebook says…"), followed by its citation. Capture the *reasoning* behind a recommendation, not just the recommendation. Anything not directly supported is a bullet starting `- **Inference:**`.
- **`## Evidence`** (papers and chapters that report studies only): one bullet per study: design, sample and medium, the main result, and the authors' own limits. Say plainly when a point rests on an anecdote or a case, not a study.
- **`## Quotes`:** 5–14 exact quotes: `> "exact words" — <Speaker or Author> ([[library/<publisher>/raw/<path-without-.md>]] @ <where>)`. Every quote names its speaker, written as in the block's speaker prefix. Books and papers: the author(s) as in the raw frontmatter. Rulebooks: the issuing body. In staging, put `speaker:` on every quote.
- **`## Examples`:** one bullet per case the source uses (a channel, a video, a client, a hand, a story): what happened, what the speaker says it shows, any numbers (marked self-reported where they are), and the citation. Cases illustrate; they don't prove.
- **`## Concepts`:** bullets of `[[slug]]: how this source uses it`.

### Example page format (only for items marked `page: example`)

A live diagnosis or demonstration of one real case. The page is a **case**, written so a reader can learn the reasoning.

- **Frontmatter:** `type: example`, `sources` (the raw transcript and, for measured videos, `library/<publisher>/examples/<item-id>.yaml`), `updated`, `item`, `url`, `title`, `published`, `duration`, `method`, `speaker_method`, `speakers`, `evidence`, `freshness`, plus `not applicable: no example-video pages` (for example `subject:` the case under review and `diagnosed_by:`).
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
Do not treat literary authority as empirical proof. Record the acknowledged Strunk → Quiller-Couch → Fowler dependencies.

## Staging file: `plain-writing/ingest/staging/<batch>.yaml`

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
    status: bench             # leave bench; the merge pass sets the status
    name: "Test every idea before making it"
    summary: "..."
    points: []
    quotes:
      - text: "<exact words>"
        speaker: The Expert
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
- **Be generous.** The merge pass works only from staging plus your pages, so anything you leave out is lost. Aim for every 20 minutes of talk, or every chapter, to feed 6–15 concepts.
- **Types:** topic = a subject area; principle = a belief or truth the experts teach; method = a step-by-step how-to; framework = a named multi-part model; glossary = a term; **rule** = an imperative the brain should apply when answering or making things (slug starts with `rule-`, needs at least one exact quote by the person who says it); **rubric** = how a source *judges* something, with the criteria as points; **tool** = a platform feature, metric or product as its owner defines it, dated, with `reviewed: <today>` and `recheck_by: <today + 90 days>` (a creator's use of a metric is a `topic`, not a `tool`). Facts that are not guidance for the brain (a game rule, a definition) go in points under a topic or method, not in a `rule` page.
- **Slugs** are kebab-case and unique wiki-wide. Before inventing one, check `plain-writing/ingest/slugs.txt` (concepts from earlier waves, if it exists) and the seed vocabulary below. Reuse a slug whenever the idea matches, and put sub-parts in points instead of new slugs. If `plain-writing/ingest/slug-map.yaml` exists, never use a slug that appears as a key in it: use its canonical slug. New slugs need a genuinely new idea with three or more points; the merge pass folds thin ones.

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

List canonical slugs, grouped by area, before dispatching. Reuse them. Add the extra staging fields your brain uses (for example `variant`, `kind`, `freshness`) and what each value means.

## Acceptance check (must pass before you report)

```
python -X utf8 -I "./tools/check_wiki.py" --brain "examples/workspace/plain-writing" <page files...> "examples/workspace/plain-writing/ingest/staging/<batch>.yaml"
```

For this portable example, resolve the shown paths from the framework repository root. It verifies frontmatter, that citations resolve to a real block, that quotes are verbatim at the cited block, that each quote's speaker matches the block's speaker, and that key claims are cited. Fix every error and re-run until it prints `ok: N files`. "Found elsewhere: fix the timestamp" means the quote exists but you cited the wrong block. Never fix a speaker mismatch by renaming to a label you believe is wrong: drop the quote and log a `speaker_doubts` entry.

## Report back (short)

- Pages written (count), and the check's final output line.
- New slugs not in the seed vocabulary (slug, type, one line each).
- Conflicts, speaker doubts, and anything odd about the material (wrong speaker labels, missing transcript stretches, unreadable PDF pages).
- Stop and report if you're blocked for more than 30 minutes on one problem.

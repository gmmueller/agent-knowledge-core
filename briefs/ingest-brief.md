# {{brain_name}} ingest brief (for batch workers)

You are ingesting part of the **{{brain_name}} brain**: {{expert_name}}'s {{source_scope}}, transcribed into `{{brain_path}}/raw/`. You turn raw files into **wiki source pages**, plus **staging notes** that a later merge pass uses to build shared topic, framework and rule pages.

All paths below are relative to `{{brain_path}}` unless they start with `tools/` (relative to `{{framework_path}}`). Fill in every placeholder before dispatching a worker. This brief is self-contained: use primary sources only (the expert's own words, no third-party summaries), keep source text private (never paste it into external services), write UTF-8 (never PowerShell `Set-Content`), and run Python as `python -X utf8 -I` (never `python3` on Windows, never a bare `python -`).

## Reading budget

- Read only the files this brief and your batch list: the gold example `{{gold_source_page}}`, your batch entries in `ingest/batches.yaml`, and your assigned raw files.
- Do not open `AGENTS.md`, `docs/workspace.md`, or other workspace-wide docs.
- Read each raw file once, in full.
- Batch several small reads into one command where possible.
- Do not re-read a file you just wrote to check it; run `check_wiki.py` instead.

## What you write (and nothing else)

1. `wiki/sources/<id>.md`: one page per item in your batch (ids and raw paths are listed in your task and in `ingest/batches.yaml`).
2. `ingest/staging/<batch>.yaml`: one file for your whole batch.

**Protected pages (from `wiki_edits.py begin`):** {{protected_pages}}

Never edit any page on that list, and never create, edit or delete anything in `notes/`. If your batch needs to update a protected page, write the proposed full page to a temporary file and file it with `python -X utf8 -I "{{framework_path}}/tools/wiki_edits.py" --brain "{{brain_path}}" propose <page> --from <file> --why "<reason>"` (saves under `ingest/proposals/`), then list it in your report.

Don't create or edit any other file. Never edit `raw/` (it is immutable). Don't run git. Don't install anything. Other workers are writing other batches at the same time.

## Source page format

Copy the shape of the gold example **`{{gold_source_page}}`** exactly (read it first; don't rewrite it).

- **Frontmatter:** `type: source`, `sources: [raw/...md]`, `updated: {{date}}`, `product`, `module`, `lesson` (the lesson title), `duration` (if video), `url`, `method` (copy from the raw frontmatter), and `speakers` if the raw file has it. For attachments (`raw/_attachments/...`), use `lesson:` for the file's title, `url:` from the raw frontmatter, and put the lesson ids from `referenced_by` in a `referenced_by:` list.
- `# <lesson title>`
- **Summary:** one paragraph of 3–6 sentences: what the lesson teaches and how it fits the course. Name concepts with `[[slug]]` links.
- **`## Key claims`:** 6–15 bullets for a normal lesson (fewer for short or text-only items, more for a 60+ minute session). Each bullet is one claim in your own words, followed by its citation. Anything not directly supported by the source is a bullet starting `- **Inference:**` (no citation needed).
- **`## Quotes`:** 5–12 exact quotes in the format `> "exact words" — ([[raw/<path-without-.md>]] @ <where>)`. One per line, no blank lines between them. A quote with no name is {{expert_name}}'s. If anyone else said it ({{other_speaker}}, a guest, a team member), put their name before the citation: `> "exact words" — {{other_speaker}} ([[raw/...]] @ <where>)`. In staging, add `speaker: <name>` to that quote item.
- **`## Concepts`:** bullets of `[[slug]]: how this source uses it`.

### Citations and quotes (the checker enforces these)

- Citation: `([[raw/<path without .md>]] @ <where>)`, where `<where>` is:
  - the block label of a transcript paragraph, exactly as it appears in bold at the start of the block (e.g. `**[12:58]**` → `@ 12:58`). Use the block where the quoted words, or the supporting statement, **start**.
  - `@ p. N` for PDF attachments (the `**[p. N]**` blocks).
  - `@ page text` for the `## Lesson page text` section, and for text-only lessons.
- Quotes are **verbatim and contiguous**: copy-paste from the raw file. No ellipses, no brackets, no fixing of grammar or filler words, no joining of separate sentences. You may start or end mid-sentence. Keep each quote ≤ 40 words.
- Choose quotes that carry teaching value or show {{expert_name}}'s voice: rules of thumb, definitions, signature phrases, strong claims. Avoid filler and promos.

### Speaker and transcription caveats

- Files with `speakers: "multi: ..."` (identified in `crawl.yaml` under `multi_speaker`, or in the raw frontmatter) contain co-hosts and attendees. Only put words in **Quotes** when they are clearly {{expert_name}}'s: the expert is presenting, says "I" about their own work or {{organization}}, or is introduced or named. When unsure, paraphrase in Key claims and attribute it ("a co-host says…", "an attendee asks…"). Never present someone else's words as {{expert_name}}'s.
- Q&A lessons: the question comes from a member; the answer is the expert's (or the named presenter's). Confirm the speaker from the raw context.
- `method: whisper` files were machine-transcribed without captions: proper names may be misspelled. Don't build claims on an uncertain name. Write "(name uncertain in transcript)" when it matters.
- Some lessons are presented by {{organization}} team members rather than {{expert_name}}. If the speaker introduces themselves, note it in the summary and in `speakers:` in your staging entry for that lesson (see below). Their words still count as course material.
- Promos (gear guides, affiliate tools, events, upsells): at most one clause in the summary; never a concept.

## Staging file: `ingest/staging/<batch>.yaml`

```yaml
batch: {{batch_id}}
lessons:                     # every item you wrote a source page for
  - id: {{lesson_id}}
    presenter: "{{expert_name}}"  # or named presenter(s); "unknown" if unclear
concepts:                    # every concept your batch teaches something about
  - slug: {{framework_slug}} # reuse a seed slug when it is the same idea
    type: framework          # topic | principle | method | framework | rule | glossary
    name: "{{framework_name}}"
    aliases: ["{{framework_alias}}"]
    summary: "One or two sentences on what your batch's sources say this is."
    points:                  # distinct teaching points, each cited (no quote needed)
      - text: "{{paraphrased_teaching_point}}"
        cite: {raw: "raw/{{product}}/{{module}}/{{lesson}}", at: "1:07"}
    quotes:                  # exact quotes, same rules as source pages
      - text: "{{exact_quote}}"
        cite: {raw: "raw/{{product}}/{{module}}/{{lesson}}", at: "0:00"}
      - text: "{{other_speaker_exact_quote}}"
        speaker: "{{other_speaker}}"
        cite: {raw: "raw/{{product}}/{{module}}/{{lesson}}", at: "2:00"}
  - slug: rule-{{rule_slug}}
    type: rule
    name: "{{imperative_rule}}"
    summary: "{{rule_summary}}"
    points: []               # use the cited point shape above
    quotes:                  # rules need at least one exact quote
      - text: "{{exact_rule_quote}}"
        cite: {raw: "raw/{{product}}/{{module}}/{{lesson}}", at: "1:07"}
voice:                       # the expert's phrases, metaphors, catchphrases (exact quotes)
  - text: "{{exact_voice_quote}}"
    cite: {raw: "raw/{{product}}/{{module}}/{{lesson}}", at: "18:21"}
    note: "signature phrase; recurs"
conflicts:                   # optional: sources disagree (numbers, changed advice)
  - text: "Lesson X says A; lesson Y says B."
    cites: [{raw: "{{first_raw_path}}", at: "{{first_locator}}"}, {raw: "{{second_raw_path}}", at: "{{second_locator}}"}]
```

- **Types:** topic = a subject area; principle = a belief or truth the expert teaches; method = a step-by-step how-to; framework = a named multi-part model; rule = an imperative the persona should enforce (slug starts with `rule-`, needs ≥1 exact quote); glossary = a term or acronym definition.
- Be generous with points and quotes for concepts; the merge pass works only from staging plus source pages, so anything you leave out is lost. Aim for every lesson to feed 3–10 concepts.
- Slugs are kebab-case and unique wiki-wide. Before inventing a slug, check the vocabulary. If your idea is a sub-part of a seed concept, use the seed slug and put the detail in points.

## Seed vocabulary: fill in per brain

{{seed_vocabulary}}

List canonical slugs, aliases and short definitions for frameworks, methods, principles, topics, rules and glossary terms before dispatching. Reuse these slugs; put sub-parts in the seed concept's points. Keep a shared vocabulary across batches.

## Acceptance check (must pass before you report)

```sh
python -X utf8 -I "{{framework_path}}/tools/check_wiki.py" --brain "{{brain_path}}" "{{brain_path}}/wiki/sources/<id>.md" ... "{{brain_path}}/ingest/staging/<batch>.yaml"
```

Use absolute paths for the brain and page files. It verifies frontmatter, that every citation resolves to a real raw file and block, that every quote is verbatim at the cited block, and that every key claim is cited. Fix every error, then re-run until it prints `ok: N files`. A "found elsewhere: fix the timestamp" error means the quote exists but you cited the wrong block.

## Report back (short)

- Pages written (count) and the check's final output line.
- Any proposals filed under `ingest/proposals/` for protected pages.
- New slugs you introduced that are not in the seed vocabulary (slug, type, one line each).
- Conflicts found, unclear presenters, uncertain names, and anything odd about the material.
- Limits: stop and report if you're blocked for more than 30 minutes on one problem.

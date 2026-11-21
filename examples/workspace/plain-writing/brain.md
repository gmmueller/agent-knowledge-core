---
name: plain-writing
display_name: Plain Writing
kind: topic
status: ready
updated: '2026-11-20'
build:
  pipeline: 2
triage:
  weight_fresh: false
experts:
- William Strunk Jr.
- Arthur Quiller-Couch
- H. W. Fowler and F. G. Fowler
expert_aliases:
  H. W. Fowler: H. W. Fowler and F. G. Fowler
  F. G. Fowler: H. W. Fowler and F. G. Fowler
rule_status: voices
voice_aliases: {}
hosts: []
official: []
evidence_types:
- practitioner
refresh:
  reminders: false
skill:
  description: 'Consult the plain-writing example brain for clear English prose: word choice, concision, paragraph
    structure, sentence order, jargon and revision, using Strunk, Quiller-Couch and the Fowlers. Name the author,
    cite the book and show disagreements.'
  short_description: Clear prose from three public-domain writing books
  default_prompt: Use $plain-writing to revise this prose, naming the methods and citing the sources.
---

# Plain Writing

A small topic brain about clear English prose, compiled from the authors’ own public-domain books. It applies attributed methods without imitating a composite author’s voice. **Inference:** This is an educational example, not a complete contemporary usage authority.

## Scope

- **Covers:** clarity, word choice, concision, paragraph development, sentence relationships, jargon and revision in ordinary explanatory prose.
- **Hands off to:** a current house style guide for present editorial conventions; a subject expert for technical correctness; a specialist in the requested dialect for current usage.
- **Boundaries:** attribute prescriptions to the author and edition; keep historical social judgments in their historical context. Do not present the books as experimental proof. Mark new checklists and rewrites **Inference:**. Preserve the original meaning when revising; request clarification where it is indeterminate.

## Evidence types

`practitioner` means a writing teacher’s argument and illustrative examples. It is not a controlled study. `inference` marks the wiki’s own application or synthesis beyond what a source directly says. `freshness: evergreen` describes the subject of a recommendation, not proof that every convention still holds. Historical spelling and dialect prescriptions use `freshness: dated`.

## Experts

| Expert | Teaches | Publisher |
|---|---|---|
| William Strunk Jr. | Everyday composition, usage and form | strunk |
| Arthur Quiller-Couch | Practice, jargon, prose and style | quiller-couch |
| H. W. Fowler and F. G. Fowler | Vocabulary and register | fowler |

The Fowlers are one co-authored voice. **Inference:** Distinct voices in this example mean separately attributed authorship, not experimentally independent evidence. Strunk recommends Quiller-Couch, and Quiller-Couch borrows an example from the Fowlers; preserve those dependencies when describing agreement. See [[strunk-introduction]] and [[quiller-couch-jargon]].

## Extraction areas

1. Meaning made clear through familiar, concrete and economical language.
2. Paragraph organization and sentence relationships.
3. Register, occasion, reader attention and justified exceptions.
4. Revision methods and the limits of historical usage advice.

Exclude later revisions, modern summaries and unselected chapters. Strunk’s six chapters are captured in full. Quiller-Couch is limited to lectures II, V, VI and XII; Fowler to Chapter I’s General section and its Neologisms-through-end sections, divided into general principles and vocabulary in use. The unselected Malaprops section is omitted from the final capture.

## Task loop

1. Identify the purpose, audience and dialect; clarify ambiguous meaning before revising it.
2. Read `wiki/index.md`, then the matching concept, rule and source pages.
3. Apply the author’s method, naming whose it is and citing raw paragraph or PDF page blocks.
4. Consult debates for differences in emphasis or actual disagreement.
5. Label a new rewrite or a combined checklist **Inference:**. Check it against meaning, structure, wasted words and suitability to the reader.
6. Separate a book’s historical prescription from current usage; say when the material does not answer.

## Rules

Use `wiki/rules/` as the rule register. Every rule has exact author-named quotes. `rule_status.py --write` computes `consensus` for two listed voices and `bench` for one. `active` means two other independent voices; `contested` requires opposition to the rule itself plus a debate page. The debates here concern emphasis and etymological limits, so they do not by themselves contest the concision or clarity rules.

## Deliverables

See `wiki/index.md`, `evals.md`, filled briefs and extraction staging in `ingest/`, and the portable sample skill in `examples/skills/plain-writing/`. The sample skill resolves its relative paths from the framework repository root. Cold evaluation is a separate test: the supplied evals are an answer key, not a claimed fresh-agent run.

---
name: my-topic
display_name: "My Topic"
kind: topic
status: scoping
updated: YYYY-MM-DD
build:
  pipeline: 2                 # docs/build-pipeline.md; library-based topic brain
triage:
  weight_fresh: false         # true = count the `fresh` score in tiers (fast-moving topics). triage_merge.py reads this
experts: [The Expert, Another Expert]   # rule consensus: 2+ of these support, none oppose
expert_aliases:               # speaker label -> the expert it counts as (nicknames, duos that count once)
  Expert: The Expert
  Another: Another Expert
rule_status: voices           # active = 2+ independent voices; one author repeating a rule across a book and talks stays bench
voice_aliases: {}             # speaker label -> voice, for groups that speak as one (platform staff: "Staff Name: The Platform")
hosts: []                     # interviewers and presenters; their claims never back a rule
official: []                  # bodies whose documents count as official sources (rule bodies, platforms, regulators); documentation for writers
evidence_types: [research, synthesis, official, practitioner, example]   # check_wiki.py validates `evidence:` against this ("inference" is always allowed)
refresh:
  reminders: true             # false = refresh_due.py never lists this brain
skill:
  description: "Consult the my-topic brain: <scope in one sentence>, compiled from the experts' own words into a cited wiki. Use for <tasks>, or when the user says \"consult my-topic\". Answers cite sources and name whose method."
  short_description: "<One line: what the brain knows>"
  default_prompt: "Use $my-topic to answer this, citing sources and naming whose method it is."
  # guidance:                 # optional: subject-specific rules rendered under "## This brain's guidance"
  #   - "State the date on time-sensitive claims and prefer the newest official source."
  # boundaries:               # optional: extra bullets appended to "## Boundaries"
  #   - "**No promised outcomes.** Apply the experts' methods; never promise results."
---

# My Topic

One paragraph: what this brain is a specialist in, which experts it draws on, and what it is compiled from. It has no imitated voice: it applies the experts' methods, names whose they are, and cites every claim to the library.

## Scope

- **Covers:** <what this brain knows and should be consulted on>
- **Hands off to:** <sibling brain or skill for each out-of-scope neighbour>
- **Doesn't:** <hard limits: material it must not reproduce, claims it must not make, things it must never assume>

## Evidence types

Every principle, method, rule and topic page carries `evidence:` with one of the values in the frontmatter's `evidence_types`. Define each:

| Value | Meaning |
|---|---|
| `research` | a peer-reviewed study. Say observational or experimental, and the population |
| `synthesis` | an author's framework built from research and cases |
| `official` | the platform or rule body about itself. Dated |
| `practitioner` | a working creator or teacher describing their own system or results |
| `example` | a measured or annotated demonstration of one real case |

Change the list to fit the topic (frontmatter and this table together). Add `freshness: evergreen | platform | tool-version | dated` to anything that changes over time.

## Experts

Experts are speakers. Their material sits under whichever publisher hosts it (`docs/library.md`).

| Expert | Priority | Teaches | Main library sources |
|---|---|---|---|
| The Expert | P0 | <topics> | `example-publisher` |
| Another Expert | P1 | <topics> | `another-publisher` |
| Official voices | official | <what they can state as fact> | their publishers |

## Extraction areas (triage rubric)

An item scores on **relevance** when it teaches one or more of:

1. <area one>
2. <area two>
3. <area three>

Skip any item that <exclusion, if any>.

## Task loop

1. Name the job: <the kinds of request this brain gets>.
2. Use the concept index and search to find the relevant concept, rule and rubric pages.
3. Answer with the experts' methods, naming whose, and cite each one.
4. Where experts disagree, show the debate page's positions instead of picking silently.
5. Check the result against the relevant rubric, and show the check.
6. Label anything the wiki doesn't support as **Inference:**.

## Rules

Rule pages live in `wiki/rules/`, each with exact, speaker-named quotes. Status:
- `consensus`: 2+ listed experts explicitly support it and none oppose it.
- `active`: 2+ independent voices.
- `contested`: a source argues against the rule, and the rule links a debate page.
- `bench`: fewer than two independent supporting voices.

## Deliverables (definition of done)

- Wiki: concept pages (topics, principles, methods, frameworks, rules, glossary), rubrics, example pages, tool pages and debate pages, all passing `check_wiki.py` and `lint_wiki.py`.
- `evals.md`: task-based evals plus traps, run by a fresh agent with only the skill.
- Generated skill `/my-topic` via `tools/generate_persona.py`.

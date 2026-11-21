# Architecture

The public framework contains tools, documentation, briefs and two skeletons (`template/` for persona brains, `template-topic/` for topic brains). The private workspace contains the actual brains and source material. Copy a template to `<workspace>/<name>/`; keep the workspace separate from this repo and never publish it.

## Two kinds of brain

| Kind | Example | Knowledge from | Voice |
|---|---|---|---|
| `persona` (also `course`, `community`) | `my-course` | its own `raw/` | imitates one teacher, with signature phrases |
| `topic` | `my-topic` | the shared `library/` (crawled once per publisher), selected per brain through triage | a specialist with no imitated voice; every quote names its speaker |

Library layout and formats: `docs/library.md`. Item selection: `docs/triage.md`. Topic brains add the page types `example`, `rubric`, `tool` and `debate`, and the rule statuses `consensus` and `contested`.

**Rebuilds.** Library raw, catalogues and `selection.yaml` are inputs. A brain's `wiki/` is a build output tagged `build: { pipeline: N }` in `brain.md`. To rebuild with a better method, build on a branch, run the same `evals.md` on old and new, and merge only if the new one scores at least as well.

## Pieces

| Piece | Where | Role |
|---|---|---|
| Brain folder | `<workspace>/<name>/` | Persona brain: raw sources, wiki and persona card. Topic brain: wiki, selection and ingest working files |
| `brain.md` | Brain folder | Single source of truth for scope, rules, refresh policy and `skill:` trigger text. Topic brains also keep their expert lists and evidence types here (see `template-topic/brain.md`) |
| `sources.yaml` | Brain folder | Source registry, titles, access methods, cadence and incremental cursors (persona brains). Topic brains register sources per publisher in the library |
| `crawl.yaml` | Brain folder (optional) | Platform, site, browser port, product mapping, transcription settings and multi-speaker flags |
| `outline.yaml` | Brain folder | Course products, modules, lessons, media ids and attachments |
| `selection.yaml` | Topic brain folder | Library items the brain uses, with a tier and triage scores per item |
| `library/` | Workspace | Shared immutable sources, one folder per publisher, plus `people.yaml` (who speaks where) |
| Generated skill | `<skills-directory>/<name>/` | Thin loader: reads `brain.md` and wiki at use time; broad lookups may use one delegated worker |
| Shared briefs | Framework `briefs/` | Templates for isolated ingest, concept-page and debate-page workers |
| Search | Local qmd collections | Persona brains: `<name>-wiki` and `<name>-raw`. Topic brains: `<name>-wiki`, plus one shared `library` collection |
| Hooks (optional) | Private workspace | Enforce a non-negotiable workflow rule |
| Dedicated persona agent (future) | User's agent directory | Optional named agent wrapper if the user's tooling needs one |

The generator writes `SKILL.md` and `agents/openai.yaml` from `brain.md`. Give `tools/generate_persona.py --brain <path> --out <skills-directory>`, or set `AGENT_KNOWLEDGE_CORE_SKILLS_DIR`. `--out` is the skills **parent** folder: the generator creates `<name>/` inside it, so passing the skill folder itself writes a nested copy. Normal use writes absolute paths; pass `--relative-to <dir>` to write portable paths relative to `<dir>` for a shareable sample skill. Topic-brain skills mention annotated examples and platform evidence only when the brain has them. Distribution into the user's agent tooling is a separate workspace concern. Regenerate after changing `brain.md`; edit the source, never the generated loader.

## Flow

Persona brain:

```text
sources -> crawl -> raw/ -> ingest -> wiki/ -> extract -> brain.md -> generate -> skill
                                      ^                                      |
                                      +---- file useful answers back <- query+
```

Topic brain:

```text
library (crawl once) -> catalogue -> triage -> selection.yaml -> fetch -> speaker pass
   -> ingest waves -> merge (bundles) -> concept pages -> debates -> rule audit -> draft skill -> evals -> regenerate skill
```

Both flows end the same way: queries that produce something valuable get filed back into the wiki.

## Persona boundaries

A source persona teaches what the expert's material says. The user's own persona skills are separate voices. If a council uses both, each identifies which view it represents. Unsupported advice is marked **Inference:**.

## Workspace hygiene

Gitignore `.secrets/` at the workspace root, `*/media/` for each brain, and `library/*/media/` and `library/*/staging/`. Browser profiles, caches and scratch stay in `.secrets/`; course media stays in the brain's `media/`. `raw/` is immutable after capture, while `wiki/` and `brain.md` evolve through logged ingests and refreshes.

## Shared-library brains

Topic brains (`kind: topic`) combine experts without imitating one voice. Their citations address `<workspace>/library/<publisher>/raw/`; every quote names its speaker. `check_wiki.py` supports paragraph locators (`@ ¶N`), speaker aliases in `library/people.yaml`, the extra page types (`example`, `rubric`, `tool`, `debate`) and the topic rule statuses (`consensus`, `contested`). A contested rule links to a debate page. See `docs/library.md` for the shared-source design, `docs/triage.md` for selection and `docs/build-pipeline.md` for the topic-brain pipeline and the tool list by stage.

A topic brain finds the library at `<workspace>/library`, where `<workspace>` is the folder that holds the brain. Tools that touch only the library take `--workspace <workspace>`. Tools that work on one brain take `--brain <brain-folder>` and locate the library from it.

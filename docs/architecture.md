# Architecture

The public framework contains tools, documentation, briefs and a skeleton. The private workspace contains the actual brains and source material. Copy `template/` to `<workspace>/my-course/`; keep the workspace separate from this repo and never publish it.

## Pieces

| Piece | Where | Role |
|---|---|---|
| Brain folder | `<workspace>/<name>/` | Raw sources, wiki and persona card |
| `brain.md` | Brain folder | Single source of truth for the persona, refresh policy and `skill:` trigger text |
| `sources.yaml` | Brain folder | Source registry, titles, access methods, cadence and incremental cursors |
| `crawl.yaml` | Brain folder (optional) | Platform, site, browser port, product mapping, transcription settings and multi-speaker flags |
| `outline.yaml` | Brain folder | Course products, modules, lessons, media ids and attachments |
| Generated skill | `<skills-directory>/<name>/` | Thin loader: reads `brain.md` and wiki at use time; broad lookups may use one delegated worker |
| Shared briefs | Framework `briefs/` | Templates for isolated ingest and concept-page workers |
| Search | Local qmd collections | One `<name>-wiki` and one `<name>-raw` collection per brain |
| Hooks (optional) | Private workspace | Enforce a non-negotiable workflow rule |
| Dedicated persona agent (future) | User's agent directory | Optional named agent wrapper if the user's tooling needs one |

The generator writes `SKILL.md` and `agents/openai.yaml` from `brain.md`. Give `tools/generate_persona.py --brain <path> --out <skills-directory>`, or set `CREATE_A_BRAIN_SKILLS_DIR`. Distribution into the user's agent tooling is a separate workspace concern. Regenerate after changing `brain.md`; edit the source, never the generated loader.

## Flow

```text
sources -> crawl -> raw/ -> ingest -> wiki/ -> extract -> brain.md -> generate -> skill
                                      ^                                      |
                                      +---- file useful answers back <- query+
```

## Persona boundaries

A source persona teaches what the expert's material says. The user's own persona skills are separate voices. If a council uses both, each identifies which view it represents. Unsupported advice is marked **Inference:**.

## Workspace hygiene

Gitignore `.secrets/` at the workspace root and `*/media/` for each brain. Browser profiles, caches and scratch stay in `.secrets/`; course media stays in the brain's `media/`. `raw/` is immutable after capture, while `wiki/` and `brain.md` evolve through logged ingests and refreshes.

## Shared-library brains

Topic brains (`kind: topic`) combine experts without imitating one voice. Their citations address `<workspace>/library/<publisher>/raw/`; every quote names its speaker. `check_wiki.py` supports paragraph locators (`@ ¶N`), speaker aliases in `library/people.yaml`, additional page types (`example`, `rubric`, `tool`, `debate`) and topic rule statuses (`consensus`, `contested`). A contested rule links to a debate page. See `docs/library.md` for the shared-source design and `docs/triage.md` for selection; source acquisition and triage for that extension are outside this port.
